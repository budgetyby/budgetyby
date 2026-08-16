"""
BudgetBy — Cooldown Management
"""

import logging
from budgetby import database, config
from budgetby.engine.evergreen import get_evergreen_cooldown_days

logger = logging.getLogger("budgetby.engine.cooldown")

async def is_on_cooldown(product_id: int) -> bool:
    try:
        query = "SELECT expires_at FROM post_cooldowns WHERE product_id = $1"
        row = await database.fetchrow(query, product_id)
        if row and row['expires_at']:
            # Assuming db NOW() is handled gracefully or we do a boolean check
            query_check = "SELECT expires_at > NOW() as active FROM post_cooldowns WHERE product_id = $1"
            res = await database.fetchrow(query_check, product_id)
            return res['active'] if res else False
        return False
    except Exception as e:
        logger.error(f"Error checking cooldown: {e}")
        return False

async def set_cooldown(product_id: int, hours: float):
    try:
        await database.execute("""
            INSERT INTO post_cooldowns (product_id, expires_at)
            VALUES ($1, NOW() + make_interval(hours => $2))
            ON CONFLICT (product_id) DO UPDATE SET
                expires_at = NOW() + make_interval(hours => $2)
        """, product_id, hours)
    except Exception as e:
        logger.error(f"Error setting cooldown: {e}")

async def set_evergreen_cooldown(product_id: int, discount_pct: float):
    days = get_evergreen_cooldown_days(discount_pct)
    await set_cooldown(product_id, days * 24.0)

async def cleanup_expired_cooldowns():
    try:
        await database.execute("DELETE FROM post_cooldowns WHERE expires_at < NOW()")
        logger.info("Cleaned up expired cooldowns.")
    except Exception as e:
        logger.error(f"Error cleaning up cooldowns: {e}")
