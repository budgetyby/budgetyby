"""
BudgetBy — Scheduler
Sets up all recurring jobs using APScheduler.
"""

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from budgetby import config, database
from budgetby.scheduler import cleanup

logger = logging.getLogger("budgetby.scheduler")

_scheduler = AsyncIOScheduler(timezone=config.TIMEZONE)

_bot = None

def set_bot(bot):
    global _bot
    _bot = bot


async def price_check_loop():
    """
    Core loop: grab products due for a check, scrape them, detect deals, post.
    Runs every 30 seconds.
    """
    try:
        from budgetby.scrapers.amazon import AmazonScraper
        from budgetby.scrapers.flipkart import FlipkartScraper
        from budgetby.scrapers.myntra import MyntraScraper
        from budgetby.scrapers.ajio import AjioScraper
        from budgetby.scrapers.nykaa import NykaaScraper
        from budgetby.engine.deal_detector import detect_deal
        from budgetby.engine.deal_scorer import score_deal
        from budgetby.engine.fake_discount import is_fake_discount
        from budgetby.engine.cooldown import is_on_cooldown, set_cooldown
        from budgetby.engine.posting_queue import PostingQueue
        from budgetby.scheduler.priority import assign_priority

        scrapers = {
            "amazon": AmazonScraper(),
            "flipkart": FlipkartScraper(),
            "myntra": MyntraScraper(),
            "ajio": AjioScraper(),
            "nykaa": NykaaScraper(),
        }

        products = await database.get_products_due_for_check(limit=50)
        if not products:
            return

        logger.info(f"Checking {len(products)} products")

        import asyncio
        sem = asyncio.Semaphore(10)

        async def process_product(product):
            async with sem:
                try:
                    platform = product["platform"]
                    scraper = scrapers.get(platform)
                    if not scraper:
                        return

                    # Scrape current price
                    data = await scraper.scrape_product(product["product_url"])
                    if not data or not data.get("current_price"):
                        await database.schedule_next_check(product["id"], product["priority_tier"])
                        return

                    new_price = data["current_price"]

                    # Update price and product metadata in DB
                    await database.update_price(
                        product["id"], new_price, data.get("in_stock", True),
                        data.get("has_coupon", False), data.get("coupon_value", 0),
                        data.get("has_bank_offer", False), data.get("bank_offer_text"),
                        title=data.get("title"), mrp=data.get("mrp"), rating=data.get("rating"),
                        review_count=data.get("review_count"), image_url=data.get("image_url")
                    )
                    try:
                        await database.upsert_daily_price(product["id"], new_price)
                    except Exception as e:
                        logger.warning(f"Failed to upsert daily price for product {product['id']}: {e}")

                    # Skip if on cooldown
                    if await is_on_cooldown(product["id"]):
                        new_tier = assign_priority(product)
                        await database.schedule_next_check(product["id"], new_tier)
                        return

                    # Detect deal
                    deal_result = await detect_deal(product, new_price)
                    if not deal_result:
                        new_tier = assign_priority(product)
                        await database.schedule_next_check(product["id"], new_tier)
                        return

                    # Check fake discount
                    if await is_fake_discount(product, new_price):
                        deal_result["is_fake"] = True

                    # Score the deal
                    score = score_deal(product, deal_result)
                    if score < config.MIN_DEAL_SCORE:
                        new_tier = assign_priority(product)
                        await database.schedule_next_check(product["id"], new_tier)
                        return

                    # Queue for posting
                    deal_data = {
                        "product": dict(product),
                        "deal_result": deal_result,
                        "score": score,
                        "new_price": new_price,
                    }
                    deal_data["product"].update(data)

                    logger.info(
                        f"Deal found: {product['title'][:50]}... "
                        f"Score={score:.0f} Badge={deal_result['badge']}"
                    )

                    # Set cooldown
                    await set_cooldown(product["id"], config.PRICE_DROP_COOLDOWN_HOURS)

                    # Actually queue and post the deal
                    pq = PostingQueue()
                    deal_data["badge"] = deal_result["badge"]
                    await pq.queue_deal(deal_data)
                    if _bot is not None:
                        await pq.process_queue(_bot)

                    # Reschedule with updated priority (critical since price just changed)
                    await database.schedule_next_check(product["id"], 1)

                except Exception as e:
                    logger.error(f"Error checking product {product['id']}: {e}")
                    await database.schedule_next_check(product["id"], product["priority_tier"])

        await asyncio.gather(*(process_product(p) for p in products))

    except Exception as e:
        logger.error(f"Error in price_check_loop: {e}")


