import aiosqlite
import asyncio
import logging
from typing import List, Dict, Any, Optional
import datetime
from budgetby import config

logger = logging.getLogger(__name__)

import pathlib
DB_PATH = pathlib.Path(__file__).parent.parent / "budgetby_local.db"

_write_queue = asyncio.Queue()
_writer_task = None
_db_conn = None

async def init_db():
    global _db_conn, _writer_task
    
    _db_conn = await aiosqlite.connect(DB_PATH)
    _db_conn.row_factory = aiosqlite.Row
    
    # Enable WAL mode for high concurrency
    await _db_conn.execute("PRAGMA journal_mode=WAL;")
    await _db_conn.execute("PRAGMA synchronous=NORMAL;")
    
    # Create products table (Mirror)
    await _db_conn.execute("""
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
    
    # Create indexes for fast scanning
    await _db_conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_next_check ON products(priority_tier ASC, next_check ASC);
    """)
    
    # Create pending_syncs table (Outbox Queue)
    await _db_conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_syncs (
            platform TEXT,
            platform_id TEXT,
            new_price REAL,
            in_stock BOOLEAN,
            status TEXT,
            PRIMARY KEY (platform, platform_id)
        );
    """)
    
    await _db_conn.commit()
    
    # Start the single writer task
    _writer_task = asyncio.create_task(_writer_loop())
    logger.info("Local SQLite database initialized.")

async def close_db():
    global _writer_task, _db_conn
    if _writer_task:
        _writer_task.cancel()
    if _db_conn:
        await _db_conn.close()

async def _writer_loop():
    """Single background worker that executes writes sequentially to prevent DB locking."""
    global _db_conn
    while True:
        try:
            # Get next query and parameters
            query, params = await _write_queue.get()
            try:
                await _db_conn.execute(query, params)
                await _db_conn.commit()
            except Exception as e:
                logger.error(f"Local DB Write Error: {e} | Query: {query} | Params: {params}")
            finally:
                _write_queue.task_done()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Local DB Writer loop error: {e}")
            await asyncio.sleep(1)

def queue_write(query: str, params: tuple):
    """Enqueue a write operation to be executed by the single writer loop."""
    _write_queue.put_nowait((query, params))

async def get_products_due_for_check(limit: int = 40) -> List[aiosqlite.Row]:
    """Get the next batch of products due for checking."""
    if not _db_conn:
        return []
        
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    # We order by priority_tier ASC first (to catch up on Hot Deals), then next_check
    query = """
        SELECT platform, platform_id, url, current_price, mrp, priority_tier, next_check, status
        FROM products
        WHERE next_check <= ? AND status != 'DORMANT' AND status != 'ARCHIVED'
        ORDER BY priority_tier ASC, next_check ASC
        LIMIT ?
    """
    
    async with _db_conn.execute(query, (now, limit)) as cursor:
        return await cursor.fetchall()

def update_product_check_time(platform: str, platform_id: str, priority_tier: int):
    """Update the local next_check time based on priority tier."""
    interval = config.PRIORITY_INTERVALS.get(priority_tier, 24 * 3600)
    next_check = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=interval)).isoformat()
    
    query = """
        UPDATE products 
        SET priority_tier = ?, next_check = ?
        WHERE platform = ? AND platform_id = ?
    """
    queue_write(query, (priority_tier, next_check, platform, platform_id))

def queue_pending_sync(platform: str, platform_id: str, new_price: float, in_stock: bool, status: str):
    """Add a cold-path price update to the pending_syncs outbox queue. UPSERT prevents zombies."""
    # First, update the local products mirror so it has the new price instantly
    queue_write("""
        UPDATE products 
        SET current_price = ?, status = ?
        WHERE platform = ? AND platform_id = ?
    """, (new_price, status, platform, platform_id))
    
    # Next, add to the sync queue for the 10 PM batch. Upsert logic guarantees only the newest price is sent.
    query = """
        INSERT INTO pending_syncs (platform, platform_id, new_price, in_stock, status)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(platform, platform_id) DO UPDATE SET
            new_price = excluded.new_price,
            in_stock = excluded.in_stock,
            status = excluded.status
    """
    queue_write(query, (platform, platform_id, float(new_price), in_stock, status))

def update_product_locally(platform: str, platform_id: str, url: str, current_price: float, mrp: float, priority_tier: int, status: str):
    """Insert or update a product in the local SQLite mirror (e.g., from the bootstrap or when a new product is found)."""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    query = """
        INSERT INTO products (platform, platform_id, url, current_price, mrp, priority_tier, next_check, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(platform, platform_id) DO UPDATE SET
            url = excluded.url,
            current_price = excluded.current_price,
            mrp = excluded.mrp,
            priority_tier = excluded.priority_tier,
            status = excluded.status
    """
    queue_write(query, (platform, platform_id, url, float(current_price), float(mrp), priority_tier, now, status))

async def get_and_clear_pending_syncs() -> List[aiosqlite.Row]:
    """Used by the 10 PM batch job to fetch all queued updates and empty the table."""
    if not _db_conn:
        return []
        
    # Wait for the write queue to drain so we don't miss anything pending in memory
    await _write_queue.join()
    
    async with _db_conn.execute("SELECT * FROM pending_syncs") as cursor:
        rows = await cursor.fetchall()
        
    # Clear the queue
    if rows:
        await _db_conn.execute("DELETE FROM pending_syncs")
        await _db_conn.commit()
        
    return rows

async def vacuum_db():
    """Defragment the SQLite database to save disk space."""
    if _db_conn:
        await _write_queue.join() # Wait for writes to finish
        logger.info("Vacuuming Local SQLite database...")
        await _db_conn.execute("VACUUM;")
        await _db_conn.commit()
        logger.info("Vacuum complete.")
