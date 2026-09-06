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
    """Parses Indian price strings like '₹1,999.00' or '1,999' to float, avoiding concatenated digits."""
    if not text:
        return 0.0
    cleaned = text.replace('\xa0', ' ').replace(',', '').strip()
    match = re.search(r'(\d+(?:\.\d{1,2})?)', cleaned)
    if not match:
        return 0.0
    try:
        val = float(match.group(1))
        # Reject numbers > 20,00,000 (20 Lakhs) as they are tracking IDs/phone numbers/metadata
        if val > 2000000.0:
            return 0.0
        return val
    except ValueError:
        return 0.0

def clean_title(text: str) -> str:
    """Sanitizes product titles, removing leaked prices, discounts, and trailing card junk."""
    if not text:
        return ""
    # Remove currency symbol and any attached price/discount noise (e.g. "Top₹292₹2,99990% off...")
    cleaned = re.split(r'[\u20b9₹]', text)[0]
    
    # Remove discount percentages and attached stock/delivery text
    cleaned = re.sub(r'\b\d{1,2}%\s*off\b.*', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\b(only\s+\w+\s+left|in\s+stock|out\s+of\s+stock|free\s+delivery|bank\s+offer|special\s+price)\b.*', '', cleaned, flags=re.IGNORECASE)
    
    # Add space between concatenated brand and title words (e.g. "COLLECTIONCasual" -> "COLLECTION Casual", "CollectionsCasual" -> "Collections Casual")
    cleaned = re.sub(r'([a-z])([A-Z])', r'\1 \2', cleaned)
    cleaned = re.sub(r'([A-Z]{2,})([A-Z][a-z])', r'\1 \2', cleaned)

    # Clean up non-breaking spaces and collapse whitespace
    cleaned = cleaned.replace('\xa0', ' ')
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned.strip(' -–—,:|')
