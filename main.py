"""
Splitbot - Telegram Expense Tracking Bot

Main entry point for the bot application.
"""

import asyncio
import logging
import sys
from pathlib import Path

from telegram.ext import Application

from src.config import settings
from src.models import Database


# Setup logging
def setup_logging():
    """Configure logging for the application."""
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    # Create logs directory if it doesn't exist
    if settings.LOG_FILE:
        log_file = Path(settings.LOG_FILE)
        log_file.parent.mkdir(parents=True, exist_ok=True)

        logging.basicConfig(
            format=log_format,
            level=getattr(logging, settings.LOG_LEVEL),
            handlers=[
                logging.FileHandler(settings.LOG_FILE),
                logging.StreamHandler(sys.stdout)
            ]
        )
    else:
        logging.basicConfig(
            format=log_format,
            level=getattr(logging, settings.LOG_LEVEL)
        )


logger = logging.getLogger(__name__)


async def initialize_database():
    """Initialize the database."""
    db = Database(settings.DATABASE_PATH)
    await db.initialize()
    logger.info(f"Database initialized at {settings.DATABASE_PATH}")


def main():
    """Initialize and run the bot."""
    # Setup logging
    setup_logging()
    logger.info("Starting Splitbot...")

    # Initialize database synchronously
    import asyncio
    asyncio.run(initialize_database())

    # Create bot application
    application = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

    # Import handlers
    from telegram.ext import CommandHandler, MessageHandler, CallbackQueryHandler, filters
    from src.handlers import command_handler, message_handler, photo_handler, edit_handler

    # Register command handlers
    application.add_handler(CommandHandler("start", command_handler.start))
    application.add_handler(CommandHandler("help", command_handler.help_command))
    application.add_handler(CommandHandler("balance", command_handler.balance))
    application.add_handler(CommandHandler("history", command_handler.history))
    application.add_handler(CommandHandler("settings", command_handler.settings_command))
    application.add_handler(CommandHandler("setcurrency", command_handler.set_currency))
    application.add_handler(CommandHandler("setratio", command_handler.set_ratio))
    application.add_handler(CommandHandler("delete", command_handler.delete_expense))
    application.add_handler(CommandHandler("clear", command_handler.clear_history))

    # Register callback query handlers for inline buttons
    application.add_handler(CallbackQueryHandler(command_handler.handle_clear_callback, pattern=r"^clear_(confirm|cancel)_-?\d+$"))
    application.add_handler(CallbackQueryHandler(command_handler.handle_delete_callback, pattern=r"^delete_(confirm|cancel)_\d+$"))
    application.add_handler(CallbackQueryHandler(command_handler.handle_receipt_callback, pattern=r"^receipt_(confirm|cancel)_\d+$"))
    application.add_handler(CallbackQueryHandler(command_handler.handle_history_callback, pattern=r"^history_page_-?\d+_\d+$"))

    # Register edited message handler (MUST come before regular message handler)
    application.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE & filters.TEXT, edit_handler.handle_edited_message))

    # Sync members when someone joins the chat
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, message_handler.handle_new_chat_members))

    # Register photo handler (for receipts)
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler.handle_photo))

    # Register PDF document handler (for invoices)
    application.add_handler(MessageHandler(filters.Document.PDF, photo_handler.handle_document))

    # Register text message handler (for expenses and payments)
    # Explicitly exclude edited messages to prevent double-processing
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.UpdateType.EDITED_MESSAGE, message_handler.handle_message))

    # Start the bot
    logger.info("Bot starting polling...")
    logger.info("Handlers registered: commands, messages, photos, edits, callbacks")

    # Run polling (this manages its own event loop)
    application.run_polling(allowed_updates=["message", "edited_message", "callback_query", "chat_member"])


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
