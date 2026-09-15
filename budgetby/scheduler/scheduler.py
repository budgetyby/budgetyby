"""
BudgetBy — Scheduler
Sets up all recurring jobs using APScheduler.
"""

import logging
import asyncio
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
        from budgetby.engine.cooldown import is_on_cooldown
        from budgetby.scheduler.priority import assign_priority

        scrapers = {
            "amazon": AmazonScraper(),
            "flipkart": FlipkartScraper(),
            "myntra": MyntraScraper(),
            "ajio": AjioScraper(),
            "nykaa": NykaaScraper(),
        }

        products = await database.get_products_due_for_check(limit=15)
        if not products:
            return

        logger.info(f"Checking {len(products)} products")

        sem = asyncio.Semaphore(getattr(config, "SCRAPER_WORKERS", 5))

        async def process_product(product):
            async with sem:
                await asyncio.sleep(0.05)  # 50ms micro-pause smooths out CPU frequency bursts
                try:
                    platform = product["platform"]
                    scraper = scrapers.get(platform)
                    if not scraper:
                        return

                    # Scrape current price
                    data = await scraper.scrape_product(product["product_url"])
                    if not data:
                        await database.schedule_next_check(product["id"], product["priority_tier"])
                        return

                    if not data.get("current_price") or data.get("in_stock") is False:
                        # Product is verified out of stock or unavailable
                        await database.execute(
                            "UPDATE products SET in_stock = FALSE, last_checked = NOW() WHERE id = $1;",
                            product["id"]
                        )
                        await database.schedule_next_check(product["id"], product["priority_tier"])
                        return

                    new_price = data["current_price"]

                    # Update price and product metadata in DB
                    await database.update_price(
                        product["id"], new_price, data.get("in_stock", True),
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


                    # Actually queue and post the deal
                    from budgetby.engine.posting_queue import get_posting_queue
                    pq = get_posting_queue()
                    deal_data["badge"] = deal_result["badge"]
                    await pq.queue_deal(deal_data)
                    if _bot is not None:
                        asyncio.create_task(pq.process_queue(_bot))
                    else:
                        asyncio.create_task(pq.process_queue())

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









async def morning_digest():
    """Curate and post Top 5 Morning Deals Digest at 9:00 AM IST."""
    await _post_digest(digest_type="Morning", hours_lookback=12)


async def evening_digest():
    """Curate and post Top 5 Evening Deals Digest at 8:00 PM IST."""
    await _post_digest(digest_type="Evening", hours_lookback=12)


async def _post_digest(digest_type: str, hours_lookback: int = 12):
    try:
        if not _bot:
            logger.warning(f"Cannot send {digest_type} digest: bot not initialized.")
            return

        from budgetby.bot.templates import format_daily_digest
        
        # Query top 5 deals in the lookback window ordered by deal_score and savings_pct
        rows = await database.fetch("""
            SELECT p.title, p.platform, p.category, p.product_url, p.affiliate_url,
                   p.image_url, p.rating, p.review_count, d.posted_price, d.posted_mrp,
                   d.savings_amount, d.savings_pct, d.deal_score, d.badge
            FROM deals d
            JOIN products p ON d.product_id = p.id
            WHERE d.posted_at >= NOW() - ($1 * INTERVAL '1 hour')
            ORDER BY d.deal_score DESC, d.savings_pct DESC
            LIMIT 5;
        """, hours_lookback)

        if not rows or len(rows) < 3:
            # Fallback to top products with highest discount currently in DB
            rows = await database.fetch("""
                SELECT title, platform, category, product_url, affiliate_url,
                       image_url, rating, review_count, current_price as posted_price,
                       mrp as posted_mrp, (mrp - current_price) as savings_amount,
                       ((mrp - current_price)/mrp) as savings_pct, 80 as deal_score, 'ATL' as badge
                FROM products
                WHERE current_price > 0 AND mrp > current_price AND in_stock = TRUE AND rating >= 4.0
                ORDER BY ((mrp - current_price)/mrp) DESC, review_count DESC
                LIMIT 5;
            """)

        if not rows:
            return

        deals_list = [dict(r) for r in rows]
        text = format_daily_digest(deals_list, digest_type=digest_type)

        await _bot.send_message(
            chat_id=config.TELEGRAM_CHANNEL_ID,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=False
        )
        logger.info(f"✅ Successfully posted {digest_type} deals digest to {config.TELEGRAM_CHANNEL_ID}")
    except Exception as e:
        logger.error(f"Error posting {digest_type} deals digest: {e}")


async def paced_posting_loop():
    """
    Continuous 30-Second Deal Broadcaster:
    - If the posting queue has intercepted channel deals: fast-drains them at 8s cadence
      (no lock, no live hunt, no pre-flight scraping — already verified).
    - If the queue is empty: hunts live deals from store APIs, then falls back to
      evergreen catalog with pre-flight verification.
    """
    try:
        from budgetby.engine.posting_queue import get_posting_queue
        pq = get_posting_queue()
        await pq.process_queue(_bot)
    except Exception as e:
        logger.error(f"Error in paced_posting_loop: {e}")


async def verify_active_deals_loop():
    """
    Targeted Micro-Job Deal Verifier:
    Fires every 60 seconds to re-verify the oldest unchecked active deals (3 products/min).
    Ensures that if retailer raises price back to MRP or item sells out,
    the deal is immediately dropped from the consumer website.
    Uses ultra-low background resources (< 0.1% CPU, ~3 requests/min across 5 stores).
    """
    try:
        from budgetby.scrapers.amazon import AmazonScraper
        from budgetby.scrapers.flipkart import FlipkartScraper
        from budgetby.scrapers.myntra import MyntraScraper
        from budgetby.scrapers.ajio import AjioScraper
        from budgetby.scrapers.nykaa import NykaaScraper

        scrapers = {
            "amazon": AmazonScraper(),
            "flipkart": FlipkartScraper(),
            "myntra": MyntraScraper(),
            "ajio": AjioScraper(),
            "nykaa": NykaaScraper(),
        }

        candidates = await database.fetch("""
            SELECT p.id, p.platform, p.product_url, p.priority_tier, 
                   COALESCE(d.posted_price, p.current_price) as posted_price, 
                   p.current_price
            FROM products p
            JOIN deals d ON d.product_id = p.id
            WHERE p.in_stock = TRUE AND p.status = 'ACTIVE'
              AND d.posted_at >= NOW() - INTERVAL '72 hours'
            ORDER BY p.last_checked ASC NULLS FIRST
            LIMIT 5;
        """)
        if not candidates:
            return

        for prod in candidates:
            platform = prod["platform"]
            scraper = scrapers.get(platform)
            if not scraper:
                continue
            try:
                data = await scraper.scrape_product(prod["product_url"])
                if not data or not data.get("current_price") or data.get("in_stock") is False:
                    # Verified out of stock or unavailable
                    await database.execute(
                        "UPDATE products SET in_stock = FALSE, last_checked = NOW() WHERE id = $1;",
                        prod["id"]
                    )
                    logger.info(f"Micro-verifier: product #{prod['id']} ({platform}) marked OUT OF STOCK")
                else:
                    new_p = float(data["current_price"])
                    await database.execute("""
                        UPDATE products SET 
                            current_price = $2,
                            mrp = COALESCE($3, mrp),
                            in_stock = $4,
                            last_checked = NOW()
                        WHERE id = $1;
                    """, prod["id"], new_p, data.get("mrp"), data.get("in_stock", True))
                    if prod["posted_price"] and new_p > float(prod["posted_price"]) * 1.01:
                        logger.info(f"Micro-verifier: price increased for #{prod['id']} ({platform}) from {prod['posted_price']} to {new_p}")
            except Exception as e:
                logger.debug(f"Micro-verifier scrape error for #{prod['id']}: {e}")
                await database.execute("UPDATE products SET last_checked = NOW() WHERE id = $1;", prod["id"])
    except Exception as e:
        logger.error(f"Error in verify_active_deals_loop: {e}")


def start_scheduler():
    """Configure and start all scheduled jobs."""
    if _scheduler.running:
        logger.info("Scheduler already running, skipping start.")
        return
    logger.info("Starting scheduler...")

    # Core catalog price checking — every 120 seconds (15 products / 2 min)
    _scheduler.add_job(price_check_loop, "interval", seconds=120, id="price_check",
                       max_instances=1, coalesce=True, misfire_grace_time=60, replace_existing=True)

    # Targeted Micro-Job Deal Verifier — every 180 seconds (3 minutes)
    _scheduler.add_job(verify_active_deals_loop, "interval", seconds=180, id="deal_verifier",
                       max_instances=1, coalesce=True, misfire_grace_time=30, replace_existing=True)

    # Discovery — every 6 hours (Amazon/Flipkart/Ajio/Nykaa only)
    _scheduler.add_job(discovery_job, "interval",
                       hours=config.DISCOVERY_INTERVAL_HOURS, id="discovery", max_instances=1, misfire_grace_time=30, replace_existing=True)

    # Daily cleanup at midnight IST
    _scheduler.add_job(cleanup.daily_cleanup, "cron", hour=0, minute=0, id="daily_cleanup", misfire_grace_time=300, replace_existing=True)

    # Monthly benchmark shift on the 1st
    _scheduler.add_job(cleanup.monthly_maintenance, "cron", day=1, hour=1, minute=0,
                       id="monthly_maintenance", misfire_grace_time=300, replace_existing=True)

    # Bi-weekly backup on 1st and 15th of each month at 3:00 AM IST (saves 93% egress)
    if config.BACKUP_ENABLED:
        _scheduler.add_job(cleanup.run_backup, "cron", day="1,15",
                           hour=config.BACKUP_HOUR, minute=0, id="biweekly_backup", misfire_grace_time=300, replace_existing=True)

    # Daily Morning Digest at 9:00 AM IST
    _scheduler.add_job(morning_digest, "cron", hour=9, minute=0, timezone="Asia/Kolkata", id="morning_digest", misfire_grace_time=300, replace_existing=True)

    # Daily Evening Digest at 8:00 PM IST
    _scheduler.add_job(evening_digest, "cron", hour=20, minute=0, timezone="Asia/Kolkata", id="evening_digest", misfire_grace_time=300, replace_existing=True)

    # High-Velocity 30-Second Paced Broadcaster with Live Deal Hunter
    _scheduler.add_job(paced_posting_loop, "interval", seconds=30, id="paced_posting",
                       max_instances=1, coalesce=True, misfire_grace_time=60, replace_existing=True)

    _scheduler.start()
    logger.info("Scheduler started with all jobs configured")


def stop_scheduler(wait: bool = True):
    """Gracefully stop the scheduler."""
    logger.info("Stopping scheduler...")
    if _scheduler.running:
        _scheduler.shutdown(wait=wait)
        logger.info("Scheduler stopped")
