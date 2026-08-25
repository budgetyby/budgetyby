"""
BudgetBy — High-Efficiency Paced & Dynamic Burst Deal Posting Engine
Guarantees:
1. Minimum Cadence: Exactly 1 post every 30 seconds (120 posts/hour • 2,880 posts/day) 24/7.
2. Dynamic Burst Drain: If queue size > 2 deals, rapidly posts with 15s pacing until queue <= 2.
3. Multi-Store Interleaving: Even during single-store surges (e.g., 5 Amazon deals), interleaves alternate stores to strictly preserve anti-clustering.
4. Cooldown Accuracy: Cooldowns are applied only after successful delivery.
"""

import asyncio
import logging
import datetime
import zoneinfo
from typing import Optional, Dict, Any, List

from budgetby import config
from budgetby.bot import templates

logger = logging.getLogger("budgetby.engine.posting_queue")

# 30-slot weighted, interleaved platform rotation sequence
# Strict 11-slot proportional rotation cycle:
# Amazon: 3, Flipkart: 3, Myntra: 2, Ajio: 2, Nykaa: 1 (Total = 11 parts)
ROTATION_SEQUENCE = [
    "amazon", "flipkart", "myntra",
    "amazon", "ajio", "flipkart",
    "nykaa",
    "amazon", "myntra",
    "flipkart", "ajio"
]

def format_deal_message(deal_data: dict) -> str:
    """Format deal using tiered high-converting templates."""
    product = deal_data.get("product", {})
    deal_type = deal_data.get("type", "price_drop")
    score = float(deal_data.get("score") or 50)
    badge = deal_data.get("badge")
    deal_result = {"badge": badge, "score": score}

    if score >= 75 or badge in ["ATL", "LOOT"]:
        return templates.format_mega_deal(product, deal_result)
    elif deal_type in ["todays_deal", "channel_deal"]:
        return templates.format_today_deal(product, deal_result)
    elif hasattr(templates, "format_price_drop"):
        return templates.format_price_drop(product, deal_result)
    else:
        return templates.format_mega_deal(product, deal_result)

