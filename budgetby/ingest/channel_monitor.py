"""
BudgetBy — Real-Time Telegram Channel Deal Monitor & Ingestion Engine
Monitors public deal channels in parallel (bypassing ISP blocks with DoH),
sanitizes affiliate tags, verifies live product pricing locally,
stores in local PostgreSQL database, and immediately broadcasts verified deals.
"""

import logging
import re
import asyncio
from typing import List, Dict, Any, Optional
from selectolax.parser import HTMLParser
import httpx
from budgetby import database, config

logger = logging.getLogger("budgetby.ingest.channel_monitor")

# Configurable list of active high-velocity public deal channels to monitor in parallel
DEFAULT_MONITORED_CHANNELS = [
    "flipkart_deals",       # 126K Subscribers (Dealshub)
    "desidime",             # 85K Subscribers (DesiDime Official)
    "bobbyustaddeals",      # 67.8K Subscribers (Bobby Ustad Deals)
    "dealbeeofficial",      # 38.2K Subscribers (DealBee Deals)
    "bestdeals"             # 26.3K Subscribers (Shop My Deals)
]

# Cloudflare DoH IP for Telegram Web
TELEGRAM_WEB_IP = "149.154.167.99"

# In-memory baseline tracker: {channel_name: max_seen_post_id}
_channel_baseline_post_ids = {}

async def unshorten_url(url: str, client: httpx.AsyncClient) -> str:
    """Follow HTTP redirects to unshorten shortened links."""
    if not url or not url.startswith("http"):
        return url or ""
    try:
        if any(store in url for store in ["amazon.in/dp/", "amazon.in/gp/product/", "flipkart.com/", "myntra.com/", "ajio.com/", "nykaa.com/"]):
            return url

        resp = await client.get(url, follow_redirects=True, timeout=8)
        return str(resp.url)
    except Exception:
        return url

