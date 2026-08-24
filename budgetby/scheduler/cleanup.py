"""
Cleanup tasks for the scheduler.
"""
import logging
import asyncio
import os
from budgetby import database, config

logger = logging.getLogger("budgetby.scheduler.cleanup")

async def daily_cleanup():
    """Orchestrates all daily maintenance."""
    try:
        logger.info("Starting daily cleanup...")
        await database.cleanup_old_daily_prices()
        await database.refresh_30d_benchmarks()
        await database.finalize_expired_tracking()
        
        try:
            from budgetby.engine.cooldown import cleanup_expired_cooldowns
            await cleanup_expired_cooldowns()
        except Exception as e:
            logger.warning(f"Could not cleanup expired cooldowns: {e}")
            
        # Archive OOS > DORMANT_THRESHOLD_DAYS
        await database.execute(f"UPDATE products SET status = '{config.STATUS_DORMANT}' WHERE status = '{config.STATUS_TEMP_OOS}' AND last_checked < NOW() - INTERVAL '{config.DORMANT_THRESHOLD_DAYS} days'")
        
        # Delete OOS > DELETE_THRESHOLD_DAYS
        await database.execute(f"DELETE FROM products WHERE status IN ('{config.STATUS_TEMP_OOS}', '{config.STATUS_DORMANT}') AND last_checked < NOW() - INTERVAL '{config.DELETE_THRESHOLD_DAYS} days'")
        
        logger.info("Daily cleanup completed.")
    except Exception as e:
        logger.error(f"Error during daily cleanup: {e}", exc_info=True)

async def run_backup():
    """Runs pg_dump and compresses output."""
    try:
        logger.info("Starting database backup...")
        cmd = f"pg_dump -U {config.DB_USER} -h {config.DB_HOST} -p {config.DB_PORT} {config.DB_NAME} | gzip > backup_$(date +%Y%m%d).sql.gz"
        process = await asyncio.create_subprocess_shell(cmd)
        await process.communicate()
        logger.info("Database backup completed.")
    except Exception as e:
        logger.error(f"Error during backup: {e}", exc_info=True)

async def monthly_maintenance():
    """Monthly benchmark shift."""
    try:
        logger.info("Starting monthly maintenance...")
        await database.monthly_benchmark_shift()
        logger.info("Monthly maintenance completed.")
    except Exception as e:
        logger.error(f"Error during monthly maintenance: {e}", exc_info=True)

async def catchup_scan():
    """Catchup scan for missed high-priority products & automated title sanitization."""
    try:
        logger.info("Starting catchup scan and title sanitization...")
        await database.execute("UPDATE products SET next_check = NOW() WHERE priority_tier = 1 OR current_price IS NULL")
        
        # Autonomous title sanitizer for all platforms
        rows = await database.fetch("""
            SELECT id, product_url, platform 
            FROM products 
            WHERE title = 'Product' OR title = 'Flipkart Product' OR length(title) < 5
            LIMIT 500;
        """)
        import re
        for r in rows:
            p_url = r["product_url"] or ""
            slug = re.sub(r'https?://[^/]+/', '', p_url).split('/p/')[0].split('?')[0].lstrip('/').replace('-', ' ').title()
            if len(slug) >= 4:
                await database.execute("UPDATE products SET title = $2 WHERE id = $1", r["id"], slug)
        
        logger.info("Catchup scan completed.")
    except Exception as e:
        logger.error(f"Error during catchup scan: {e}")
