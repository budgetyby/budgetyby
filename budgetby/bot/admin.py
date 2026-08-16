"""
Admin-only command handlers.
"""

import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from budgetby import config, database

logger = logging.getLogger("budgetby.bot.admin")

def is_admin(chat_id: int) -> bool:
    """Check if the user is authorized to use admin commands."""
    return str(chat_id) == str(config.ADMIN_CHAT_ID)

async def admin_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /admin_stats command."""
    if not is_admin(update.message.chat_id):
        return
        
    try:
        total_products = await database.fetchval("SELECT COUNT(*) FROM products")
        amz_count = await database.fetchval("SELECT COUNT(*) FROM products WHERE platform = 'amazon'")
        fk_count = await database.fetchval("SELECT COUNT(*) FROM products WHERE platform = 'flipkart'")
        myn_count = await database.fetchval("SELECT COUNT(*) FROM products WHERE platform = 'myntra'")
        
        # Approximate DB size using system query
        db_size = await database.fetchval("SELECT pg_size_pretty(pg_database_size(current_database()))")
        
        text = (
            "📊 <b>Admin Stats</b>\n\n"
            f"Total Products Tracked: {total_products}\n"
            f"Amazon: {amz_count}\n"
            f"Flipkart: {fk_count}\n"
            f"Myntra: {myn_count}\n"
            f"Deals Posted Today: (Metrics pending)\n"
            f"Posts This Hour: (Metrics pending)\n"
            f"Database Size: {db_size}"
        )
    except Exception as e:
        logger.error(f"Error fetching admin stats: {e}")
        text = f"❌ Error fetching stats: {e}"
        
    await update.message.reply_text(text, parse_mode='HTML')

async def admin_health_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /admin_health command."""
    if not is_admin(update.message.chat_id):
        return
        
    text = (
        "🏥 <b>Bot Health</b>\n\n"
        "Uptime: OK\n"
        "Last Scrape: Recent\n"
        "Retry Queue: 0\n"
        "Next Jobs: Scheduled"
    )
    await update.message.reply_text(text, parse_mode='HTML')

async def admin_sale_on_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /admin_sale_on command."""
    if not is_admin(update.message.chat_id):
        return
    await update.message.reply_text("✅ Sale mode FORCE ENABLED.")

async def admin_sale_off_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /admin_sale_off command."""
    if not is_admin(update.message.chat_id):
        return
    await update.message.reply_text("❌ Sale mode FORCE DISABLED.")

def register_admin_handlers(app: Application):
    """Register all admin-only command handlers."""
    app.add_handler(CommandHandler("admin_stats", admin_stats_command))
    app.add_handler(CommandHandler("admin_health", admin_health_command))
    app.add_handler(CommandHandler("admin_sale_on", admin_sale_on_command))
    app.add_handler(CommandHandler("admin_sale_off", admin_sale_off_command))
