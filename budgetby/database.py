"""
BudgetBy — Database Connection & Query Helpers
Uses asyncpg for high-performance async PostgreSQL access.
"""

import asyncpg
import logging
from contextlib import asynccontextmanager
from budgetby import config

logger = logging.getLogger("budgetby.database")

# Global connection pool
_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    """Initialize the connection pool. Call once at startup."""
    global _pool
    if _pool is not None:
        return _pool

    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    host_to_use = config.DB_HOST
    if "aivencloud.com" in config.DB_HOST:
        try:
            import socket
            socket.gethostbyname(config.DB_HOST)
        except socket.gaierror:
            host_to_use = "168.144.145.235"

    pool_kwargs = {
        "host": host_to_use,
        "port": config.DB_PORT,
        "database": config.DB_NAME,
        "user": config.DB_USER,
        "password": config.DB_PASSWORD,
        "min_size": 2,
        "max_size": 20,
        "command_timeout": 30,
        "statement_cache_size": 0,
    }
    if config.DB_SSL:
        pool_kwargs["ssl"] = ctx

    _pool = await asyncpg.create_pool(**pool_kwargs)
    logger.info(f"Database connection pool initialized to {host_to_use}:{config.DB_PORT} (min=2, max=20)")
    return _pool


async def close_pool():
    """Close the connection pool. Call at shutdown."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database connection pool closed")


def get_pool() -> asyncpg.Pool:
    """Get the current connection pool. Raises if not initialized."""
    if _pool is None:
        raise RuntimeError("Database pool not initialized. Call init_pool() first.")
    return _pool


@asynccontextmanager
async def acquire():
    """Acquire a connection from the pool as an async context manager."""
    pool = get_pool()
    async with pool.acquire() as conn:
        yield conn


async def fetch(query: str, *args) -> list[asyncpg.Record]:
    """Execute a query and return all result rows."""
    pool = get_pool()
    return await pool.fetch(query, *args)


async def fetchrow(query: str, *args) -> asyncpg.Record | None:
    """Execute a query and return a single row (or None)."""
    pool = get_pool()
    return await pool.fetchrow(query, *args)


async def fetchval(query: str, *args):
    """Execute a query and return a single value."""
    pool = get_pool()
    return await pool.fetchval(query, *args)


async def execute(query: str, *args) -> str:
    """Execute a query (INSERT/UPDATE/DELETE) and return status."""
    pool = get_pool()
    return await pool.execute(query, *args)


async def executemany(query: str, args_list: list) -> None:
    """Execute a query with multiple argument sets (batch insert)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.executemany(query, args_list)


# ── Product-Specific Helpers ───────────────────────────────────────────


async def upsert_product(data: dict) -> int:
    """
    Insert a new product or update if it already exists (same platform + platform_id).
    Returns the product id.
    """
    # Automated title sanitizer: if title is missing or generic, derive from URL slug
    title = data.get("title") or ""
    p_url = data.get("product_url") or ""
    if not title or len(title) < 5 or "product" in title.lower() or "editor" in title.lower():
        if p_url:
            import re
            slug = re.sub(r'https?://[^/]+/', '', p_url).split('/p/')[0].split('?')[0].lstrip('/').replace('-', ' ').title()
            if len(slug) >= 4:
                title = slug
    if not title:
        title = f"{str(data.get('platform', '')).capitalize()} Item {data.get('platform_id', '')}"

    row = await fetchrow("""
        INSERT INTO products (platform, platform_id, title, category,
                              product_url, affiliate_url, image_url,
                              current_price, mrp, rating, review_count,
                              in_stock, is_renewed, status, priority_tier,
                              last_checked, next_check, all_time_low)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
                $12, $13, $14, $15, NOW(), NOW(), $8)
        ON CONFLICT (platform, platform_id) DO UPDATE SET
            title = COALESCE(EXCLUDED.title, products.title),
            category = COALESCE(EXCLUDED.category, products.category),
            image_url = COALESCE(EXCLUDED.image_url, products.image_url),
            affiliate_url = EXCLUDED.affiliate_url,
            last_checked = NOW()
        RETURNING id
    """,
        data.get("platform"),
        data.get("platform_id"),
        title,
        data.get("category"),
        data.get("product_url"),
        data.get("affiliate_url"),
        data.get("image_url"),
        data.get("current_price"),
        data.get("mrp"),
        data.get("rating"),
        data.get("review_count", 0),
        data.get("in_stock", True),
        data.get("is_renewed", False),
        data.get("status", config.STATUS_ACTIVE),
        data.get("priority_tier", 3),
    )
    return row["id"]


