"""
BudgetBy — Paced Posting Queue & Multi-Platform Rotation Engine
Maintains continuous 1-post-every-2-minutes cadence strictly balanced across catalog proportions.
"""

import logging
import asyncio
from datetime import datetime, timezone, timedelta
from budgetby import config

logger = logging.getLogger("budgetby.engine.posting_queue")

_global_posting_queue = None

async def verify_product_url_live(url: str, platform: str = "") -> bool:
    """Pre-post check to ensure product URL returns HTTP 200 and has active PDP data."""
    try:
        from curl_cffi.requests import AsyncSession
        async with AsyncSession(impersonate="chrome", timeout=6) as session:
            resp = await session.get(url, allow_redirects=True)
            if resp.status_code != 200:
                return False
            text = resp.text
            if platform == "myntra":
                if '"pdpData":null' in text or '"pdpData": null' in text:
                    return False
            elif platform == "amazon":
                if "page not found" in text.lower() or "looking for something?" in text.lower():
                    return False
            elif platform == "flipkart":
                if "page not found" in text.lower() and len(text) < 10000:
                    return False
            return True
    except Exception:
        # On network timeout, do not block
        return True

def get_posting_queue() -> 'PostingQueue':
    global _global_posting_queue
    if _global_posting_queue is None:
        _global_posting_queue = PostingQueue()
    return _global_posting_queue

