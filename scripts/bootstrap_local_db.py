import asyncio
import logging
from budgetby import database, local_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def bootstrap():
    logger.info("Connecting to Supabase...")
    await database.init_pool()
    
    logger.info("Initializing Local SQLite Database...")
    await local_db.init_db()
    
    logger.info("Fetching all products from Supabase (this may take a minute)...")
    
    # We fetch all active/oos products
    query = """
        SELECT platform, platform_id, product_url, current_price, mrp, priority_tier, status
        FROM products
        WHERE status != 'DORMANT' AND status != 'ARCHIVED';
    """
    
    rows = await database.fetch(query)
    logger.info(f"Fetched {len(rows)} products from Supabase.")
    
    logger.info("Populating local database...")
    for idx, row in enumerate(rows):
        local_db.update_product_locally(
            platform=row['platform'],
            platform_id=row['platform_id'],
            url=row['product_url'],
            current_price=row['current_price'] or 0.0,
            mrp=row['mrp'] or 0.0,
            priority_tier=row['priority_tier'] or 3,
            status=row['status'] or 'ACTIVE'
        )
        if idx % 1000 == 0:
            logger.info(f"Queued {idx} products...")
            
    # Wait for the write queue to finish
    logger.info("Waiting for local DB writes to finish...")
    await local_db._write_queue.join()
    
    logger.info("Bootstrap complete!")
    await local_db.close_db()
    await database.close_pool()

if __name__ == "__main__":
    asyncio.run(bootstrap())
