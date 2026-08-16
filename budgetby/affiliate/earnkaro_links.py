"""
EarnKaro affiliate link generator for Flipkart and Myntra.
"""
import logging
from budgetby.config import EARNKARO_API_KEY

logger = logging.getLogger("budgetby.affiliate.earnkaro")

async def build_earnkaro_url(url: str) -> str:
    """
    Convert a Flipkart or Myntra URL to an EarnKaro affiliate link.
    TODO: Implement actual EarnKaro API integration.
    """
    logger.debug(f"Placeholder: building EarnKaro URL for {url}")
    return url
