"""
Database Optimization & Compaction Script for BudgetBy PostgreSQL.
1. Removes redundant duplicate indexes on daily_prices and products.
2. Cleans expired cooldown records.
3. Runs VACUUM FULL ANALYZE to reclaim disk space.
"""
import sys
import os

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asyncio
import asyncpg
from budgetby import config

async def optimize():
    print("=" * 60)
    print("STARTING BUDGETBY DATABASE OPTIMIZATION")
    print("=" * 60)

    conn = await asyncpg.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME
    )

    try:
        pre_size = await conn.fetchval("SELECT pg_size_pretty(pg_database_size(current_database()));")
        pre_bytes = await conn.fetchval("SELECT pg_database_size(current_database());")
        print(f"Initial Database Size: {pre_size} ({pre_bytes:,} bytes)\n")

        # 1. Drop redundant duplicate indexes on daily_prices
        print("1. Cleaning duplicate indexes on daily_prices...")
        await conn.execute("DROP INDEX IF EXISTS idx_daily_prices_product_date;")
        print("   - Dropped redundant index 'idx_daily_prices_product_date' (~27 MB)")
        await conn.execute("DROP INDEX IF EXISTS uq_daily_prices_prod_date;")
        print("   - Dropped redundant index 'uq_daily_prices_prod_date' (~25 MB)")
        print("   [OK] Retained canonical index 'unique_product_date'")

        # 2. Drop redundant duplicate index on products
        print("\n2. Cleaning duplicate indexes on products...")
        await conn.execute("DROP INDEX IF EXISTS uq_products_platform_pid;")
        print("   - Dropped redundant index 'uq_products_platform_pid' (~7 MB)")
        print("   [OK] Retained canonical index 'unique_platform_id'")

        # 3. Clean expired cooldowns
        print("\n3. Cleaning expired post_cooldowns...")
        deleted_cooldowns = await conn.execute("DELETE FROM post_cooldowns WHERE expires_at < NOW();")
        print(f"   [OK] Cleaned expired cooldowns: {deleted_cooldowns}")

        # 4. VACUUM FULL ANALYZE
        print("\n4. Running VACUUM FULL ANALYZE to compact disk blocks...")
        await conn.execute("VACUUM (FULL, ANALYZE);")
        print("   [OK] VACUUM FULL ANALYZE completed successfully.")

        # Post-optimization size
        post_size = await conn.fetchval("SELECT pg_size_pretty(pg_database_size(current_database()));")
        post_bytes = await conn.fetchval("SELECT pg_database_size(current_database());")
        reclaimed_mb = (pre_bytes - post_bytes) / (1024 * 1024)

        print("\n" + "=" * 60)
        print("DATABASE OPTIMIZATION COMPLETE!")
        print(f"   Original Size : {pre_size}")
        print(f"   New Size      : {post_size}")
        print(f"   Disk Reclaimed: {reclaimed_mb:.1f} MB ({(pre_bytes - post_bytes) / pre_bytes * 100:.1f}% reduction)")
        print("=" * 60)

    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(optimize())