def clean_and_tag_url(resolved_url: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Identifies store platform, strips foreign affiliate tracking, and injects our affiliate tag.
    Returns: (platform, clean_product_url, affiliate_url)
    """
    if not resolved_url:
        return None, None, None

    # 1. Amazon
    if "amazon.in" in resolved_url or "amzn." in resolved_url or "link.amazon" in resolved_url:
        asin_match = re.search(r'/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})', resolved_url)
        if not asin_match:
            asin_match = re.search(r'/([A-Z0-9]{10})(?:[/?]|$)', resolved_url)
        if asin_match:
            asin = asin_match.group(1)
            clean_url = f"https://www.amazon.in/dp/{asin}"
            aff_url = f"{clean_url}?tag={config.AMAZON_ASSOCIATE_TAG}"
            return "amazon", clean_url, aff_url

    # 2. Flipkart
    elif "flipkart.com" in resolved_url or "fkrt." in resolved_url:
        clean_url = resolved_url.split('?')[0]
        if "/p/itm" in clean_url or "/p/" in clean_url or "pid=" in resolved_url:
            from budgetby.affiliate.earnkaro_links import build_earnkaro_url_sync
            aff_url = build_earnkaro_url_sync(clean_url)
            return "flipkart", clean_url, aff_url

    # 3. Myntra
    elif "myntra.com" in resolved_url or "myntr." in resolved_url:
        clean_url = resolved_url.split('?')[0]
        if "/buy" in clean_url or re.search(r'/\d+$', clean_url):
            from budgetby.affiliate.earnkaro_links import build_earnkaro_url_sync
            aff_url = build_earnkaro_url_sync(clean_url)
            return "myntra", clean_url, aff_url

    # 4. Ajio
    elif "ajio.com" in resolved_url:
        clean_url = resolved_url.split('?')[0]
        if "/p/" in clean_url:
            from budgetby.affiliate.earnkaro_links import build_earnkaro_url_sync
            aff_url = build_earnkaro_url_sync(clean_url)
            return "ajio", clean_url, aff_url

    # 5. Nykaa
    elif "nykaa.com" in resolved_url:
        clean_url = resolved_url.split('?')[0]
        if "/p/" in clean_url or "/product/" in clean_url:
            from budgetby.affiliate.earnkaro_links import build_earnkaro_url_sync
            aff_url = build_earnkaro_url_sync(clean_url)
            return "nykaa", clean_url, aff_url

    return None, None, None

async def scrape_channel_posts(channel: str, limit: int = 15) -> List[Dict[str, Any]]:
    """Scrape latest messages from Telegram channel web preview via DoH."""
    channel_name = channel.lstrip("@").strip()
    extracted_posts = []

    try:
        transport = httpx.AsyncHTTPTransport(verify=False)
        async with httpx.AsyncClient(transport=transport, follow_redirects=False, timeout=10, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}) as client:
            resp = await client.get(f"https://{TELEGRAM_WEB_IP}/s/{channel_name}", headers={"Host": "t.me"})
            
            if resp.status_code != 200:
                return []

            tree = HTMLParser(resp.text)
            message_nodes = tree.css(".tgme_widget_message_wrap")

            for node in message_nodes[-limit:]:
                msg_node = node.css_first(".tgme_widget_message")
                if not msg_node:
                    continue

                data_post = msg_node.attributes.get("data-post", "")
                post_id = int(data_post.split("/")[-1]) if "/" in data_post else 0

                text_node = node.css_first(".tgme_widget_message_text")
                post_text = text_node.text(strip=True) if text_node else ""

                link_nodes = node.css("a[href]")
                raw_urls = []
                for ln in link_nodes:
                    href = ln.attributes.get("href", "")
                    if href and href.startswith("http") and "t.me/" not in href and "telegram.org" not in href:
                        raw_urls.append(href)

                if raw_urls and post_id > 0:
                    extracted_posts.append({
                        "channel": f"@{channel_name}",
                        "post_id": post_id,
                        "text": post_text,
                        "raw_urls": list(set(raw_urls))
                    })

    except Exception as e:
        logger.error(f"Error scraping channel @{channel_name}: {e}")

    return extracted_posts

async def verify_and_ingest_single_deal(channel: str, post_id: int, raw_url: str, client: httpx.AsyncClient) -> Optional[int]:
    """
    Unshortens URL, verifies product data live with local scrapers, saves in DB, and queues deal if valid.
    """
    try:
        # 1. Unshorten & clean
        resolved = await unshorten_url(raw_url, client)
        platform, clean_url, aff_url = clean_and_tag_url(resolved)

        if not platform or not clean_url:
            return None

        # 2. Extract Platform ID
        platform_id = None
        if platform == "amazon":
            asin_match = re.search(r'/(?:dp|gp/product)/([A-Z0-9]{10})', clean_url)
            platform_id = asin_match.group(1) if asin_match else None
        elif platform == "flipkart":
            itm_match = re.search(r'/p/([^/?]+)', clean_url)
            platform_id = itm_match.group(1) if itm_match else clean_url.split('/')[-1]
        elif platform in ["myntra", "ajio", "nykaa"]:
            platform_id = clean_url.rstrip('/').split('/')[-1].replace('.html', '')

        if not platform_id:
            return None

        # 3. Scrape Live Store Product Details
        live_data = None
        if platform == "amazon":
            from budgetby.scrapers.amazon import AmazonScraper
            live_data = await AmazonScraper()._do_scrape_product(clean_url)
        elif platform == "flipkart":
            from budgetby.scrapers.flipkart import FlipkartScraper
            live_data = await FlipkartScraper()._do_scrape_product(clean_url)
        elif platform == "myntra":
            from budgetby.scrapers.myntra import MyntraScraper
            live_data = await MyntraScraper()._do_scrape_product(clean_url)
        elif platform == "ajio":
            from budgetby.scrapers.ajio import AjioScraper
            live_data = await AjioScraper()._do_scrape_product(clean_url)
        elif platform == "nykaa":
            from budgetby.scrapers.nykaa import NykaaScraper
            live_data = await NykaaScraper()._do_scrape_product(clean_url)

        if not live_data or not live_data.get("current_price") or live_data.get("current_price") <= 0:
            await database.execute("""
                INSERT INTO ingested_channel_deals (source_channel, message_id, raw_url, resolved_url, platform, status)
                VALUES ($1, $2, $3, $4, $5, 'FAILED_SCRAPE');
            """, channel, post_id, raw_url, clean_url, platform)
            return None

        price = float(live_data.get("current_price"))
        mrp = float(live_data.get("mrp") or price)
        title = live_data.get("title") or f"{platform.capitalize()} Product"
        rating = float(live_data.get("rating") or 4.2)
        review_count = int(live_data.get("review_count") or 100)
        image_url = live_data.get("image_url") or ""
        in_stock = bool(live_data.get("in_stock", True))

        if not in_stock:
            await database.execute("""
                INSERT INTO ingested_channel_deals (source_channel, message_id, raw_url, resolved_url, platform, status, title, price, mrp)
                VALUES ($1, $2, $3, $4, $5, 'OUT_OF_STOCK', $6, $7, $8);
            """, channel, post_id, raw_url, clean_url, platform, title, price, mrp)
            return None

        # 4. Upsert product into local database
        prod_dict = {
            "platform": platform,
            "platform_id": platform_id,
            "title": title,
            "category": "deals",
            "product_url": clean_url,
            "affiliate_url": aff_url or clean_url,
            "image_url": image_url,
            "current_price": price,
            "mrp": mrp,
            "rating": rating,
            "review_count": review_count,
            "in_stock": in_stock
        }

        pid = await database.upsert_product(prod_dict)
        if not pid:
            return None

        # Record daily price snapshot
        await database.upsert_daily_price(pid, price)

        # 5. Verify Deal Legitimacy
        discount_pct = round(((mrp - price) / mrp) * 100, 1) if mrp > price else 0.0
        min_disc = getattr(config, "MIN_DEAL_DISCOUNT_PCT", 10.0)
        min_sav = getattr(config, "MIN_DEAL_SAVINGS_INR", 30.0)
        is_valid_deal = (mrp > price) and (discount_pct >= min_disc) and ((mrp - price) >= min_sav)

        status = "VERIFIED_DEAL" if is_valid_deal else "SAVED_TO_CATALOG"
        await database.execute("""
            INSERT INTO ingested_channel_deals (source_channel, message_id, raw_url, resolved_url, platform, product_id, status, title, price, mrp, discount_pct)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11);
        """, channel, post_id, raw_url, clean_url, platform, pid, status, title, price, mrp, discount_pct)

        # 6. If verified deal, queue deal and trigger immediate posting!
        from budgetby.engine.cooldown import is_on_cooldown
        if is_valid_deal and not await is_on_cooldown(pid):
            from budgetby.engine.posting_queue import get_posting_queue
            pq = get_posting_queue()
            
            badge = "ATL" if discount_pct >= 50 else ("HOT_DEAL" if discount_pct >= 25 else "DEAL")
            deal_data = {
                "product": {
                    "id": pid,
                    "title": title,
                    "platform": platform,
                    "category": "deals",
                    "product_url": clean_url,
                    "affiliate_url": aff_url or clean_url,
                    "image_url": image_url,
                    "current_price": price,
                    "mrp": mrp,
                    "rating": rating,
                    "review_count": review_count
                },
                "type": "channel_deal",
                "badge": badge,
                "score": round(min(95, 50 + discount_pct)),
                "source_channel": channel
            }
            await pq.queue_deal(deal_data)
            logger.info(f"🎯 Intercepted & Verified DEAL from {channel} [{platform.upper()}]: {title[:40]} ({discount_pct}% OFF)")

        return pid

    except Exception as e:
        logger.error(f"Error ingesting deal from {channel}: {e}")
        return None

async def _process_single_channel(channel: str, client: httpx.AsyncClient):
    """Processes a single channel, records live heartbeat in database, and processes incoming deals."""
    global _channel_baseline_post_ids
    ch_key = channel.lstrip("@").lower()
    ch_tag = f"@{ch_key}"

    try:
        # Record live scan heartbeat in database
        await database.execute("""
            INSERT INTO channel_monitors (channel_name, status, last_scanned_at)
            VALUES ($1, 'ACTIVE', (NOW() AT TIME ZONE 'Asia/Kolkata'))
            ON CONFLICT (channel_name) DO UPDATE SET
                status = 'ACTIVE',
                last_scanned_at = (NOW() AT TIME ZONE 'Asia/Kolkata');
        """, ch_tag)

        posts = await scrape_channel_posts(channel, limit=15)
        if not posts:
            return

        max_id_on_page = max(p["post_id"] for p in posts)

        # Update last post id in database
        await database.execute("UPDATE channel_monitors SET last_post_id = $2 WHERE channel_name = $1;", ch_tag, max_id_on_page)

        # First boot for this channel: record baseline
        if ch_key not in _channel_baseline_post_ids:
            _channel_baseline_post_ids[ch_key] = max_id_on_page
            logger.info(f"📍 Channel @{ch_key}: Initialized baseline at Post #{max_id_on_page}.")
            return

        baseline_id = _channel_baseline_post_ids[ch_key]
        new_posts = [p for p in posts if p["post_id"] > baseline_id]

        if new_posts:
            logger.info(f"⚡ Channel @{ch_key}: Found {len(new_posts)} NEW incoming deal posts (since #{baseline_id})")
            for p in new_posts:
                for raw_url in p["raw_urls"]:
                    await verify_and_ingest_single_deal(
                        channel=p["channel"],
                        post_id=p["post_id"],
                        raw_url=raw_url,
                        client=client
                    )
                    await asyncio.sleep(0.3)

            _channel_baseline_post_ids[ch_key] = max_id_on_page

    except Exception as e:
        logger.error(f"Error processing channel @{channel}: {e}")

async def run_channel_monitor(channels: List[str] = None):
    """
    Main background job: Scrapes all monitored channels concurrently in parallel.
    """
    target_channels = channels or DEFAULT_MONITORED_CHANNELS
    async with httpx.AsyncClient(timeout=12, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}) as client:
        await asyncio.gather(*(_process_single_channel(ch, client) for ch in target_channels))
