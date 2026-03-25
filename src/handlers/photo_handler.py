"""Handler for photo messages (receipt OCR)."""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from src.models.database import get_db
from src.models import user as user_model
from src.services.receipt_service import ReceiptService
from src.parsers.currency_parser import CurrencyParser

logger = logging.getLogger(__name__)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle photo messages for receipt OCR.

    Args:
        update: Telegram update
        context: Bot context
    """
    if not update.message or not update.message.photo:
        return

    message = update.message
    chat_id = message.chat_id
    user = message.from_user

    # Get database connection
    db_instance = get_db()
    db = await db_instance.get_connection()

    try:
        # Send processing message
        processing_msg = await message.reply_text("Processing receipt... 📄")

        # Get the largest photo
        photo = message.photo[-1]
        file_id = photo.file_id

        # Download photo
        photo_file = await context.bot.get_file(file_id)
        photo_bytes = await photo_file.download_as_bytearray()

        # Determine media type from file path
        media_type = "image/jpeg"  # Default
        if photo_file.file_path:
            if photo_file.file_path.endswith('.png'):
                media_type = "image/png"
            elif photo_file.file_path.endswith('.webp'):
                media_type = "image/webp"

        # Extract data from receipt
        receipt_service = ReceiptService(db)
        extracted_data, error_message = await receipt_service.extract_from_image(
            bytes(photo_bytes),
            media_type
        )

        if not extracted_data:
            if error_message:
                await processing_msg.edit_text(error_message)
            else:
                await processing_msg.edit_text(
                    "Sorry, I couldn't extract expense information from this receipt. "
                    "Please try a clearer image or enter the expense manually (e.g., '50 groceries')."
                )
            return

        # Initialize/update user
        await user_model.create_or_update_user(
            db,
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name
        )

        currency_parser = CurrencyParser()

        # Build the list of found expenses
        lines = [f"Found {len(extracted_data)} expense(s):\n"]
        for i, item in enumerate(extracted_data, 1):
            symbol = currency_parser.get_symbol(item.currency)
            amount_str = f"{symbol}{item.amount:,.2f}" if symbol != item.currency else f"{item.currency} {item.amount:,.2f}"
            line = f"{i}. {amount_str} — {item.description}"
            if item.merchant:
                line += f" ({item.merchant})"
            if item.transaction_date:
                line += f" · {item.transaction_date}"
            lines.append(line)

        confirmation_text = "\n".join(lines)

        keyboard = [[
            InlineKeyboardButton(
                f"Add all ({len(extracted_data)})" if len(extracted_data) > 1 else "Add expense",
                callback_data=f"receipt_confirm_{user.id}"
            ),
            InlineKeyboardButton("Cancel", callback_data=f"receipt_cancel_{user.id}")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        confirmation_msg = await processing_msg.edit_text(
            confirmation_text,
            reply_markup=reply_markup
        )

        await receipt_service.store_pending_confirmation(
            chat_id=chat_id,
            user_telegram_id=user.id,
            confirmation_message_id=confirmation_msg.message_id,
            receipt_file_id=file_id,
            extracted_data=extracted_data
        )

        logger.info(f"Receipt processed for user {user.id} in chat {chat_id}: {len(extracted_data)} expense(s)")

    except Exception as e:
        logger.error(f"Error processing receipt: {e}", exc_info=True)
        await message.reply_text(
            "Sorry, I encountered an error processing this receipt. "
            "Please try again or enter the expense manually."
        )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle PDF document uploads for receipt OCR.
    """
    if not update.message or not update.message.document:
        return

    message = update.message
    chat_id = message.chat_id
    user = message.from_user
    doc = message.document

    if doc.mime_type != "application/pdf":
        return

    db_instance = get_db()
    db = await db_instance.get_connection()

    try:
        processing_msg = await message.reply_text("Processing PDF invoice... 📄")

        pdf_file = await context.bot.get_file(doc.file_id)
        pdf_bytes = await pdf_file.download_as_bytearray()

        receipt_service = ReceiptService(db)
        extracted_data, error_message = await receipt_service.extract_from_image(
            bytes(pdf_bytes),
            "application/pdf"
        )

        if not extracted_data:
            await processing_msg.edit_text(
                error_message or
                "Sorry, I couldn't extract expense information from this PDF. "
                "Please try a clearer scan or enter the expense manually (e.g., '50 groceries')."
            )
            return

        await user_model.create_or_update_user(
            db,
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name
        )

        currency_parser = CurrencyParser()

        lines = [f"Found {len(extracted_data)} expense(s):\n"]
        for i, item in enumerate(extracted_data, 1):
            symbol = currency_parser.get_symbol(item.currency)
            amount_str = f"{symbol}{item.amount:,.2f}" if symbol != item.currency else f"{item.currency} {item.amount:,.2f}"
            line = f"{i}. {amount_str} — {item.description}"
            if item.merchant:
                line += f" ({item.merchant})"
            if item.transaction_date:
                line += f" · {item.transaction_date}"
            lines.append(line)

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = [[
            InlineKeyboardButton(
                f"Add all ({len(extracted_data)})" if len(extracted_data) > 1 else "Add expense",
                callback_data=f"receipt_confirm_{user.id}"
            ),
            InlineKeyboardButton("Cancel", callback_data=f"receipt_cancel_{user.id}")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        confirmation_msg = await processing_msg.edit_text(
            "\n".join(lines),
            reply_markup=reply_markup
        )

        await receipt_service.store_pending_confirmation(
            chat_id=chat_id,
            user_telegram_id=user.id,
            confirmation_message_id=confirmation_msg.message_id,
            receipt_file_id=doc.file_id,
            extracted_data=extracted_data
        )

        logger.info(f"PDF processed for user {user.id} in chat {chat_id}: {len(extracted_data)} expense(s)")

    except Exception as e:
        logger.error(f"Error processing PDF: {e}", exc_info=True)
        await message.reply_text(
            "Sorry, I encountered an error processing this PDF. "
            "Please try again or enter the expense manually."
        )
