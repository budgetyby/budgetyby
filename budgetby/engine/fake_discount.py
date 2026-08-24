"""
BudgetBy — Fake Discount Detection
"""

import logging
from asyncpg import Record

logger = logging.getLogger("budgetby.engine.fake_discount")

async def is_fake_discount(product: Record, new_price: float) -> bool:
    """
    Checks if the product has a fake discount.
    If MRP rose >20% and current price is within 10% of median_30d, it's considered fake.
    Note: We might lack 7-day MRP history in DB, so we use a heuristic based on available data.
    """
    try:
        mrp = float(product.get("mrp")) if product.get("mrp") else None
        median_30d = float(product.get("median_30d_price")) if product.get("median_30d_price") else None
        new_price = float(new_price)
        
        if not mrp or not median_30d or median_30d <= 0:
            return False

        # If price is within 10% of median_30d
        if abs(new_price - median_30d) / median_30d <= 0.10:
            previous_price = float(product.get("previous_price")) if product.get("previous_price") else None
            if previous_price and previous_price < mrp and (mrp - previous_price) / previous_price > 0.20:
                 return True

        return False
    except Exception as e:
        logger.error(f"Error in is_fake_discount: {e}")
        return False
