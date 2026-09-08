"""
BudgetBy — Evergreen Deals
"""

import logging
from asyncpg import Record
from budgetby import database, config

logger = logging.getLogger("budgetby.engine.evergreen")

def get_evergreen_cooldown_days(discount_pct: float) -> int:
    """Returns the cooldown days for evergreen deals."""
    return config.EVERGREEN_COOLDOWN_DAYS

async def find_evergreen_deals(limit: int = 10, platform: str = None) -> list[Record]:
    """Finds stable, highly discounted products that haven't been posted in the last 7 days."""
    try:
        platform_filter = "AND p.platform = $3" if platform else ""
        query = f"""
            SELECT p.id, p.platform, p.product_url, p.affiliate_url, p.title, p.current_price, p.mrp, p.rating, p.review_count, p.image_url, p.category, ((p.mrp - p.current_price) / p.mrp) AS discount_pct
            FROM products p
            LEFT JOIN post_cooldowns c ON p.id = c.product_id AND c.expires_at > NOW()
            WHERE p.in_stock = TRUE
              AND p.mrp > 0 AND p.current_price > 0
              AND p.mrp > p.current_price
              AND p.mrp <= p.current_price * 4.5
              AND ((p.mrp - p.current_price) / p.mrp) >= $1
              AND ((p.mrp - p.current_price) / p.mrp) <= 0.85
              AND (p.mrp - p.current_price) >= $2
              AND NOT (p.mrp > 15000 AND p.current_price < 1500)
              {platform_filter}
              AND c.product_id IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM deals d 
                  WHERE d.product_id = p.id 
                    AND d.posted_at >= NOW() - make_interval(days => {config.DUPLICATE_EXPIRY_DAYS})
              )
            ORDER BY 
                ((p.mrp - p.current_price) / p.mrp) DESC,
                p.rating DESC NULLS LAST,
                RANDOM()
            LIMIT ${4 if platform else 3}
        """
        args = [config.EVERGREEN_MIN_MRP_DISCOUNT, config.EVERGREEN_MIN_SAVINGS_INR]
        if platform:
            args.append(platform)
        args.append(limit)
        return await database.fetch(query, *args)
    except Exception as e:
        logger.error(f"Error in find_evergreen_deals: {e}")
        return []

async def find_still_in_stock_reminders(limit: int = 5, platform: str = None) -> list[Record]:
    """Finds deals posted 2 to 7 days ago that are STILL in stock for reminders (doesn't count towards fresh minimums)."""
    try:
        platform_filter = "AND p.platform = $1" if platform else ""
        query = f"""
            SELECT p.*, d.posted_price, d.posted_at as initial_posted_at
            FROM deals d
            JOIN products p ON d.product_id = p.id
            LEFT JOIN post_cooldowns c ON p.id = c.product_id AND c.expires_at > NOW()
            WHERE p.in_stock = TRUE
              AND p.current_price > 0
              AND d.posted_at <= NOW() - make_interval(hours => {config.MIN_REMINDER_DELAY_HOURS})
              AND d.posted_at >= NOW() - make_interval(days => {config.DUPLICATE_EXPIRY_DAYS})
              {platform_filter}
              AND c.product_id IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM deals d2 
                  WHERE d2.product_id = p.id 
                    AND d2.deal_type = 'reminder' 
                    AND d2.posted_at >= NOW() - INTERVAL '48 hours'
              )
            ORDER BY d.posted_at ASC, RANDOM()
            LIMIT ${2 if platform else 1}
        """
        args = [platform] if platform else []
        args.append(limit)
        return await database.fetch(query, *args)
    except Exception as e:
        logger.error(f"Error in find_still_in_stock_reminders: {e}")
        return []