async def update_price(product_id: int, new_price: float, in_stock: bool,
                        has_coupon: bool = False, coupon_value: float = 0,
                        has_bank_offer: bool = False, bank_offer_text: str = None,
                        title: str = None, mrp: float = None, rating: float = None,
                        review_count: int = None, image_url: str = None):
    """
    Update a product's live price snapshot and product details (title, mrp, rating, etc.).
    Also updates min benchmarks and all_time_low.
    """
    await execute("""
        UPDATE products SET
            previous_price = current_price,
            current_price = $2,
            in_stock = $3,
            has_coupon = $4,
            coupon_value = $5,
            has_bank_offer = $6,
            bank_offer_text = $7,
            title = CASE WHEN $8 IS NOT NULL AND $8 != '' THEN $8 ELSE title END,
            mrp = COALESCE($9, mrp),
            rating = COALESCE($10, rating),
            review_count = COALESCE($11, review_count),
            image_url = CASE WHEN $12 IS NOT NULL AND $12 != '' THEN $12 ELSE image_url END,
            last_checked = NOW(),
            last_price_change = CASE
                WHEN current_price IS DISTINCT FROM $2 THEN NOW()
                ELSE last_price_change
            END,
            all_time_low = LEAST(all_time_low, $2)
        WHERE id = $1
    """, product_id, new_price, in_stock, has_coupon, coupon_value,
         has_bank_offer, bank_offer_text, title, mrp, rating,
         review_count, image_url)


async def upsert_daily_price(product_id: int, price: float):
    """
    Upsert today's daily price record.
    If row exists for today: update min_price (LEAST) and close_price.
    If no row: insert new.
    """
    await execute("""
        INSERT INTO daily_prices (product_id, date, min_price, close_price)
        VALUES ($1, (NOW() AT TIME ZONE 'Asia/Kolkata')::DATE, $2, $2)
        ON CONFLICT (product_id, date) DO UPDATE SET
            min_price = LEAST(daily_prices.min_price, $2),
            close_price = $2
    """, product_id, price)


async def get_products_due_for_check(limit: int = 50) -> list[asyncpg.Record]:
    """
    Get products due for checking.
    Prioritizes products missing prices or strike-through MRPs first, then priority_tier, then next_check.
    """
    return await fetch("""
        SELECT * FROM products
        WHERE status IN ($1, $2)
          AND next_check <= NOW()
        ORDER BY 
            CASE WHEN current_price IS NULL THEN 0 ELSE 1 END ASC,
            priority_tier ASC, 
            next_check ASC
        LIMIT $3
    """, config.STATUS_ACTIVE, config.STATUS_TEMP_OOS, limit)


async def schedule_next_check(product_id: int, priority_tier: int):
    """Set the product's next check time based on its priority tier."""
    interval_seconds = config.PRIORITY_INTERVALS.get(priority_tier, 6 * 3600)
    await execute("""
        UPDATE products SET
            priority_tier = $2,
            next_check = NOW() + make_interval(secs => $3)
        WHERE id = $1
    """, product_id, priority_tier, interval_seconds)


async def refresh_30d_benchmarks():
    """
    Recalculate min_30d and median_30d_price from daily_prices for all products.
    Run daily at midnight.
    """
    await execute("""
        UPDATE products p SET
            min_30d = sub.min_30d,
            median_30d_price = sub.median_price
        FROM (
            SELECT
                product_id,
                MIN(min_price) AS min_30d,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY close_price) AS median_price
            FROM daily_prices
            WHERE date >= ((NOW() AT TIME ZONE 'Asia/Kolkata')::DATE - 30)
            GROUP BY product_id
        ) sub
        WHERE p.id = sub.product_id
    """)
    logger.info("Refreshed 30-day benchmarks for all products")


async def monthly_benchmark_shift():
    """
    Monthly sliding window shift:
    min_90d ← min_60d, min_60d ← min_30d, then min_30d recalculates fresh.
    """
    await execute("""
        UPDATE products SET
            min_90d = min_60d,
            min_60d = min_30d
    """)
    await refresh_30d_benchmarks()
    logger.info("Monthly benchmark shift complete")


async def cleanup_old_daily_prices():
    """Delete daily_prices older than retention period."""
    result = await execute("""
        DELETE FROM daily_prices
        WHERE date < (NOW() AT TIME ZONE 'Asia/Kolkata')::DATE - $1
    """, config.DAILY_PRICE_RETENTION_DAYS)
    logger.info(f"Cleaned up old daily prices: {result}")


async def get_product_by_platform_id(platform: str, platform_id: str) -> asyncpg.Record | None:
    """Look up a product by its platform and platform-specific ID."""
    return await fetchrow("""
        SELECT * FROM products
        WHERE platform = $1 AND platform_id = $2
    """, platform, platform_id)


async def get_active_deal_tracking() -> list[asyncpg.Record]:
    """Get all deals being tracked for message editing (within 2.5-day window)."""
    return await fetch("""
        SELECT dt.*, p.current_price, p.in_stock, p.title
        FROM deal_tracking dt
        JOIN products p ON dt.product_id = p.id
        WHERE dt.track_until > NOW()
          AND dt.is_finalized = FALSE
    """)


async def insert_deal_tracking(deal_id: int, product_id: int, message_id: int,
                                 channel_id: str, caption: str, price: float):
    """Record a posted deal for 2.5-day edit tracking."""
    await execute("""
        INSERT INTO deal_tracking (deal_id, product_id, message_id, channel_id,
                                    original_caption, posted_price, posted_at, track_until)
        VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW() + INTERVAL '60 hours')
    """, deal_id, product_id, message_id, channel_id, caption, price)


async def finalize_expired_tracking():
    """Mark expired tracking records as finalized."""
    result = await execute("""
        UPDATE deal_tracking
        SET is_finalized = TRUE
        WHERE track_until < NOW() AND is_finalized = FALSE
    """)
    logger.info(f"Finalized expired deal tracking: {result}")
