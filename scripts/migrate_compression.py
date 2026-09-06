"""
BudgetBy — Price History Compression Migration
Run ONCE to add the columns required for tiered price compression.
Safe to re-run: uses ADD COLUMN IF NOT EXISTS.

Usage:
    python -m scripts.migrate_compression
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from budgetby.config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, DB_SSL
import asyncpg


async def run_migration():
    print("=" * 60)
    print("BudgetBy — Price Compression Migration")
    print("=" * 60)

    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    pool_kwargs = {
        "host": DB_HOST,
        "port": DB_PORT,
        "database": DB_NAME,
        "user": DB_USER,
        "password": DB_PASSWORD,
        "statement_cache_size": 0,
    }
    if DB_SSL and str(DB_SSL).lower() not in ("disable", "false", "none", "0", ""):
        pool_kwargs["ssl"] = ctx

    conn = await asyncpg.connect(**pool_kwargs)

    try:
        # ── 1. Add is_compressed to daily_prices ─────────────────────────
        print("\n[1/4] Adding is_compressed column to daily_prices...")
        await conn.execute("""
            ALTER TABLE daily_prices
            ADD COLUMN IF NOT EXISTS is_compressed BOOLEAN DEFAULT FALSE;
        """)
        print("      [OK] is_compressed column ready")

        # ── 2. Add min_120d to products ───────────────────────────────────
        print("\n[2/4] Adding min_120d column to products...")
        await conn.execute("""
            ALTER TABLE products
            ADD COLUMN IF NOT EXISTS min_120d NUMERIC(10,2);
        """)
        print("      [OK] min_120d column ready")

        # ── 3. Backfill min_120d from min_90d for all existing products ───
        print("\n[3/4] Backfilling min_120d = min_90d for existing products...")
        result = await conn.execute("""
            UPDATE products
            SET min_120d = COALESCE(min_90d, min_60d, min_30d, all_time_low)
            WHERE min_120d IS NULL
              AND COALESCE(min_90d, min_60d, min_30d, all_time_low) IS NOT NULL;
        """)
        print(f"      [OK] Backfilled: {result}")

        # ── 4. Create index on is_compressed for fast partition queries ───
        print("\n[4/4] Creating index on is_compressed flag...")
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_daily_prices_compressed
            ON daily_prices(product_id, date DESC, is_compressed);
        """)
        print("      [OK] Index ready")

        # ── Verify ────────────────────────────────────────────────────────
        print("\n-- Verification ------------------------------------------")

        dp_cols = await conn.fetch("""
            SELECT column_name, data_type, column_default
            FROM information_schema.columns
            WHERE table_name = 'daily_prices'
              AND column_name IN ('is_compressed', 'date', 'min_price', 'close_price')
            ORDER BY column_name;
        """)
        print("daily_prices columns:")
        for c in dp_cols:
            print(f"  {c['column_name']:20s} {c['data_type']:20s} default={c['column_default']}")

        prod_cols = await conn.fetch("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'products'
              AND column_name IN ('min_30d', 'min_60d', 'min_90d', 'min_120d', 'all_time_low')
            ORDER BY column_name;
        """)
        print("products benchmark columns:")
        for c in prod_cols:
            print(f"  {c['column_name']:20s} {c['data_type']}")

        row_count = await conn.fetchval("SELECT COUNT(*) FROM daily_prices")
        compressed_count = await conn.fetchval(
            "SELECT COUNT(*) FROM daily_prices WHERE is_compressed = TRUE"
        )
        print(f"\ndaily_prices total rows:      {row_count:,}")
        print(f"already compressed rows:      {compressed_count:,}")
        print(f"raw rows (uncompressed):      {row_count - compressed_count:,}")

        print("\n[DONE] Migration complete -- system ready for tiered compression.\n")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_migration())