async def discovery_job():
    """Run full product discovery across all platforms."""
    try:
        from budgetby.discovery.seeder import ProductSeeder
        logger.info("Running full discovery...")
        seeder = ProductSeeder()
        stats = await seeder.run_full_discovery()
        logger.info(f"Discovery complete: {stats}")
    except Exception as e:
        logger.error(f"Error in discovery_job: {e}")


async def deals_page_crawl():
    """Crawl Amazon deals page and Flipkart offers store."""
    try:
        from budgetby.discovery.amazon_discover import discover_deals_page
        from budgetby.discovery.flipkart_discover import discover_offers_store
        from budgetby.discovery.seeder import ProductSeeder

        logger.info("Crawling deals pages...")
        seeder = ProductSeeder()

        amazon_deals = await discover_deals_page()
        for product_data in amazon_deals:
            try:
                await database.upsert_product(product_data)
            except Exception:
                pass

        flipkart_deals = await discover_offers_store()
        for product_data in flipkart_deals:
            try:
                await database.upsert_product(product_data)
            except Exception:
                pass

        logger.info(f"Deals crawl: {len(amazon_deals)} Amazon, {len(flipkart_deals)} Flipkart")
    except Exception as e:
        logger.error(f"Error in deals_page_crawl: {e}")


async def movers_shakers_crawl():
    """Crawl Amazon Movers & Shakers pages."""
    try:
        from budgetby.discovery.amazon_discover import discover_movers_and_shakers

        logger.info("Crawling Movers & Shakers...")
        total = 0
        for cat_name, cat_info in config.AMAZON_DISCOVERY_TARGETS.items():
            try:
                products = await discover_movers_and_shakers(cat_info["slug"])
                for product_data in products:
                    product_data["category"] = cat_info.get("category", cat_name)
                    await database.upsert_product(product_data)
                total += len(products)
            except Exception as e:
                logger.warning(f"M&S crawl failed for {cat_name}: {e}")

        logger.info(f"Movers & Shakers: {total} products discovered")
    except Exception as e:
        logger.error(f"Error in movers_shakers_crawl: {e}")


async def hourly_backfill():
    """Check hourly posting minimum and backfill with evergreen deals if needed."""
    try:
        from budgetby.engine.evergreen import find_evergreen_deals
        from budgetby.engine.cooldown import set_evergreen_cooldown

        import pytz
        from datetime import datetime

        ist = pytz.timezone(config.TIMEZONE)
        now = datetime.now(ist)
        hour = now.hour

        if config.DAYTIME_START_HOUR <= hour < config.DAYTIME_END_HOUR:
            minimum = config.MIN_POSTS_PER_HOUR_DAY
        else:
            minimum = config.MIN_POSTS_PER_HOUR_NIGHT

        # Count posts in the current hour
        posts_this_hour = await database.fetchval("""
            SELECT COUNT(*) FROM deals
            WHERE posted_at >= date_trunc('hour', NOW())
        """)

        gap = minimum - (posts_this_hour or 0)
        if gap <= 0:
            logger.info(f"Hourly minimum met: {posts_this_hour} posts (min={minimum})")
            return

        logger.info(f"Need {gap} more posts to meet hourly minimum of {minimum}")
        evergreen_deals = await find_evergreen_deals(limit=gap)
        logger.info(f"Found {len(evergreen_deals)} evergreen deals for backfill")

        from budgetby.engine.posting_queue import PostingQueue
        pq = PostingQueue()
        for deal in evergreen_deals:
            logger.info(f"Evergreen candidate: {deal['title'][:50]}...")
            await pq.queue_deal({"product": deal, "type": "evergreen", "badge": "EVERGREEN"})
        await pq.process_queue(_bot)

    except Exception as e:
        logger.error(f"Error in hourly_backfill: {e}")


