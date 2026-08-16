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
            from budgetby.features import cooldown
            if hasattr(cooldown, 'cleanup_expired_cooldowns'):
                await cooldown.cleanup_expired_cooldowns()
        except ImportError:
            pass
            
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
        os.system(f"pg_dump -U {config.DB_USER} -h {config.DB_HOST} -p {config.DB_PORT} {config.DB_NAME} | gzip > backup_$(date +%Y%m%d).sql.gz")
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
    """Catchup scan for missed high-priority products."""
    try:
        logger.info("Starting catchup scan...")
        await database.execute("UPDATE products SET next_check = NOW() WHERE priority_tier = 1")
        logger.info("Catchup scan completed.")
    except Exception as e:
        logger.error(f"Error during catchup scan: {e}", exc_info=True)
