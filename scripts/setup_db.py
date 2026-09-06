"""
BudgetBy — Database Schema Setup
Run once to create all required tables.
Usage: python -m scripts.setup_db
"""

import asyncio
import asyncpg
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from budgetby.config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, DB_SSL


SCHEMA_SQL = """
-- ══════════════════════════════════════════════════════════════════════
-- PRODUCTS — Main product catalog (1 row per tracked product)
-- ══════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS products (
    id                  SERIAL PRIMARY KEY,
    platform            VARCHAR(10) NOT NULL,
    platform_id         VARCHAR(50) NOT NULL,
    title               TEXT NOT NULL,
    category            VARCHAR(50),
    product_url         TEXT NOT NULL,
    affiliate_url       TEXT NOT NULL,
    image_url           TEXT,

    -- Live prices (updated every check)
    current_price       NUMERIC(10,2),
    previous_price      NUMERIC(10,2),
    mrp                 NUMERIC(10,2),

    -- Price benchmarks (updated daily/monthly)
    median_30d_price    NUMERIC(10,2),
    min_30d             NUMERIC(10,2),
    min_60d             NUMERIC(10,2),
    min_90d             NUMERIC(10,2),
    min_120d            NUMERIC(10,2),
    all_time_low        NUMERIC(10,2),

    -- Product signals (scraped from product page)
    rating              NUMERIC(3,1),
    review_count        INTEGER DEFAULT 0,
    in_stock            BOOLEAN DEFAULT TRUE,
    is_renewed          BOOLEAN DEFAULT FALSE,

    -- Scheduling & state
    status              VARCHAR(20) DEFAULT 'ACTIVE',
    priority_tier       INTEGER DEFAULT 3,
    last_checked        TIMESTAMPTZ,
    next_check          TIMESTAMPTZ,
    last_price_change   TIMESTAMPTZ,
    first_oos_at        TIMESTAMPTZ,

    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(platform, platform_id)
);

CREATE INDEX IF NOT EXISTS idx_products_next_check
    ON products(next_check ASC) WHERE status IN ('ACTIVE', 'TEMP_OOS');
CREATE INDEX IF NOT EXISTS idx_products_platform
    ON products(platform, platform_id);
CREATE INDEX IF NOT EXISTS idx_products_category
    ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_status
    ON products(status);


-- ══════════════════════════════════════════════════════════════════════
-- DAILY PRICES — Tiered price history (raw: 5 days | compressed 3-day buckets: days 6-30)
-- After 30 days all rows deleted; benchmarks live on products.min_30d/median_30d_price
-- ══════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS daily_prices (
    id            SERIAL PRIMARY KEY,
    product_id    INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    date          DATE NOT NULL,
    min_price     NUMERIC(10,2) NOT NULL,
    close_price   NUMERIC(10,2) NOT NULL,
    is_compressed BOOLEAN DEFAULT FALSE,  -- TRUE = 3-day average bucket; FALSE = raw daily row
    UNIQUE(product_id, date)
);

CREATE INDEX IF NOT EXISTS idx_daily_prices_product_date
    ON daily_prices(product_id, date DESC);

CREATE INDEX IF NOT EXISTS idx_daily_prices_compressed
    ON daily_prices(product_id, date DESC, is_compressed);


-- ══════════════════════════════════════════════════════════════════════
-- DEALS — Log of all posted deals
-- ══════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS deals (
    id              SERIAL PRIMARY KEY,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    deal_type       VARCHAR(20),
    badge           VARCHAR(100),
    posted_price    NUMERIC(10,2) NOT NULL,
    posted_mrp      NUMERIC(10,2),
    savings_amount  NUMERIC(10,2),
    savings_pct     NUMERIC(5,2),
    deal_score      NUMERIC(5,1),
    posted_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_deals_product
    ON deals(product_id, posted_at DESC);


-- ══════════════════════════════════════════════════════════════════════
-- DEAL TRACKING — 2.5-day message edit window
-- ══════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS deal_tracking (
    id                  SERIAL PRIMARY KEY,
    deal_id             INTEGER REFERENCES deals(id),
    product_id          INTEGER NOT NULL REFERENCES products(id),
    message_id          BIGINT NOT NULL,
    channel_id          VARCHAR(50) NOT NULL,
    original_caption    TEXT NOT NULL,
    posted_price        NUMERIC(10,2) NOT NULL,
    posted_at           TIMESTAMPTZ DEFAULT NOW(),
    track_until         TIMESTAMPTZ NOT NULL,
    last_edited         TIMESTAMPTZ,
    is_finalized        BOOLEAN DEFAULT FALSE,
    UNIQUE(message_id, channel_id)
);

CREATE INDEX IF NOT EXISTS idx_deal_tracking_active
    ON deal_tracking(track_until) WHERE is_finalized = FALSE;


-- ══════════════════════════════════════════════════════════════════════
-- POST COOLDOWNS — Anti-spam control
-- ══════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS post_cooldowns (
    id          SERIAL PRIMARY KEY,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    expires_at  TIMESTAMPTZ NOT NULL,
    UNIQUE(product_id)
);

CREATE INDEX IF NOT EXISTS idx_cooldowns_expires
    ON post_cooldowns(expires_at);


-- ══════════════════════════════════════════════════════════════════════
-- SCRAPER RETRY QUEUE — Failed scrapes retry
-- ══════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS scraper_retry_queue (
    id              SERIAL PRIMARY KEY,
    product_id      INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    retry_count     INTEGER DEFAULT 0,
    last_error      TEXT,
    next_retry_at   TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_retry_queue_next
    ON scraper_retry_queue(next_retry_at ASC);
"""


async def setup_database():
    """Create all tables and indexes."""
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    # Use IP fallback if DNS not yet cached locally
    host_to_use = DB_HOST
    if "aivencloud.com" in DB_HOST:
        try:
            import socket
            socket.gethostbyname(DB_HOST)
        except socket.gaierror:
            host_to_use = "168.144.145.235"

    conn_kwargs = {
        "host": host_to_use,
        "port": DB_PORT,
        "database": DB_NAME,
        "user": DB_USER,
        "password": DB_PASSWORD,
    }
    if DB_SSL:
        conn_kwargs["ssl"] = ctx

    conn = await asyncpg.connect(**conn_kwargs)

    try:
        print("Creating tables...")
        await conn.execute(SCHEMA_SQL)
        print("[OK] All tables and indexes created successfully!")

        # Print table counts
        tables = ["products", "daily_prices", "deals", "deal_tracking",
                   "post_cooldowns", "scraper_retry_queue"]
        for table in tables:
            count = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
            print(f"  - {table}: {count} rows")

    finally:
        await conn.close()
        print("Database connection closed.")


if __name__ == "__main__":
    asyncio.run(setup_database())