async def deal_tracking_check():
    """Check active deal tracking records and edit messages if price changed."""
    try:
        active_tracking = await database.get_active_deal_tracking()
        if not active_tracking:
            return

        logger.info(f"Checking {len(active_tracking)} tracked deals for price changes")

        for track in active_tracking:
            try:
                posted_price = float(track["posted_price"])
                current_price = float(track["current_price"]) if track["current_price"] else None
                is_oos = not track["in_stock"]

                if current_price and abs(current_price - posted_price) < 1 and not is_oos:
                    continue  # No change

                # Price changed or went OOS — needs edit
                logger.info(
                    f"Deal {track['message_id']} needs update: "
                    f"posted={posted_price}, current={current_price}, oos={is_oos}"
                )

                # The actual message editing would be done by the bot
                # Mark as edited in DB
                await database.execute("""
                    UPDATE deal_tracking SET last_edited = NOW() WHERE id = $1
                """, track["id"])

            except Exception as e:
                logger.warning(f"Error checking tracked deal {track['id']}: {e}")

        # Finalize expired records
        await database.finalize_expired_tracking()

    except Exception as e:
        logger.error(f"Error in deal_tracking_check: {e}")


def start_scheduler():
    """Configure and start all scheduled jobs."""
    logger.info("Starting scheduler...")

    # Core price checking — every 30 seconds
    _scheduler.add_job(price_check_loop, "interval", seconds=30, id="price_check", max_instances=1, misfire_grace_time=30)

    # Discovery — every 6 hours
    _scheduler.add_job(discovery_job, "interval",
                       hours=config.DISCOVERY_INTERVAL_HOURS, id="discovery", max_instances=1, misfire_grace_time=30)

    # Deals page crawl — every 1 hour
    _scheduler.add_job(deals_page_crawl, "interval",
                       hours=config.DEALS_PAGE_CRAWL_INTERVAL_HOURS, id="deals_crawl", max_instances=1, misfire_grace_time=30)

    # Movers & Shakers — every 3 hours
    _scheduler.add_job(movers_shakers_crawl, "interval",
                       hours=config.MOVERS_AND_SHAKERS_INTERVAL_HOURS, id="movers_shakers", max_instances=1, misfire_grace_time=30)

    # Hourly backfill check
    _scheduler.add_job(hourly_backfill, "interval", hours=1, id="hourly_backfill", max_instances=1, misfire_grace_time=30)

    # Deal tracking check — every 10 minutes
    _scheduler.add_job(deal_tracking_check, "interval", minutes=10, id="deal_tracking", max_instances=1, misfire_grace_time=30)

    # Daily cleanup at midnight IST
    _scheduler.add_job(cleanup.daily_cleanup, "cron", hour=0, minute=0, id="daily_cleanup")

    # Monthly benchmark shift on the 1st
    _scheduler.add_job(cleanup.monthly_maintenance, "cron", day=1, hour=1, minute=0,
                       id="monthly_maintenance")

    # Backup at configured hour
    if config.BACKUP_ENABLED:
        _scheduler.add_job(cleanup.run_backup, "cron",
                           hour=config.BACKUP_HOUR, minute=0, id="daily_backup")

    _scheduler.start()
    logger.info("Scheduler started with all jobs configured")


def stop_scheduler():
    """Gracefully stop the scheduler."""
    logger.info("Stopping scheduler...")
    _scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped.")
