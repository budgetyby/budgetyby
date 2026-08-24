"""
BudgetBy — Evergreen Deals
"""

import logging
from asyncpg import Record
from budgetby import database, config

logger = logging.getLogger("budgetby.engine.evergreen")

def get_evergreen_cooldown_days(discount_pct: float) -> int:
    """Returns the cooldown days for evergreen deals based on discount depth."""
    cooldowns = sorted(config.EVERGREEN_COOLDOWNS.items(), key=lambda x: x[0], reverse=True)
    for threshold, days in cooldowns:
        if discount_pct >= threshold:
            return days
    return 7 # Default

async def find_evergreen_deals(limit: int = 10) -> list[Record]:
    """Finds stable, highly discounted products that haven't been posted in the last 7 days, rotating diversely."""
    try:
        query = """
            SELECT p.*, ((p.mrp - p.current_price) / p.mrp) AS discount_pct
            FROM products p
            LEFT JOIN post_cooldowns c ON p.id = c.product_id AND c.expires_at > NOW()
            WHERE p.in_stock = TRUE
              AND p.mrp > 0 AND p.current_price > 0
              AND p.mrp > p.current_price
              AND ((p.mrp - p.current_price) / p.mrp) >= $1
              AND (p.mrp - p.current_price) >= $2
              AND c.product_id IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM deals d 
                  WHERE d.product_id = p.id 
                    AND d.posted_at >= NOW() - INTERVAL '7 days'
              )
            ORDER BY 
                p.rating DESC NULLS LAST,
                (((p.mrp - p.current_price) / p.mrp) * p.current_price) DESC,
                RANDOM()
            LIMIT $3
        """
        records = await database.fetch(
            query,
            config.EVERGREEN_MIN_MRP_DISCOUNT,
            config.EVERGREEN_MIN_SAVINGS_INR,
            limit
        )
        return records
    except Exception as e:
        logger.error(f"Error in find_evergreen_deals: {e}")
        return []
