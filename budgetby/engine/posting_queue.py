"""
BudgetBy — Posting Queue
"""

import logging
import asyncio
from datetime import datetime, timezone, timedelta
from budgetby import config

logger = logging.getLogger("budgetby.engine.posting_queue")

_global_posting_queue = None

def get_posting_queue() -> 'PostingQueue':
    global _global_posting_queue
    if _global_posting_queue is None:
        _global_posting_queue = PostingQueue()
    return _global_posting_queue

class PostingQueue:
    def __init__(self):
        self.posts_this_hour = 0
        self.hour_started = self._get_ist_hour()
        self._queue = asyncio.Queue()
        self._is_processing = False

    def _get_ist_hour(self) -> int:
        utc_now = datetime.now(timezone.utc)
        ist_now = utc_now + timedelta(hours=5, minutes=30)
        return ist_now.hour

    def get_minimum_per_hour(self) -> int:
        hour = self._get_ist_hour()
        if config.DAYTIME_START_HOUR <= hour < config.DAYTIME_END_HOUR:
            return config.MIN_POSTS_PER_HOUR_DAY
        return config.MIN_POSTS_PER_HOUR_NIGHT

    def reset_hour(self):
        self.posts_this_hour = 0
        self.hour_started = self._get_ist_hour()

    async def queue_deal(self, deal_data: dict):
        await self._queue.put(deal_data)
        logger.info(f"Queued deal: {deal_data.get('product', {}).get('id')} (Queue size: {self._queue.qsize()})")

    async def process_queue(self, bot=None):
        """Processes the queue and posts deals with delays, recording each in the database."""
        if self._is_processing:
            logger.info("PostingQueue is already processing in background.")
            return

        self._is_processing = True
        try:
            if not bot and config.TELEGRAM_BOT_TOKEN:
                from telegram import Bot
                bot = Bot(token=config.TELEGRAM_BOT_TOKEN)

            if not bot:
                logger.warning("No Telegram bot available for process_queue.")
                return

            while not self._queue.empty():
                try:
                    deal_data = await self._queue.get()
                    
                    from budgetby.bot import templates
                    from budgetby import database
                    from budgetby.engine.cooldown import is_on_cooldown, set_cooldown
                    product = deal_data.get("product", {})
                    pid = product.get("id")

                    # Strict 24-Hour Anti-Duplicate Guard
                    if pid and await is_on_cooldown(pid):
                        logger.info(f"Skipping product #{pid} ({product.get('title')[:30]}...) — already posted within last 24 hours.")
                        self._queue.task_done()
                        continue

                    deal_type = deal_data.get("type", "price_drop")
                    badge = deal_data.get("badge", "DEAL")
                    score = deal_data.get("score", 50)
                    
                    price = float(product.get("current_price") or 0)
                    mrp = float(product.get("mrp") or price)
                    # Pre-post sanity check: ensure MRP is realistic and non-corrupted
                    if price > 0 and (mrp > 3.5 * price or (mrp > 100000 and price < 10000)):
                        mrp = round((price * 1.35) / 10) * 10
                        product["mrp"] = mrp

                    if deal_type == "today_deal" or badge == "TODAY_DEAL":
                        text = templates.format_today_deal(product)
                    elif deal_type == "evergreen":
                        text = templates.format_evergreen_deal(product, 1)
                    elif badge == "ATL" or badge == "near_ATL":
                        text = templates.format_mega_deal(product)
                    elif badge in ["90d_low", "60d_low"]:
                        text = templates.format_hot_deal(product)
                    else:
                        text = templates.format_good_deal(product)
                        
                    url = product.get("affiliate_url") or product.get("product_url") or product.get("url", "")
                    
                    msg = await bot.send_message(
                        chat_id=config.TELEGRAM_CHANNEL_ID,
                        text=text,
                        parse_mode="HTML"
                    )
                    logger.info(f"Successfully posted deal #{pid} to Telegram (Msg ID: {msg.message_id}): {product.get('title')[:50]}")
                    
                    # Enforce strict 24-hour cooldown immediately after post
                    if pid:
                        await set_cooldown(pid, config.PRICE_DROP_COOLDOWN_HOURS)

                    # Record deal in database
                    price = float(product.get("current_price") or 0)
                    mrp = float(product.get("mrp") or price)
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

                    self.posts_this_hour += 1
                    self._queue.task_done()
                    
                    await asyncio.sleep(config.POST_DELAY_SECONDS)
                except Exception as e:
                    logger.error(f"Error processing deal queue: {e}", exc_info=True)
        finally:
            self._is_processing = False

    async def hourly_backfill_check(self, bot):
        """Fills hourly gap with evergreen deals if minimum not met."""
        try:
            current_hour = self._get_ist_hour()
            if current_hour != self.hour_started:
                # Hour changed
                min_required = self.get_minimum_per_hour()
                shortfall = min_required - self.posts_this_hour
                
                if shortfall > 0:
                    logger.info(f"Hourly shortfall of {shortfall} posts. Backfilling.")
                    from budgetby.engine.evergreen import find_evergreen_deals
                    deals = await find_evergreen_deals(limit=shortfall)
                    for deal in deals:
                        await self.queue_deal({"product": deal, "type": "evergreen"})
                        
                    await self.process_queue(bot)
                
                self.reset_hour()
        except Exception as e:
            logger.error(f"Error in hourly backfill check: {e}")
