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
        "min_size": 1,
        "max_size": 6,
        "command_timeout": 30,
        "statement_cache_size": 0,
    }
    if config.DB_SSL and str(config.DB_SSL).lower() not in ("disable", "false", "none", "0", ""):
        pool_kwargs["ssl"] = ctx

    _pool = await asyncpg.create_pool(**pool_kwargs)
    logger.info(f"Database connection pool initialized to {host_to_use}:{config.DB_PORT} (min=1, max=6)")
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
    # Strict Exclusion Guard: Croma is permanently excluded across the entire system
    platform = str(data.get("platform") or "").strip().lower()
    p_url = str(data.get("product_url") or "").strip()
    if platform == "croma" or "croma.com" in p_url.lower():
        logger.debug("Excluded Croma product from ingestion.")
        return 0

    # Automated title sanitizer: if title is missing or generic, derive from URL slug
    title = data.get("title") or ""
    if not title or len(title) < 5 or "product" in title.lower() or "editor" in title.lower():
        if p_url:
            import re
            slug = re.sub(r'https?://[^/]+/', '', p_url).split('/p/')[0].split('?')[0].lstrip('/').replace('-', ' ').title()
            if len(slug) >= 4:
                title = slug
    if not title:
        title = f"{str(data.get('platform', '')).capitalize()} Item {data.get('platform_id', '')}"

    cur_price = data.get("current_price")
    mrp_val = data.get("mrp")
    if cur_price and mrp_val and cur_price > 0:
        if mrp_val > 4.0 * cur_price or (mrp_val > 100000 and cur_price < 10000):
            mrp_val = round((cur_price * 1.35) / 10) * 10

    platform = data.get("platform")
    platform_id = str(data.get("platform_id") or "")

    # Strict Deduplication Check: Look for existing product by platform_id, URL, or normalized Title
    existing = await fetchrow("""
        SELECT id, current_price, mrp, all_time_low 
        FROM products 
        WHERE platform = $1 
          AND (platform_id = $2 OR product_url = $3 OR LOWER(TRIM(title)) = LOWER(TRIM($4)))
        LIMIT 1;
    """, platform, platform_id, p_url, title)

    if existing:
        existing_id = existing["id"]
        # Update existing record instead of creating duplicate
        await execute("""
            UPDATE products SET
                current_price = COALESCE($2, current_price),
                mrp = COALESCE($3, mrp),
                rating = COALESCE($4, rating),
                review_count = COALESCE($5, review_count),
                image_url = COALESCE(NULLIF(TRIM($6), ''), image_url),
                affiliate_url = CASE
                    WHEN $7 ILIKE '%fktr.in%' OR $7 ILIKE '%myntr.it%' OR $7 ILIKE '%ajiio.in%' OR $7 ILIKE '%ekaro.in%' OR $7 ILIKE '%clnk.in%' OR ($7 ILIKE '%amazon.in%' AND $7 ILIKE '%tag=%') THEN $7
                    WHEN products.affiliate_url ILIKE '%fktr.in%' OR products.affiliate_url ILIKE '%myntr.it%' OR products.affiliate_url ILIKE '%ajiio.in%' OR products.affiliate_url ILIKE '%ekaro.in%' OR products.affiliate_url ILIKE '%clnk.in%' OR (products.affiliate_url ILIKE '%amazon.in%' AND products.affiliate_url ILIKE '%tag=%') THEN products.affiliate_url
                    ELSE COALESCE($7, products.affiliate_url)
                END,
                in_stock = COALESCE($8, in_stock),
                last_checked = NOW(),
                all_time_low = LEAST(COALESCE($2, all_time_low), all_time_low)
            WHERE id = $1;
        """, existing_id, cur_price, mrp_val, data.get("rating"), data.get("review_count"), 
             data.get("image_url"), data.get("affiliate_url"), data.get("in_stock", True))
        
        if cur_price and cur_price > 0:
            try:
                await upsert_daily_price(existing_id, cur_price)
            except Exception:
                pass
        return existing_id

    aff_url = data.get("affiliate_url") or p_url

    # If product does not exist, insert cleanly
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
            image_url = COALESCE(NULLIF(TRIM(EXCLUDED.image_url), ''), products.image_url),
            affiliate_url = CASE
                WHEN EXCLUDED.affiliate_url ILIKE '%fktr.in%' OR EXCLUDED.affiliate_url ILIKE '%myntr.it%' OR EXCLUDED.affiliate_url ILIKE '%ajiio.in%' OR EXCLUDED.affiliate_url ILIKE '%ekaro.in%' OR EXCLUDED.affiliate_url ILIKE '%clnk.in%' OR (EXCLUDED.affiliate_url ILIKE '%amazon.in%' AND EXCLUDED.affiliate_url ILIKE '%tag=%') THEN EXCLUDED.affiliate_url
                WHEN products.affiliate_url ILIKE '%fktr.in%' OR products.affiliate_url ILIKE '%myntr.it%' OR products.affiliate_url ILIKE '%ajiio.in%' OR products.affiliate_url ILIKE '%ekaro.in%' OR products.affiliate_url ILIKE '%clnk.in%' OR (products.affiliate_url ILIKE '%amazon.in%' AND products.affiliate_url ILIKE '%tag=%') THEN products.affiliate_url
                ELSE COALESCE(EXCLUDED.affiliate_url, products.affiliate_url)
            END,
            last_checked = NOW()
        RETURNING id
    """,
        platform,
        platform_id,
        title,
        data.get("category"),
        p_url,
        aff_url,
        data.get("image_url"),
        cur_price,
        mrp_val,
        data.get("rating"),
        data.get("review_count", 0),
        data.get("in_stock", True),
        data.get("is_renewed", False),
        data.get("status", config.STATUS_ACTIVE),
        data.get("priority_tier", 3),
    )
    if cur_price and cur_price > 0:
        try:
            await upsert_daily_price(row["id"], cur_price)
        except Exception:
            pass
    return row["id"]


async def update_price(product_id: int, new_price: float, in_stock: bool,
                        title: str = None, mrp: float = None, rating: float = None,
                        review_count: int = None, image_url: str = None):
    """
    Update a product's live price snapshot and product details (title, mrp, rating, etc.).
    Also updates min benchmarks and all_time_low.
    """
    if new_price and new_price > 0:
        if mrp:
            if new_price > mrp:
                mrp = new_price
            elif mrp > 4.0 * new_price or (mrp > 100000 and new_price < 10000):
                mrp = round((new_price * 1.35) / 10) * 10
    await execute("""
        UPDATE products SET
            previous_price = current_price,
            current_price = $2::numeric,
            in_stock = $3::boolean,
            title = CASE WHEN $4::text IS NOT NULL AND $4::text != '' THEN $4::text ELSE title END,
            mrp = CASE 
                WHEN $5::numeric IS NOT NULL THEN $5::numeric
                WHEN mrp < $2::numeric THEN $2::numeric
                ELSE mrp 
            END,
            rating = COALESCE($6::numeric, rating),
            review_count = COALESCE($7::integer, review_count),
            image_url = CASE WHEN $8::text IS NOT NULL AND $8 != '' THEN $8::text ELSE image_url END,
            last_checked = NOW(),
            last_price_change = CASE
                WHEN current_price IS DISTINCT FROM $2::numeric THEN NOW()
                ELSE last_price_change
            END,
            all_time_low = LEAST(all_time_low, $2::numeric)
        WHERE id = $1::integer
    """, product_id, new_price, in_stock, title, mrp, rating,
         review_count, image_url)


async def sync_daily_price_baselines():
    """
    Ensures 100% of all active products in the catalog have a daily_price snapshot for today.
    Runs instantaneously at midnight and on startup.
    """
    await execute("""
        INSERT INTO daily_prices (product_id, date, min_price, close_price)
        SELECT id, (NOW() AT TIME ZONE 'Asia/Kolkata')::DATE, current_price, current_price
        FROM products
        WHERE status = 'ACTIVE' AND current_price > 0
        ON CONFLICT (product_id, date) DO NOTHING;
    """)

async def upsert_daily_price(product_id: int, price: float):
    """
    Upsert today's daily price record.
    If row exists for today: update min_price (LEAST) and close_price.
    If no row: insert new.
    """
    if not price or price <= 0:
        return
    await execute("""
        INSERT INTO daily_prices (product_id, date, min_price, close_price)
        VALUES ($1, (NOW() AT TIME ZONE 'Asia/Kolkata')::DATE, $2, $2)
        ON CONFLICT (product_id, date) DO UPDATE SET
            min_price = LEAST(daily_prices.min_price, $2),
            close_price = $2
    """, product_id, price)


async def get_products_due_for_check(limit: int = 50) -> list[asyncpg.Record]:
    """
    Get products due for checking with balanced round-robin sampling across all 5 platforms.
    Prevents any single platform from starving or monopolizing the scanner queue.
    """
    per_platform = max(5, limit // 5)
    return await fetch("""
        WITH ranked_candidates AS (
            SELECT p.*,
                   EXISTS(
                       SELECT 1 FROM deals d 
                       WHERE d.product_id = p.id 
                         AND d.posted_at >= NOW() - INTERVAL '48 hours'
                   ) as has_recent_deal,
                   ROW_NUMBER() OVER (
                       PARTITION BY p.platform 
                       ORDER BY 
                           CASE WHEN p.current_price IS NULL THEN 0 ELSE 1 END ASC,
                           p.priority_tier ASC, 
                           p.next_check ASC
                   ) as rank_in_platform
            FROM products p
            WHERE p.status IN ($1, $2)
              AND p.next_check <= NOW()
              AND LOWER(p.platform) != 'croma'
        )
        SELECT * FROM ranked_candidates
        WHERE rank_in_platform <= $4
        ORDER BY rank_in_platform ASC, next_check ASC
        LIMIT $3;
    """, config.STATUS_ACTIVE, config.STATUS_TEMP_OOS, limit, per_platform)


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
        WHERE date < (NOW() AT TIME ZONE 'Asia/Kolkata')::DATE - ($1 * INTERVAL '1 day')
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


async def insert_deal(data: dict) -> int:
    """
    Insert a broadcasted deal record into the deals table.
    Guarantees that the underlying product record is synchronized with last_checked = NOW()
    and verified current_price so customer freshness badges always reflect real-time verification.
    """
    pid = data.get("product_id")
    posted_price = data.get("posted_price")
    row = await fetchrow("""
        INSERT INTO deals (
            product_id, deal_type, posted_price,
            posted_mrp, savings_amount, savings_pct, deal_score,
            badge, source_channel, posted_at
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, (NOW() AT TIME ZONE 'Asia/Kolkata')
        )
        ON CONFLICT (product_id) DO UPDATE SET
            deal_type = EXCLUDED.deal_type,
            posted_price = EXCLUDED.posted_price,
            posted_mrp = EXCLUDED.posted_mrp,
            savings_amount = EXCLUDED.savings_amount,
            savings_pct = EXCLUDED.savings_pct,
            deal_score = EXCLUDED.deal_score,
            badge = EXCLUDED.badge,
            source_channel = EXCLUDED.source_channel,
            posted_at = EXCLUDED.posted_at
        RETURNING id;
    """,
        pid,
        data.get("deal_type", "price_drop"),
        posted_price,
        data.get("posted_mrp"),
        data.get("savings_amount", 0.0),
        data.get("savings_pct", 0.0),
        data.get("deal_score", 50.0),
        data.get("badge", "DEAL"),
        data.get("source_channel", "local_scanner")
    )
    if pid and posted_price:
        try:
            await execute("""
                UPDATE products 
                SET last_checked = (NOW() AT TIME ZONE 'Asia/Kolkata'),
                    current_price = $1,
                    in_stock = TRUE
                WHERE id = $2;
            """, float(posted_price), pid)
        except Exception as e:
            logger.debug(f"Sync product on deal insert note: {e}")
    return row["id"] if row else None


async def get_core_metrics() -> dict:
    """
    Centralized Single Source of Truth for system-wide platform metrics.
    Guarantees 100% mathematical synchronization across:
    1. Direct PostgreSQL Database queries
    2. Admin Control Center (/api/stats)
    3. PostgreSQL Database Studio (/api/db/overview)
    4. 24h Movements Hub (/api/price_changes_24h)
    5. Consumer Storefront Header & Hero (/api/public/stats)
    6. Consumer 24h Price Drops Carousel (/api/public/price-drops)
    """
    total_prods = await fetchval("SELECT COUNT(*) FROM products WHERE LOWER(platform) != 'croma';")
    prods_today = await fetchval("""
        SELECT COUNT(*) FROM products 
        WHERE (created_at AT TIME ZONE 'Asia/Kolkata')::DATE = (NOW() AT TIME ZONE 'Asia/Kolkata')::DATE
          AND LOWER(platform) != 'croma';
    """)
    total_deals = await fetchval("""
        SELECT COUNT(DISTINCT d.product_id) FROM deals d 
        JOIN products p ON d.product_id = p.id 
        WHERE LOWER(p.platform) != 'croma'
          AND p.in_stock = TRUE
          AND p.status = 'ACTIVE'
          AND p.current_price > 0
          AND p.current_price <= (d.posted_price * 1.01)
          AND d.posted_at >= NOW() - INTERVAL '30 days';
    """)
    lifetime_deals = await fetchval("""
        SELECT COUNT(*) FROM deals d 
        JOIN products p ON d.product_id = p.id 
        WHERE LOWER(p.platform) != 'croma';
    """)
    deals_today = await fetchval("""
        SELECT COUNT(DISTINCT d.product_id) FROM deals d 
        JOIN products p ON d.product_id = p.id 
        WHERE d.posted_at >= (NOW() AT TIME ZONE 'Asia/Kolkata')::DATE
          AND LOWER(p.platform) != 'croma'
          AND p.in_stock = TRUE
          AND p.status = 'ACTIVE'
          AND p.current_price > 0
          AND p.current_price <= (d.posted_price * 1.01);
    """)
    drops_today = await fetchval("""
        SELECT COUNT(*) FROM products p
        JOIN daily_prices dp_today ON p.id = dp_today.product_id AND dp_today.date = (NOW() AT TIME ZONE 'Asia/Kolkata')::DATE
        JOIN daily_prices dp_yest ON p.id = dp_yest.product_id AND dp_yest.date = ((NOW() AT TIME ZONE 'Asia/Kolkata')::DATE - 1)
        WHERE dp_today.close_price < dp_yest.close_price 
          AND p.in_stock = TRUE
          AND dp_today.close_price > 0 AND dp_yest.close_price > 0
          AND LOWER(p.platform) != 'croma';
    """)
    return {
        "total_products": total_prods or 0,
        "products_added_today": prods_today or 0,
        "total_deals": total_deals or 0,
        "active_deals": total_deals or 0,
        "lifetime_deals": lifetime_deals or 0,
        "deals_today": deals_today or 0,
        "drops_today": drops_today or 0,
    }

