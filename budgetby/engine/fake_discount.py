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
        mrp = product.get("mrp")
        median_30d = product.get("median_30d_price")
        # In a real setup, we'd check previous MRPs from a price history table.
        # Here we simulate by looking at some available fields if present.
        
        if not mrp or not median_30d or median_30d <= 0:
            return False

        # If price is within 10% of median_30d
        if abs(new_price - median_30d) / median_30d <= 0.10:
            # We'll just assume fake discount if MRP is significantly higher than historical median
            # representing an inflated MRP (e.g. MRP > 2x median) and current price is close to median.
            # OR we check if previous_price < mrp which indicates MRP inflation.
            previous_price = product.get("previous_price")
            if previous_price and previous_price < mrp and (mrp - previous_price) / previous_price > 0.20:
                 return True

        return False
    except Exception as e:
        logger.error(f"Error in is_fake_discount: {e}")
        return False
