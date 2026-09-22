"""
BudgetBy — Local Database Incremental Sync & Backup Daemon.
Synchronizes budgetby_local.db with Supabase every 5 minutes.
Fetches newly discovered products and updated prices.
Keeps a local backup copy for testing and disaster recovery.
"""

import os
import sys
import time
import asyncio
import logging
import sqlite3
import datetime
from pathlib import Path

# Ensure project root is in python path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from budgetby import database, config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [DBSync] %(levelname)s - %(message)s"
)
logger = logging.getLogger("sync_local_mirror")

DB_PATH = ROOT_DIR / "budgetby_local.db"
BACKUP_DIR = ROOT_DIR / "backups"
INTERVAL_SECONDS = 300  # 5 minutes


def init_local_schema():
    """Ensures local SQLite table and indexes exist."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL;")
    cur.execute("PRAGMA synchronous=NORMAL;")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            platform TEXT,
            platform_id TEXT,
            url TEXT,
            current_price REAL,
            mrp REAL,
            priority_tier INTEGER DEFAULT 3,
            next_check TIMESTAMP,
            status TEXT DEFAULT 'ACTIVE',
            PRIMARY KEY (platform, platform_id)
        );
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_next_check ON products(priority_tier ASC, next_check ASC);
    """)
    conn.commit()
    conn.close()


def create_local_backup():
    """Creates a safe SQLite backup of budgetby_local.db."""
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup_file = BACKUP_DIR / "budgetby_local_backup.db"
        
        src_conn = sqlite3.connect(DB_PATH)
        dst_conn = sqlite3.connect(backup_file)
        with dst_conn:
            src_conn.backup(dst_conn)
        dst_conn.close()
        src_conn.close()
        logger.info(f"💾 Local backup snapshot created: {backup_file.name}")
    except Exception as e:
        logger.warning(f"Could not create backup snapshot: {e}")


async def sync_incremental():
    """Fetches new and updated products from Supabase and applies to local SQLite."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # 1. Get total local count
    cur.execute("SELECT COUNT(*) FROM products;")
    local_count = cur.fetchone()[0]

    # 2. Get the latest updated_at or created_at timestamp from local db
    # If empty or new, do initial bootstrap
    if local_count == 0:
        logger.info("Local database empty. Performing initial bootstrap...")
        query = """
            SELECT platform, platform_id, product_url, current_price, mrp, priority_tier, status, updated_at
            FROM products
            WHERE status != 'DORMANT' AND status != 'ARCHIVED';
        """
        rows = await database.fetch(query)
    else:
        # Fetch products updated in the last 15 minutes (with safe overlap for the 5-minute interval)
        fifteen_mins_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=15)
        query = """
            SELECT platform, platform_id, product_url, current_price, mrp, priority_tier, status, updated_at
            FROM products
            WHERE (updated_at >= $1 OR created_at >= $1)
              AND status != 'DORMANT' AND status != 'ARCHIVED';
        """
        rows = await database.fetch(query, fifteen_mins_ago)

    if not rows:
        logger.info(f"✅ Local database is up to date ({local_count} products). 0 changes in Supabase.")
        conn.close()
        return 0

    # 3. Batch UPSERT into local SQLite matching local_db schema
    upsert_sql = """
        INSERT INTO products (platform, platform_id, url, current_price, mrp, priority_tier, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(platform, platform_id) DO UPDATE SET
            url = excluded.url,
            current_price = excluded.current_price,
            mrp = excluded.mrp,
            priority_tier = excluded.priority_tier,
            status = excluded.status;
    """

    records = [
        (
            r["platform"],
            r["platform_id"],
            r["product_url"],
            float(r["current_price"]) if r["current_price"] is not None else 0.0,
            float(r["mrp"]) if r["mrp"] is not None else 0.0,
            int(r["priority_tier"]) if r["priority_tier"] is not None else 3,
            r["status"] or "ACTIVE"
        )
        for r in rows
    ]

    cur.executemany(upsert_sql, records)
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM products;")
    new_local_count = cur.fetchone()[0]
    conn.close()

    logger.info(f"🔄 Synced {len(rows)} products from Supabase. Total local products: {new_local_count}")
    return len(rows)


async def run_sync_loop():
    """Main loop: runs every 5 minutes."""
    logger.info("🚀 Starting BudgetBy 5-Minute Local DB Sync & Backup Service...")
    init_local_schema()
    
    await database.init_pool()

    while True:
        try:
            synced = await sync_incremental()
            if synced > 0:
                create_local_backup()
        except Exception as e:
            logger.error(f"Error during incremental sync: {e}", exc_info=True)
            
        logger.info(f"⏳ Sleeping {INTERVAL_SECONDS}s until next sync...")
        await asyncio.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        async def run_once():
            init_local_schema()
            await database.init_pool()
            await sync_incremental()
            create_local_backup()
            await database.close_pool()
        asyncio.run(run_once())
    else:
        try:
            asyncio.run(run_sync_loop())
        except (KeyboardInterrupt, SystemExit):
            logger.info("Local DB Sync service stopped.")
