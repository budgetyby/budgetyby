"""
BudgetBy — Cooldown Management
"""

import logging
from budgetby import database, config
from budgetby.engine.evergreen import get_evergreen_cooldown_days

logger = logging.getLogger("budgetby.engine.cooldown")

async def is_on_cooldown(product_id: int) -> bool:
    """
    3-Layer Permanent Cooldown & Deduplication Guard:
    1. Direct product_id cooldown in post_cooldowns and deals (last 24h)
    2. SKU / ASIN / Platform ID cooldown in deals (last 24h)
    3. Title-level cooldown across same platform in deals (last 24h, prevents variant duplicate spam)
    """
    if not product_id:
        return False
    try:
        query = """
            WITH target_prod AS (
                SELECT platform, platform_id, LOWER(TRIM(title)) as norm_title
                FROM products
                WHERE id = $1
            )
            SELECT EXISTS(
                -- 1. Direct product_id cooldown
                SELECT 1 FROM post_cooldowns WHERE product_id = $1 AND expires_at > NOW()
                UNION ALL
                SELECT 1 FROM deals WHERE product_id = $1 AND posted_at > (NOW() - INTERVAL '24 hours')
                UNION ALL
                -- 2. Duplicate SKU / ASIN / Platform ID posted in last 24 hours
                SELECT 1 
                FROM deals d
                JOIN products p ON d.product_id = p.id
                JOIN target_prod tp ON p.platform = tp.platform AND p.platform_id = tp.platform_id
                WHERE d.posted_at > (NOW() - INTERVAL '24 hours')
                UNION ALL
                -- 3. Identical product Title posted in last 24 hours (prevents color/size variant duplicate spam)
                SELECT 1
                FROM deals d
                JOIN products p ON d.product_id = p.id
                JOIN target_prod tp ON p.platform = tp.platform AND LOWER(TRIM(p.title)) = tp.norm_title
                WHERE d.posted_at > (NOW() - INTERVAL '24 hours')
                  AND length(tp.norm_title) >= 8
            );
        """
        active = await database.fetchval(query, product_id)
        return bool(active)
    except Exception as e:
        logger.error(f"Error checking cooldown: {e}")
        return False

async def set_cooldown(product_id: int, hours: float):
    if not product_id:
        return
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