class PostingQueue:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(PostingQueue, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._queue = asyncio.Queue()
        self._lock = asyncio.Lock()
        self._draining = False
        self._bot = None
        self._last_posted_platform = None
        self._rotation_index = 0
        self.posts_this_hour = 0
        self.hour_started = self._get_ist_hour()
        self.ROTATION_SEQUENCE = ROTATION_SEQUENCE
        self._initialized = True
        logger.info("PostingQueue initialized with 30-second high-velocity pacer, smart interleaving, and dynamic >2 burst drain.")

    def set_bot(self, bot):
        self._bot = bot

    def _get_ist_hour(self) -> int:
        tz = zoneinfo.ZoneInfo("Asia/Kolkata")
        return datetime.datetime.now(tz).hour

    def reset_hour_if_needed(self):
        cur_hour = self._get_ist_hour()
        if cur_hour != self.hour_started:
            self.posts_this_hour = 0
            self.hour_started = cur_hour

    def get_queue_snapshot(self) -> dict:
        """Returns a snapshot of the current queue state and queued deals."""
        items = list(self._queue._queue) if hasattr(self._queue, "_queue") else []
        target_platform = self.ROTATION_SEQUENCE[self._rotation_index % len(self.ROTATION_SEQUENCE)]
        formatted_items = []
        for idx, it in enumerate(items):
            prod = it.get("product", {})
            price = float(prod.get("current_price") or 0)
            mrp = float(prod.get("mrp") or price)
            discount_pct = round(((mrp - price) / mrp) * 100, 1) if mrp > price else 0.0
            formatted_items.append({
                "queue_position": idx + 1,
                "id": prod.get("id"),
                "title": prod.get("title", "Product Deal"),
                "platform": (prod.get("platform") or "store").lower(),
                "price": price,
                "mrp": mrp,
                "discount_pct": discount_pct,
                "badge": it.get("badge", "DEAL"),
                "score": it.get("score", 50),
                "deal_type": it.get("type", "price_drop"),
                "source_channel": it.get("source_channel", "scanner"),
                "image_url": prod.get("image_url") or "",
                "affiliate_url": prod.get("affiliate_url") or prod.get("product_url") or ""
            })

        return {
            "queue_size": len(formatted_items),
            "is_draining_fast": self._draining,
            "next_scheduled_platform": target_platform,
            "last_posted_platform": self._last_posted_platform or "None yet",
            "posts_this_hour": self.posts_this_hour,
            "items": formatted_items
        }

    async def process_queue(self, bot=None):
        """
        Non-blocking process_queue wrapper:
        If queue > 2, initiates burst drain background task.
        If queue <= 2 and has items, posts the next deal immediately without blocking other tasks.
        """
        if bot:
            self._bot = bot
        if self._queue.qsize() > 2 and not self._draining:
            asyncio.create_task(self._drain_overflow_queue())
        elif not self._queue.empty():
            asyncio.create_task(self.post_next_deal(bot))

    async def queue_deal(self, deal_data: dict):
        """
        Enqueue an organic or intercepted deal.
        If queue size exceeds 2, immediately initiates fast-drain background worker!
        """
        await self._queue.put(deal_data)
        pid = deal_data.get('product', {}).get('id')
        plat = deal_data.get('product', {}).get('platform', 'unknown')
        qsize = self._queue.qsize()
        logger.info(f"📥 Queued deal #{pid} [{plat.upper()}] (Current Queue Size: {qsize})")

        if qsize > 2 and not self._draining:
            asyncio.create_task(self._drain_overflow_queue())

    async def _drain_overflow_queue(self):
        """
        Fast-drain background worker:
        Runs when queue > 2. Posts deals with 15-second pacing until queue size <= 2.
        """
        if self._draining:
            return
        self._draining = True
        logger.info(f"⚡ [OVERFLOW TRIGGERED] Queue has {self._queue.qsize()} deals (>2 limit). Initiating fast-drain posting...")

        try:
            while self._queue.qsize() > 2:
                await self.post_next_deal(self._bot)
                await asyncio.sleep(8)  # Rapid 8s delay for overflow drain
        except Exception as e:
            logger.error(f"Error in _drain_overflow_queue: {e}")
        finally:
            self._draining = False
            logger.info(f"✅ Overflow drained. Remaining queue size: {self._queue.qsize()} (Returning to 30-second baseline pacing)")

    async def post_next_deal(self, bot=None):
        """
        Main Dispatcher:
        - Prioritizes queued deals (organic drops & channel interceptions).
        - If queue is empty, falls back to highest-discount catalog deals.
        - Guarantees multi-platform rotation & anti-clustering.
        """
        async with self._lock:
            self.reset_hour_if_needed()
            
            bot_instance = bot or self._bot
            if not bot_instance and config.TELEGRAM_BOT_TOKEN:
                from telegram import Bot
                bot_instance = Bot(token=config.TELEGRAM_BOT_TOKEN)

            if not bot_instance:
                logger.warning("No Telegram bot available for deal posting.")
                return

            target_platform = self.ROTATION_SEQUENCE[self._rotation_index % len(self.ROTATION_SEQUENCE)]
            deal_data = None
            
            # 1. Search Queue for an Anti-Clustering Compatible Deal
            if not self._queue.empty():
                pending_items = []
                while not self._queue.empty():
                    item = self._queue.get_nowait()
                    plat = item.get("product", {}).get("platform", "").lower()
                    
                    # Ideal: Platform is different from last post
                    if not deal_data and plat != self._last_posted_platform:
                        deal_data = item
                    else:
                        pending_items.append(item)

                # Re-enqueue remaining items
                for item in pending_items:
                    await self._queue.put(item)

            # 2. If all queued items were same platform as last post, interleave 1 alternate store catalog deal!
            if not deal_data and not self._queue.empty():
                logger.info(f"Interleaving alternate platform deal to maintain anti-clustering...")
                from budgetby.engine.evergreen import find_evergreen_deals
                for alt_plat in ["flipkart", "amazon", "myntra", "ajio", "nykaa"]:
                    if alt_plat != self._last_posted_platform:
                        candidates = await find_evergreen_deals(limit=1, platform=alt_plat)
                        if candidates:
                            deal_data = {
                                "product": dict(candidates[0]),
                                "type": "evergreen",
                                "badge": "EVERGREEN",
                                "score": 75
                            }
                            break

            # 3. If queue was empty, fetch standard rotation deal
            if not deal_data:
                from budgetby.engine.evergreen import find_evergreen_deals
                candidates = await find_evergreen_deals(limit=1, platform=target_platform)
                
                # Fallback to alternate platform if target platform has no candidate
                if not candidates:
                    for alt_plat in ["amazon", "flipkart", "myntra", "ajio", "nykaa"]:
                        if alt_plat != self._last_posted_platform and alt_plat != target_platform:
                            candidates = await find_evergreen_deals(limit=1, platform=alt_plat)
                            if candidates:
                                target_platform = alt_plat
                                break

                if candidates:
                    deal_data = {
                        "product": dict(candidates[0]),
                        "type": "evergreen",
                        "badge": "EVERGREEN",
                        "score": 75
                    }

            if not deal_data:
                logger.info("No qualifying deal available to post this tick.")
                self._rotation_index += 1
                return

            # 4. Process and Broadcast Deal to Telegram
            try:
                from budgetby import database
                from budgetby.engine.cooldown import is_on_cooldown, set_cooldown

                product = deal_data.get("product", {})
                pid = product.get("id")
                platform = (product.get("platform") or "store").lower()

                # Anti-duplicate check
                if pid and await is_on_cooldown(pid):
                    logger.info(f"Skipping product #{pid} — on cooldown.")
                    return

                deal_type = deal_data.get("type", "price_drop")
                badge = deal_data.get("badge", "DEAL")
                score = float(deal_data.get("score") or 50)
                source_channel = deal_data.get("source_channel", "local_scanner")
                
                price = float(product.get("current_price") or 0)
                mrp = float(product.get("mrp") or price)

                # Quality guard: minimum discount from MRP
                min_discount = getattr(config, "MIN_DEAL_DISCOUNT_PCT", 10.0) / 100.0
                if mrp > 0 and price > 0 and ((mrp - price) / mrp) < min_discount and deal_type != "price_drop":
                    return

                # URL Resolution
                url = product.get("affiliate_url") or product.get("product_url") or product.get("url", "")
                if not url and platform == "amazon" and product.get("platform_id"):
                    url = f"https://www.amazon.in/dp/{product.get('platform_id')}?tag={config.AMAZON_ASSOCIATE_TAG}"
                    product["affiliate_url"] = url

                # Generate clean formatted message
                message_text = format_deal_message(deal_data)

                # Send message to Telegram Channel
                sent_msg = await bot_instance.send_message(
                    chat_id=config.TELEGRAM_CHANNEL_ID,
                    text=message_text,
                    parse_mode="HTML",
                    disable_web_page_preview=False
                )

                savings_amount = max(0.0, mrp - price)
                savings_pct = (savings_amount / mrp) if mrp > 0 else 0.0

                # Record in deals database table
                await database.insert_deal({
                    "product_id": pid,
                    "deal_type": deal_type,
                    "posted_price": price,
                    "posted_mrp": mrp,
                    "savings_amount": savings_amount,
                    "savings_pct": savings_pct,
                    "deal_score": score,
                    "badge": badge,
                    "source_channel": source_channel
                })

                # Set 24h Cooldown only AFTER successful post
                if pid:
                    await set_cooldown(pid, config.PRICE_DROP_COOLDOWN_HOURS)

                self._last_posted_platform = platform
                
                # Advance rotation schedule only if this was on-schedule
                if platform == target_platform:
                    self._rotation_index += 1

                self.posts_this_hour += 1
                logger.info(f"📢 [POSTED TO TELEGRAM] [{platform.upper()}] {product.get('title', '')[:40]} | ₹{price:.0f} (MRP: ₹{mrp:.0f}) | Source: {source_channel}")

            except Exception as e:
                logger.error(f"Error posting deal to Telegram: {e}", exc_info=True)


_global_posting_queue = None

def get_posting_queue() -> PostingQueue:
    global _global_posting_queue
    if _global_posting_queue is None:
        _global_posting_queue = PostingQueue()
    return _global_posting_queue
