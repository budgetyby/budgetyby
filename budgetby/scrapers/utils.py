"""
BudgetBy — Scraper Utilities
"""
import random
import re
from budgetby import config
from budgetby import database as db

def get_random_ua() -> str:
    """Picks a random User-Agent from config."""
    return random.choice(config.USER_AGENTS)

def get_random_delay() -> float:
    """Returns random float between min and max delays."""
    return random.uniform(config.SCRAPER_DELAY_MIN, config.SCRAPER_DELAY_MAX)

class RetryQueue:
    """Manages failed scrapes with exponential backoff in DB."""
    
    @staticmethod
    async def add_to_retry(product_id: int, error: str):
        """Adds to DB retry queue."""
        try:
            await db.execute("""
                INSERT INTO scrape_retries (product_id, error, next_retry, attempt)
                VALUES ($1, $2, NOW() + INTERVAL '5 minutes', 1)
                ON CONFLICT (product_id) DO UPDATE SET
                    attempt = scrape_retries.attempt + 1,
                    error = $2,
                    next_retry = NOW() + (INTERVAL '1 second' * (5 * (2 ^ scrape_retries.attempt)))
            """, product_id, error)
        except Exception:
            pass

    @staticmethod
    async def get_pending_retries() -> list:
        """Returns products due for retry."""
        try:
            return await db.fetch("""
                SELECT * FROM scrape_retries WHERE next_retry <= NOW()
            """)
        except Exception:
            return []

    @staticmethod
    async def mark_retry_success(product_id: int):
        """Removes from retry queue."""
        try:
            await db.execute("DELETE FROM scrape_retries WHERE product_id = $1", product_id)
        except Exception:
            pass

def extract_price(text: str) -> float:
    """Parses Indian price strings like '₹1,999.00' or '1,999' to float."""
    if not text:
        return 0.0
    cleaned = re.sub(r'[^\d.]', '', text.replace(',', ''))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

def clean_title(text: str) -> str:
    """Removes extra whitespace and special chars from product titles."""
    if not text:
        return ""
    cleaned = re.sub(r'\s+', ' ', text)
    return cleaned.strip()
