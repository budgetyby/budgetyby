"""
Commission calculation module.
"""
import logging
from budgetby.config import AMAZON_COMMISSION_RATES, EARNKARO_COMMISSION_RATES

logger = logging.getLogger("budgetby.affiliate.commission")

def get_commission_rate(platform: str, category: str) -> float:
    """Look up commission rate from config."""
    if platform == "amazon":
        return AMAZON_COMMISSION_RATES.get(category, 0.0)
    elif platform in EARNKARO_COMMISSION_RATES:
        rates = EARNKARO_COMMISSION_RATES[platform]
        return rates.get(category, rates.get("default", 0.0))
    return 0.0

def estimate_commission(platform: str, category: str, price: float) -> float:
    """Return estimated commission in INR."""
    rate = get_commission_rate(platform, category)
    return price * rate
