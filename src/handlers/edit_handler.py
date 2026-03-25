"""Handler for message edits and deletes."""

import logging
import json
from telegram import Update
from telegram.ext import ContextTypes

from src.models.database import get_db
from src.models import expense as expense_model
from src.models import chat as chat_model
from src.models import user as user_model
from src.models import expense_split as split_model
from src.parsers.expense_parser import ExpenseParser
from src.parsers.payment_parser import PaymentParser
from src.parsers.currency_parser import CurrencyParser
from src.services.expense_service import ExpenseService
from src.services.currency_service import CurrencyService

logger = logging.getLogger(__name__)


async def handle_edited_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle edited messages - automatically update expenses/payments.

    Args:
        update: Telegram update
        context: Bot context
    """
    if not update.edited_message or not update.edited_message.text:
        return

    message = update.edited_message
    chat_id = message.chat_id
    message_id = message.message_id
    user_id = message.from_user.id
    new_text = message.text.strip()

    db_instance = get_db()
    db = await db_instance.get_connection()

    try:
        # Check if this message was an expense
        cursor = await db.execute(
            """
            SELECT id, description, original_amount, original_currency
            FROM expenses
            WHERE chat_id = ? AND message_id = ? AND is_deleted = 0
            """,
            (chat_id, message_id)
        )
        expense_row = await cursor.fetchone()

        if expense_row:
            expense_id, old_description, old_amount, old_currency = expense_row

            # Try to parse the edited text as an expense
            expense_parser = ExpenseParser()
            parsed_expense = expense_parser.parse(new_text)

            if not parsed_expense:
                await message.reply_text(
                    "⚠️ Edit not recognized as valid expense.\n\n"
                    "Use /delete to remove this expense."
                )
                return

            # Log the edit in audit_log
            await db.execute(
                """
                INSERT INTO audit_log (entity_type, entity_id, action, old_value, new_value, changed_by_telegram_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    'expense',
                    expense_id,
                    'edited',
                    json.dumps({'description': old_description, 'amount': old_amount, 'currency': old_currency}),
                    json.dumps({'description': parsed_expense.description, 'amount': parsed_expense.amount, 'currency': parsed_expense.currency}),
                    user_id
                )
            )
            await db.commit()

            # Get chat settings
            chat_settings = await chat_model.get_chat_settings(db, chat_id)
            currency = parsed_expense.currency if parsed_expense.currency != 'DEFAULT' else chat_settings.default_currency

            # Convert to base currency
            currency_service = CurrencyService(db)
            converted_amount, exchange_rate = await currency_service.convert(
                parsed_expense.amount,
                currency,
                chat_settings.default_currency
            )

            # Update expense record
            await db.execute(
                """
                UPDATE expenses
                SET description = ?,
                    amount = ?,
                    original_amount = ?,
                    original_currency = ?,
                    exchange_rate = ?,
                    custom_split = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    parsed_expense.description,
                    converted_amount,
                    parsed_expense.amount,
                    currency,
                    exchange_rate,
                    1 if parsed_expense.split_percentage is not None else 0,
                    expense_id
                )
            )

            # Delete old splits
            await db.execute(
                "DELETE FROM expense_splits WHERE expense_id = ?",
                (expense_id,)
            )

            # Recalculate splits
            expense_service = ExpenseService(db)
            splits = await expense_service._calculate_splits(
                chat_id=chat_id,
                chat_settings=chat_settings,
                payer_telegram_id=user_id,
                total_amount=converted_amount,
                split_percentage=parsed_expense.split_percentage,
                mentioned_users=None,
                bot_id=context.bot.id
            )

            # Create new split records
            split_records = [
                (expense_id, user_id, amount_owed, percentage)
                for user_id, (amount_owed, percentage) in splits.items()
            ]
            await split_model.create_expense_splits_bulk(db, split_records)

            await db.commit()

            # Build confirmation message
            currency_parser = CurrencyParser()
            currency_symbol = currency_parser.get_symbol(chat_settings.default_currency)

            debtor_lines = []
            for debtor_id, (amount_owed, _) in splits.items():
                debtor_name = await user_model.get_user_display_name(db, debtor_id)
                debtor_lines.append(f"{debtor_name} owes {currency_symbol}{amount_owed:,.2f}")

            if debtor_lines:
                debtors_text = ", ".join(debtor_lines)
                confirmation = f"✓ Updated: {currency_parser.get_symbol(currency)}{parsed_expense.amount:,.2f} {parsed_expense.description} ({debtors_text})"
            else:
                confirmation = f"✓ Updated: {currency_parser.get_symbol(currency)}{parsed_expense.amount:,.2f} {parsed_expense.description}"

            await message.reply_text(confirmation)
            logger.info(f"Updated expense {expense_id} in chat {chat_id}")
            return

        # Check if this message was a payment
        cursor = await db.execute(
            """
            SELECT id, original_amount, original_currency
            FROM payments
            WHERE chat_id = ? AND message_id = ? AND is_deleted = 0
            """,
            (chat_id, message_id)
        )
        payment_row = await cursor.fetchone()

        if payment_row:
            payment_id, old_amount, old_currency = payment_row

            # Try to parse as payment
            payment_parser = PaymentParser()
            parsed_payment = payment_parser.parse(new_text)

            if not parsed_payment:
                await message.reply_text(
                    "⚠️ Edit not recognized as valid payment.\n\n"
                    "Use /delete to remove this payment."
                )
                return

            # Log the edit
            await db.execute(
                """
                INSERT INTO audit_log (entity_type, entity_id, action, old_value, new_value, changed_by_telegram_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    'payment',
                    payment_id,
                    'edited',
                    json.dumps({'amount': old_amount, 'currency': old_currency}),
                    json.dumps({'amount': parsed_payment.amount, 'currency': parsed_payment.currency}),
                    user_id
                )
            )

            # Get chat settings
            chat_settings = await chat_model.get_chat_settings(db, chat_id)
            currency = parsed_payment.currency if parsed_payment.currency != 'DEFAULT' else chat_settings.default_currency

            # Convert to base currency
            currency_service = CurrencyService(db)
            converted_amount, exchange_rate = await currency_service.convert(
                parsed_payment.amount,
                currency,
                chat_settings.default_currency
            )

            # Update payment
            await db.execute(
                """
                UPDATE payments
                SET amount = ?,
                    original_amount = ?,
                    original_currency = ?,
                    exchange_rate = ?
                WHERE id = ?
                """,
                (converted_amount, parsed_payment.amount, currency, exchange_rate, payment_id)
            )
            await db.commit()

            # Build confirmation
            currency_parser = CurrencyParser()
            payer_name = await user_model.get_user_display_name(db, user_id)
            currency_symbol = currency_parser.get_symbol(currency)
            confirmation = f"✓ Updated payment: {payer_name} paid {currency_symbol}{parsed_payment.amount:,.2f}"

            await message.reply_text(confirmation)
            logger.info(f"Updated payment {payment_id} in chat {chat_id}")

    except Exception as e:
        logger.error(f"Error handling edited message: {e}", exc_info=True)
        await message.reply_text("Error updating expense/payment. Please try again.")