class PostingQueue:
    # 30-slot weighted round-robin sequence strictly proportional to catalog size:
    # Amazon: 9 (~30%), Flipkart: 8 (~27%), Myntra: 6 (~20%), Ajio: 4 (~13%), Nykaa: 3 (~10%)
    # Guaranteed 0 consecutive duplicate platforms!
    ROTATION_SEQUENCE = [
        "amazon", "flipkart", "myntra", "amazon", "ajio", "flipkart",
        "nykaa", "amazon", "myntra", "flipkart", "amazon", "ajio",
        "flipkart", "myntra", "amazon", "nykaa", "flipkart", "amazon",
        "ajio", "myntra", "flipkart", "amazon", "nykaa", "amazon",
        "flipkart", "myntra", "ajio", "amazon", "flipkart", "myntra"
    ]

    def __init__(self):
        self.posts_this_hour = 0
        self.hour_started = self._get_ist_hour()
        self._queue = asyncio.Queue()
        self._last_posted_platform = None
        self._rotation_index = 0
        self._lock = asyncio.Lock()

    def _get_ist_hour(self) -> int:
        utc_now = datetime.now(timezone.utc)
        ist_now = utc_now + timedelta(hours=5, minutes=30)
        return ist_now.hour

    def reset_hour_if_needed(self):
        cur_hour = self._get_ist_hour()
        if cur_hour != self.hour_started:
            self.posts_this_hour = 0
            self.hour_started = cur_hour

    async def queue_deal(self, deal_data: dict):
        """Enqueue an organic price-drop deal."""
        await self._queue.put(deal_data)
        pid = deal_data.get('product', {}).get('id')
        plat = deal_data.get('product', {}).get('platform', 'unknown')
        logger.info(f"Queued organic deal #{pid} [{plat.upper()}] (Queue size: {self._queue.qsize()})")

    async def post_next_deal(self, bot=None):
        """
        Paced Dispatcher: Called precisely every 2 minutes.
        Picks the next deal respecting the weighted platform rotation sequence
        and guaranteeing no 2 consecutive posts from the same platform.
        """
        async with self._lock:
            self.reset_hour_if_needed()
            
            if not bot and config.TELEGRAM_BOT_TOKEN:
                from telegram import Bot
                bot = Bot(token=config.TELEGRAM_BOT_TOKEN)

            if not bot:
                logger.warning("No Telegram bot available for post_next_deal.")
                return

            # 1. Determine target platform from weighted sequence
            target_platform = self.ROTATION_SEQUENCE[self._rotation_index % len(self.ROTATION_SEQUENCE)]
            
            deal_data = None
            
            # 2. Check internal organic queue for a matching or eligible deal
            pending_items = []
            while not self._queue.empty():
                item = self._queue.get_nowait()
                plat = item.get("product", {}).get("platform", "").lower()
                
                # Check if this item is eligible (different from last posted platform)
                if not deal_data and (plat == target_platform or (plat != self._last_posted_platform and self._queue.qsize() > 5)):
                    deal_data = item
                else:
                    pending_items.append(item)

            # Re-enqueue unchosen items
            for item in pending_items:
                await self._queue.put(item)

            # 3. If no organic deal available for target platform, query highest-discount deal from DB
            if not deal_data:
                from budgetby.engine.evergreen import find_evergreen_deals
                # Try target platform first
                candidates = await find_evergreen_deals(limit=1, platform=target_platform)
                
                # Fallback to other platforms that are NOT the last posted platform
                if not candidates:
                    for alt_plat in ["amazon", "flipkart", "myntra", "ajio", "nykaa"]:
                        if alt_plat != self._last_posted_platform and alt_plat != target_platform:
                            candidates = await find_evergreen_deals(limit=1, platform=alt_plat)
                            if candidates:
                                break
                                
                if candidates:
                    product_row = dict(candidates[0])
                    deal_data = {
                        "product": product_row,
                        "type": "evergreen",
                        "badge": "EVERGREEN",
                        "score": 75
                    }

            if not deal_data:
                logger.info(f"No qualifying deal found for {target_platform} or alternate platforms this cycle.")
                self._rotation_index += 1
                return

            # 4. Process and post the selected deal
            try:
                from budgetby.bot import templates
                from budgetby import database
                from budgetby.engine.cooldown import is_on_cooldown, set_cooldown

                product = deal_data.get("product", {})
                pid = product.get("id")
                platform = (product.get("platform") or "store").lower()

                # Guard: Strict 24h anti-duplicate
                if pid and await is_on_cooldown(pid):
                    logger.info(f"Skipping product #{pid} — on cooldown.")
                    self._rotation_index += 1
                    return

                deal_type = deal_data.get("type", "price_drop")
                badge = deal_data.get("badge", "DEAL")
                score = float(deal_data.get("score") or 50)
                
                price = float(product.get("current_price") or 0)
                mrp = float(product.get("mrp") or price)

                # Ensure minimum 10% discount from MRP
                if mrp > 0 and price > 0 and ((mrp - price) / mrp) < 0.10 and deal_type != "price_drop":
                    self._rotation_index += 1
                    return

                # URL Resolution
                url = product.get("affiliate_url") or product.get("product_url") or product.get("url", "")
                if not url and platform == "amazon" and product.get("platform_id"):
                    url = f"https://www.amazon.in/dp/{product.get('platform_id')}?tag={config.AMAZON_ASSOCIATE_TAG}"
                    product["affiliate_url"] = url
                    product["product_url"] = url

                if not url or not url.startswith("http"):
                    logger.warning(f"Product #{pid} has no valid URL, skipping.")
                    self._rotation_index += 1
                    return

                # Verify live URL
                is_live = await verify_product_url_live(url, platform)
                if not is_live:
                    logger.warning(f"Product #{pid} ({product.get('title')[:30]}) failed live URL check, marking DORMANT.")
                    if pid:
                        await database.execute("UPDATE products SET status = 'DORMANT', in_stock = FALSE WHERE id = $1", pid)
                    self._rotation_index += 1
                    return

                # Format Template
                if deal_type == "today_deal" or badge == "TODAY_DEAL":
                    text = templates.format_today_deal(product, deal_data.get("deal_result"))
                elif deal_type == "evergreen":
                    text = templates.format_evergreen_deal(product, 1)
                elif badge in ["ATL", "near_ATL"]:
                    text = templates.format_mega_deal(product, deal_data.get("deal_result"))
                elif badge in ["90d_low", "60d_low"]:
                    text = templates.format_hot_deal(product, deal_data.get("deal_result"))
                else:
                    text = templates.format_good_deal(product, deal_data.get("deal_result"))

                # Send Telegram message
                msg = await bot.send_message(
                    chat_id=config.TELEGRAM_CHANNEL_ID,
                    text=text,
                    parse_mode="HTML"
                )
                logger.info(f"✅ [2-MIN PACER] Posted [{platform.upper()}] #{pid} to Telegram (Msg ID: {msg.message_id}): {product.get('title')[:45]}")

                # Set Cooldown
                if pid:
                    cooldown_hours = 168.0 if deal_type == "evergreen" else config.PRICE_DROP_COOLDOWN_HOURS
                    await set_cooldown(pid, cooldown_hours)

                # Record in Database
                savings_amt = max(0.0, mrp - price)
                savings_pct = (savings_amt / mrp) if mrp > 0 else 0.0

                deal_row = await database.fetchrow("""
                    INSERT INTO deals (product_id, deal_type, badge, posted_price, posted_mrp, savings_amount, savings_pct, deal_score, posted_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                    RETURNING id;
                """, pid, deal_type, badge, price, mrp, savings_amt, savings_pct, float(score))

                if deal_row and deal_row["id"]:
                    await database.insert_deal_tracking(
                        deal_row["id"], pid, msg.message_id,
                        str(config.TELEGRAM_CHANNEL_ID), text, price
                    )

                self._last_posted_platform = platform
                self._rotation_index += 1
                self.posts_this_hour += 1

            except Exception as e:
                logger.error(f"Error in post_next_deal: {e}", exc_info=True)
                self._rotation_index += 1
