"""
EarnKaro affiliate link generator for Flipkart, Myntra, Ajio, and Nykaa.
Automatically routes products through EarnKaro profit referral tracking.
"""
import logging
import urllib.parse
from budgetby import config

logger = logging.getLogger("budgetby.affiliate.earnkaro")

def build_earnkaro_url_sync(url: str) -> str:
    """
    Convert any Flipkart, Myntra, Ajio, or Nykaa URL to an EarnKaro affiliate profit link.
    Format: https://earnkaro.com/product?r={user_id}&url={encoded_url}
    """
    if not url:
        return ""
    user_id = config.EARNKARO_API_KEY or "5549565"
    encoded_url = urllib.parse.quote_plus(url)
    return f"https://earnkaro.com/product?r={user_id}&url={encoded_url}"

async def build_earnkaro_url(url: str) -> str:
    """Async wrapper for compatibility."""
    return build_earnkaro_url_sync(url)
