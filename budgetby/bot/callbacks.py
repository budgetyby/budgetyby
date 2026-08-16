"""
Callback query handlers for inline buttons.
"""

import logging
from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

logger = logging.getLogger("budgetby.bot.callbacks")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Basic handler for inline keyboard button presses."""
    query = update.callback_query
    await query.answer("Action acknowledged!")

def register_callbacks(app: Application):
    """Register all callback query handlers."""
    app.add_handler(CallbackQueryHandler(button_callback))
