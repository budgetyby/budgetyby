"""
BudgetBy — Posting Queue
"""

import logging
import asyncio
from datetime import datetime, timezone, timedelta
from budgetby import config

logger = logging.getLogger("budgetby.engine.posting_queue")

class PostingQueue:
    def __init__(self):
        self.posts_this_hour = 0
        self.hour_started = self._get_ist_hour()
        self._queue = asyncio.Queue()

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
        logger.info(f"Queued deal: {deal_data.get('product', {}).get('id')}")

    async def process_queue(self, bot):
        """Processes the queue and posts deals with delays."""
        while not self._queue.empty():
            try:
                deal_data = await self._queue.get()
                
                # In real bot, format message and send via bot
                # bot.send_message(...)
                logger.info(f"Posting deal: {deal_data.get('product', {}).get('title')}")
                
                self.posts_this_hour += 1
                self._queue.task_done()
                
                await asyncio.sleep(config.POST_DELAY_SECONDS)
            except Exception as e:
                logger.error(f"Error processing deal queue: {e}")

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
