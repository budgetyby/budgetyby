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
    """Finds stable, highly discounted products that haven't been posted recently."""
    try:
        # Note: 'post_cooldowns' is assumed to exist
        query = f"""
            SELECT p.*, ((p.mrp - p.current_price) / p.mrp) AS discount_pct
            FROM products p
            LEFT JOIN post_cooldowns c ON p.id = c.product_id AND c.expires_at > NOW()
            WHERE p.in_stock = TRUE
              AND p.mrp > 0 AND p.current_price > 0
              AND ((p.mrp - p.current_price) / p.mrp) >= $1
              AND (p.mrp - p.current_price) >= $2
              AND p.last_price_change < NOW() - make_interval(hours => $3)
              AND c.product_id IS NULL
            ORDER BY (((p.mrp - p.current_price) / p.mrp) * p.current_price) DESC
            LIMIT $4
        """
        records = await database.fetch(
            query,
            config.EVERGREEN_MIN_MRP_DISCOUNT,
            config.EVERGREEN_MIN_SAVINGS_INR,
            config.EVERGREEN_MIN_STABLE_HOURS,
            limit
        )
        return records
    except Exception as e:
        logger.error(f"Error in find_evergreen_deals: {e}")
        return []
