"""
BudgetBy Main Entry Point.
"""
import asyncio
import logging
import os
import signal
import sys
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

async def handle_http(reader, writer):
    """Simple HTTP healthcheck handler for cloud platforms like Render."""
    try:
        data = await reader.read(1024)
        response = "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 22\r\n\r\nBudgetBy Bot is Active\n"
        writer.write(response.encode())
        await writer.drain()
    except Exception:
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def main():
    logger.info("Starting BudgetBy Bot...")
    
    # Start HTTP server for Render/Cloud healthcheck
    port = int(os.getenv("PORT", "8080"))
    try:
        server = await asyncio.start_server(handle_http, "0.0.0.0", port)
        logger.info(f"Cloud healthcheck HTTP server listening on port {port}")
    except Exception as e:
        logger.warning(f"Could not start HTTP server on port {port}: {e}")
        server = None

    await database.init_pool()
    
    if config.TELEGRAM_BOT_TOKEN:
        application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
        register_handlers(application)
        register_admin_handlers(application)
        
        from budgetby.scheduler import scheduler as sched_module
        if application:
            sched_module.set_bot(application.bot)
            
        logger.info("Telegram application configured with all handlers.")
    else:
        logger.warning("No TELEGRAM_BOT_TOKEN provided. Telegram features will be disabled.")
        application = None

    await cleanup.catchup_scan()
    
    try:
        result = await database.execute("DELETE FROM products WHERE platform = 'flipkart' AND (title = 'Product' OR length(title) < 5);")
        logger.info(f"Cleaned up bad Flipkart titles: {result}")
    except Exception as e:
        logger.warning(f"Could not clean bad titles: {e}")
    
    # Auto-seed all platforms in continuous bootstrap loop until 75,000 products reached
    async def auto_seed_if_needed():
        try:
            from budgetby.discovery.seeder import ProductSeeder
            seeder = ProductSeeder()
            await seeder.run_bootstrap_until_target(target_count=75000)
        except Exception as e:
            logger.error(f"Error in auto_seed_if_needed: {e}")

    asyncio.create_task(auto_seed_if_needed())

    scheduler.start_scheduler()
    
    stop_event = asyncio.Event()
    
    def handle_sigterm():
        logger.info("Received termination signal.")
        stop_event.set()

    if sys.platform != 'win32':
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, handle_sigterm)
        loop.add_signal_handler(signal.SIGTERM, handle_sigterm)
    
    if application:
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        logger.info("Bot is polling.")
    
    try:
        if sys.platform == 'win32':
            while not stop_event.is_set():
                await asyncio.sleep(1)
        else:
            await stop_event.wait()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received.")
    finally:
        logger.info("Shutting down...")
        if application:
            await application.updater.stop()
            await application.stop()
            await application.shutdown()
        scheduler.stop_scheduler()
        await database.close_pool()
        logger.info("Shutdown complete.")

if __name__ == '__main__':
    asyncio.run(main())
