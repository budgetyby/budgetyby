"""
BudgetBy — Scraper Utilities
"""
import random
import re
from budgetby import config
def get_random_ua() -> str:
    """Picks a random User-Agent from config."""
    return random.choice(config.USER_AGENTS)

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
    """Sanitizes product titles, removing leaked prices, discounts, leading numbers, and trailing ratings/card junk."""
    if not text:
        return ""
    # Remove currency symbol and any attached price/discount noise (e.g. "Top₹292₹2,99990% off...")
    cleaned = re.split(r'[\u20b9₹]', text)[0]
    
    # Strip leading list numbers/bullets (e.g. "3. CANTABIL...", "1) Nike...", "10 - Puma...", "(1) Item...")
    cleaned = re.sub(r'^(?:\d+[\.\)\-:\s]+|\(\d+\)\s*)', '', cleaned)
    # Strip leading bracketed SKU/ASIN codes (e.g. "[B09XKZV7S8] Men's...", "[1202621] ...")
    cleaned = re.sub(r'^\[[A-Za-z0-9_\-]+\]\s*', '', cleaned)
    
    # Strip trailing rating and review text (e.g. "...4115 Ratings&10 Reviews", "...4.2★ (120)")
    cleaned = re.sub(r'\b\d[\d,]*\s*Ratings?\s*&?\s*[\d,]*\s*Reviews?.*', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\b\d(?:\.\d)?\s*★.*', '', cleaned)
    
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

