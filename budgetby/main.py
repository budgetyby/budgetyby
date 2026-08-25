"""
BudgetBy Main Entry Point.
"""
import asyncio
import logging
import os
import signal
import sys
import uvicorn
from dotenv import load_dotenv
from telegram.ext import Application
from budgetby import database, config
from budgetby.bot.handlers import register_handlers
from budgetby.bot.admin import register_admin_handlers
from budgetby.scheduler import scheduler, cleanup

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("budgetby.main")


async def main():
    logger.info("Starting BudgetBy Bot...")
    
    # 1. Initialize Database Pool
    await database.init_pool()

    # 2. Start Local Web Dashboard on http://localhost:5000
    try:
        from budgetby.dashboard.app import app as dashboard_app
        dash_port = int(os.getenv("DASHBOARD_PORT", "5000"))
        config_server = uvicorn.Config(
            dashboard_app,
            host="127.0.0.1",
            port=dash_port,
            log_level="warning",
            access_log=False
        )
        dash_server = uvicorn.Server(config_server)
        asyncio.create_task(dash_server.serve())
        logger.info(f"🚀 Local Web Dashboard running on http://localhost:{dash_port}")
    except Exception as e:
        logger.warning(f"Could not start dashboard on port 5000: {e}")
    
    # 3. Configure Telegram Bot with robust HTTP connection pool & timeout handling
    if config.TELEGRAM_BOT_TOKEN:
        from telegram.request import HTTPXRequest
        from telegram.error import NetworkError, TimedOut

        request_config = HTTPXRequest(
            connection_pool_size=20,
            read_timeout=30.0,
            write_timeout=20.0,
            connect_timeout=15.0,
            pool_timeout=20.0
        )

        application = (
            Application.builder()
            .token(config.TELEGRAM_BOT_TOKEN)
            .request(request_config)
            .get_updates_request(request_config)
            .build()
        )

        async def handle_telegram_polling_error(update, context):
            err = context.error
            if isinstance(err, (NetworkError, TimedOut)) or "httpx" in str(err).lower() or "readerror" in str(err).lower():
                logger.debug(f"Transient Telegram polling network blip (automatically recovered): {err}")
            else:
                logger.error(f"Telegram Bot Exception: {err}", exc_info=err)

        application.add_error_handler(handle_telegram_polling_error)
        register_handlers(application)
        register_admin_handlers(application)
        
        from budgetby.scheduler import scheduler as sched_module
        if application:
            sched_module.set_bot(application.bot)
            
        logger.info("Telegram application configured with all handlers.")
    else:
        application = None
        logger.warning("TELEGRAM_BOT_TOKEN not found in environment!")

    # 4. Catchup scan & title cleanup
    await cleanup.catchup_scan()
    await database.sync_daily_price_baselines()
    try:
        result = await database.execute("DELETE FROM products WHERE platform = 'flipkart' AND (title = 'Product' OR length(title) < 5);")
        logger.info(f"Cleaned up bad Flipkart titles: {result}")
    except Exception as e:
        logger.warning(f"Could not clean bad titles: {e}")
    
    # 5. Start Scheduler
    scheduler.start_scheduler()

    # 6. Start Seeder Background Workers
    try:
        from budgetby.discovery.seeder import ProductSeeder
        logger.info("Starting bootstrap seeder workers...")
        seeder = ProductSeeder()
        asyncio.create_task(seeder.run_bootstrap_until_target())
    except Exception as e:
        logger.error(f"Error starting bootstrap workers: {e}")

    # 7. Start Real-Time Private Channel Listener
    try:
        from budgetby.ingest.telegram_listener import start_telegram_listener
        asyncio.create_task(start_telegram_listener())
    except Exception as e:
        logger.warning(f"Could not start telegram private listener: {e}")

    # 8. Run Bot Polling
    if application:
        try:
            await application.initialize()
            await application.start()
            await application.updater.start_polling(
                drop_pending_updates=True,
                poll_interval=1.0,
                timeout=20,
                bootstrap_retries=-1
            )
            logger.info("Bot is polling.")
            
            # Keep main task alive
            stop_event = asyncio.Event()
            await stop_event.wait()
            
        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutting down bot gracefully...")
        finally:
            scheduler.stop_scheduler()
            if application.updater:
                await application.updater.stop()
            await application.stop()
            await application.shutdown()
            await database.close_pool()
            logger.info("Bot shutdown complete.")
    else:
        try:
            while True:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            scheduler.stop_scheduler()
            await database.close_pool()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
