"""
EarnKaro affiliate link generator for Flipkart, Myntra, Ajio, and Nykaa.
Automatically routes products through EarnKaro profit referral tracking.
"""
import logging
import urllib.parse
from budgetby import config

logger = logging.getLogger("budgetby.affiliate.earnkaro")

def build_earnkaro_url_sync(url: str) -> str:
    return url or ""

async def build_earnkaro_url(url: str) -> str:
    """Async wrapper for compatibility."""
    return build_earnkaro_url_sync(url)
