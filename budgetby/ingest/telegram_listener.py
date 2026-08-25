"""
BudgetBy — Real-Time Telegram MTProto Listener for Private & Joined Channels.
Listens to live incoming messages from private invite channels and forwards verified deals.
Strictly ignores all historical messages and only processes new posts from this moment onwards.
"""

import logging
import asyncio
import os
import re
from telethon import TelegramClient, events
import httpx
from budgetby import database, config
from budgetby.ingest.channel_monitor import verify_and_ingest_single_deal

logger = logging.getLogger("budgetby.ingest.telegram_listener")

# Target Private & Web Channel IDs / Links provided by user:
# 1. https://t.me/+0GTLjgGo-DQ5YjE9
# 2. https://t.me/+SHMJO014m9MxNDFl
# 3. https://web.telegram.org/a/#-1002442523223 (-1002442523223)
TARGET_CHAT_IDS = [
    -1002273009558,  # Discounts & Offers and More ✨ (+0GTLjgGo-DQ5YjE9)
    -1002442523223,  # CHIRAG DEALS (-1002442523223)
    -1001404064358,  # QUICK DEALS 2.0 (+SHMJO014m9MxNDFl)
]

# Telethon Session path in local storage
SESSION_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "telegram_user.session")

async def start_telegram_listener(api_id: int = None, api_hash: str = None):
    """
    Connects to Telegram user session and starts listening to live incoming messages.
    """
    env_api_id = os.getenv("TG_API_ID")
    env_api_hash = os.getenv("TG_API_HASH")
    
    api_id = api_id or (int(env_api_id) if env_api_id else None)
    api_hash = api_hash or env_api_hash

    if not api_id or not api_hash:
        logger.info("TG_API_ID and TG_API_HASH not set. Telethon private listener skipped (public DoH monitor active).")
        return

    logger.info("🚀 Starting Real-Time Telegram MTProto Channel Listener...")
    
    client = TelegramClient(SESSION_PATH, api_id, api_hash)
    await client.start()

    logger.info("🟢 Telethon Connected! Listening to incoming deals in real-time (history ignored)...")

    http_client = httpx.AsyncClient(timeout=10, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})

    @client.on(events.NewMessage)
    async def handler(event):
        try:
            chat = await event.get_chat()
            chat_title = getattr(chat, 'title', str(event.chat_id))
            chat_username = getattr(chat, 'username', None)
            source_tag = f"@{chat_username}" if chat_username else f"[{chat_title}]"

            text = event.raw_text or ""
            # Extract URLs
            raw_urls = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', text)

            if raw_urls:
                logger.info(f"⚡ [REAL-TIME TELEGRAM] New Deal Post from {source_tag} with {len(raw_urls)} link(s)")
                for url in raw_urls:
                    await verify_and_ingest_single_deal(
                        channel=source_tag,
                        post_id=event.id,
                        raw_url=url,
                        client=http_client
                    )

        except Exception as e:
            logger.error(f"Error processing real-time message: {e}")

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(start_telegram_listener())
