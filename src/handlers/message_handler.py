"""Handler for text messages (expenses and payments)."""

import logging
import re
from telegram import Update
from telegram.ext import ContextTypes

from src.models.database import get_db
from src.models import chat as chat_model
from src.models import user as user_model
from src.models import payment as payment_model
from src.parsers.expense_parser import ExpenseParser
from src.parsers.payment_parser import PaymentParser
from src.parsers.owe_parser import OweParser
from src.parsers.currency_parser import CurrencyParser
from src.services.expense_service import ExpenseService
from src.services.currency_service import CurrencyService
from src.config import settings

logger = logging.getLogger(__name__)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle text messages for expense/payment tracking.

    Args:
        update: Telegram update
        context: Bot context
    """
    if not update.message or not update.message.text:
        return

    message = update.message
    chat_id = message.chat_id
    message_id = message.message_id
    user = message.from_user
    text = message.text.strip()

    # Get database connection
    db_instance = get_db()
    db = await db_instance.get_connection()

    try:
        # Initialize/update user
        await user_model.create_or_update_user(
            db,
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name
        )

        # Add user to chat
        await user_model.add_user_to_chat(db, chat_id, user.id)

        # Ensure chat settings exist
        await chat_model.get_or_create_chat_settings(db, chat_id)

        # Try to parse as owe message first
        owe_parser = OweParser()
        parsed_owe = owe_parser.parse(text)

        if parsed_owe:
            await _handle_owe(update, context, db, parsed_owe)
            return
        elif text.lower().startswith('owe '):
            await message.reply_text(
                "Please include a description. Examples:\n"
                "• owe 15 taxi\n"
                "• owe @alice 50 dinner\n"
                "• owe 22 groceries, 100%"
            )
            return

        # Try to parse as payment
        payment_parser = PaymentParser()
        parsed_payment = payment_parser.parse(text)

        if parsed_payment:
            await _handle_payment(update, context, db, parsed_payment)
            return

        # Try to parse as expense
        expense_parser = ExpenseParser()
        parsed_expense = expense_parser.parse(text)

        if parsed_expense:
            logger.info(f"Parsed expense: {parsed_expense}")
            await _handle_expense(update, context, db, parsed_expense)
            return
        elif re.match(r'^\d+(?:\.\d+)?$', text):
            # Bare number with no description
            await message.reply_text(
                "Please include a description, e.g. `15 taxi` or `50 dinner`.",
                parse_mode='Markdown'
            )

        logger.debug(f"Message not recognized as expense or payment: {text}")

    except Exception as e:
        logger.error(f"Error handling message: {e}", exc_info=True)
        await message.reply_text(
            "Sorry, something went wrong processing your message. Please try again."
        )


async def _handle_expense(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    db,
    parsed_expense
) -> None:
    """Handle parsed expense."""
    message = update.message
    chat_id = message.chat_id
    user_id = message.from_user.id

    logger.info(f"Handling expense for user {user_id} in chat {chat_id}: {parsed_expense}")

    try:
        # Check chat size before processing
        member_count = await context.bot.get_chat_member_count(chat_id)
        human_count = member_count - 1  # Exclude bot

        if human_count > settings.MAX_CHAT_MEMBERS:
            await message.reply_text(
                f"⚠️ This chat has {human_count} members. Splitbot only works with groups of "
                f"{settings.MAX_CHAT_MEMBERS} people or less. Please use a smaller group chat."
            )
            return

        # Sync all chat members from Telegram before creating expense
        await user_model.sync_chat_members_from_telegram(db, chat_id, context.bot, exclude_bot=True)

        # Get chat settings for currency symbol
        chat_settings = await chat_model.get_chat_settings(db, chat_id)
        currency_parser = CurrencyParser()
        currency_symbol = currency_parser.get_symbol(chat_settings.default_currency)

        # Extract mentioned users if any
        mentioned_users = None
        if parsed_expense.mentioned_users:
            resolved_ids = []
            unresolved = []
            for username in parsed_expense.mentioned_users:
                user = await user_model.get_user_by_username(db, username)
                if user:
                    resolved_ids.append(user.telegram_id)
                else:
                    unresolved.append(f"@{username}")
            if unresolved:
                await message.reply_text(
                    f"Could not find {', '.join(unresolved)} — they may need to send a message in this chat first."
                )
                return
            mentioned_users = resolved_ids or None

        # Create expense
        expense_service = ExpenseService(db)
        expense_id, splits = await expense_service.create_expense(
            chat_id=chat_id,
            message_id=message.message_id,
            payer_telegram_id=user_id,
            description=parsed_expense.description,
            amount=parsed_expense.amount,
            currency=parsed_expense.currency,
            split_percentage=parsed_expense.split_percentage,
            mentioned_users=mentioned_users,
            bot_id=context.bot.id
        )

        # Build confirmation message
        original_currency = parsed_expense.currency if parsed_expense.currency != 'DEFAULT' else chat_settings.default_currency
        original_amount = f"{currency_parser.get_symbol(original_currency)}{parsed_expense.amount:,.2f}"

        # Build debtor list
        debtor_lines = []
        for debtor_id, amount_owed in splits.items():
            debtor_name = await user_model.get_user_display_name(db, debtor_id)
            debtor_lines.append(f"{debtor_name} owes {currency_symbol}{amount_owed:,.2f}")

        if debtor_lines:
            debtors_text = ", ".join(debtor_lines)
            confirmation = f"✓ Tracked: {original_amount} {parsed_expense.description} ({debtors_text})"
        else:
            confirmation = (
                f"✓ Tracked: {original_amount} {parsed_expense.description}\n"
                "⚠️ No other members found to split with. Ask everyone to send a message in this chat so the bot can see them."
            )

        await message.reply_text(confirmation)
        logger.info(f"Created expense {expense_id} in chat {chat_id}")

    except Exception as e:
        logger.error(f"Error creating expense: {e}", exc_info=True)
        await message.reply_text(
            "Couldn't track that expense. Please check your format. Examples:\n"
            "• 15 taxi\n"
            "• 50 usd boots\n"
            "• €30 dinner\n"
            "• 50 boots, 100%"
        )


async def _handle_owe(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    db,
    parsed_owe
) -> None:
    """Handle 'owe @user amount description' — record expense paid by another user."""
    message = update.message
    chat_id = message.chat_id
    sender_id = message.from_user.id

    try:
        # Resolve payer: @mention or infer from 2-person chat
        if parsed_owe.username:
            payer_user = await user_model.get_user_by_username(db, parsed_owe.username)
            if not payer_user:
                await message.reply_text(
                    f"Unknown user @{parsed_owe.username}. "
                    "Make sure they've sent a message in this chat first."
                )
                return
            payer_id = payer_user.telegram_id
        else:
            # Infer other person in a 2-person chat
            all_members = await user_model.get_chat_members(db, chat_id)
            others = [uid for uid in all_members if uid != sender_id]
            if len(others) != 1:
                await message.reply_text(
                    "Please specify who you owe: `owe @username 14 taxi`\n"
                    "(Auto-detection only works in 2-person chats.)",
                    parse_mode='Markdown'
                )
                return
            payer_id = others[0]

        # Get chat settings
        chat_settings = await chat_model.get_chat_settings(db, chat_id)
        currency_parser = CurrencyParser()

        # Create expense: payer is the resolved user.
        # If split_percentage is set, force sender as the only debtor at that %.
        # Otherwise let the default ratio apply (same as regular expenses).
        expense_service = ExpenseService(db)
        expense_id, splits = await expense_service.create_expense(
            chat_id=chat_id,
            message_id=message.message_id,
            payer_telegram_id=payer_id,
            description=parsed_owe.description,
            amount=parsed_owe.amount,
            currency=parsed_owe.currency,
            split_percentage=parsed_owe.split_percentage,
            mentioned_users=[sender_id] if parsed_owe.split_percentage is not None else None,
            bot_id=context.bot.id
        )

        # Build confirmation
        original_currency = parsed_owe.currency if parsed_owe.currency != 'DEFAULT' else chat_settings.default_currency
        currency_symbol = currency_parser.get_symbol(original_currency)
        amount_str = f"{currency_symbol}{parsed_owe.amount:,.2f}"
        payer_name = await user_model.get_user_display_name(db, payer_id)
        owed_amount = splits.get(sender_id, parsed_owe.amount)
        base_symbol = currency_parser.get_symbol(chat_settings.default_currency)
        confirmation = (
            f"✓ Tracked: {amount_str} {parsed_owe.description} "
            f"(you owe {payer_name} {base_symbol}{owed_amount:,.2f})"
        )

        await message.reply_text(confirmation)
        logger.info(f"Created owe expense {expense_id} in chat {chat_id}: sender {sender_id} owes {payer_id}")

    except Exception as e:
        logger.error(f"Error creating owe expense: {e}", exc_info=True)
        await message.reply_text(
            "Couldn't record that. Please check your format. Examples:\n"
            "• owe @username 15 taxi\n"
            "• owe @username 50 usd dinner\n"
            "• owe @username $30 groceries"
        )


async def _handle_payment(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    db,
    parsed_payment
) -> None:
    """Handle parsed payment."""
    message = update.message
    chat_id = message.chat_id
    user_id = message.from_user.id

    try:
        # Get chat settings
        chat_settings = await chat_model.get_chat_settings(db, chat_id)
        currency_parser = CurrencyParser()

        # Resolve currency
        currency = parsed_payment.currency
        if currency == 'DEFAULT':
            currency = chat_settings.default_currency

        # Convert to base currency
        currency_service = CurrencyService(db)
        converted_amount, exchange_rate = await currency_service.convert(
            parsed_payment.amount,
            currency,
            chat_settings.default_currency
        )

        # Create payment record
        payment_id = await payment_model.create_payment(
            db,
            chat_id=chat_id,
            message_id=message.message_id,
            payer_telegram_id=user_id,
            amount=converted_amount,
            original_amount=parsed_payment.amount,
            original_currency=currency,
            base_currency=chat_settings.default_currency,
            exchange_rate=exchange_rate
        )

        # Build confirmation
        payer_name = await user_model.get_user_display_name(db, user_id)
        currency_symbol = currency_parser.get_symbol(currency)
        confirmation = f"✓ Payment recorded: {payer_name} paid {currency_symbol}{parsed_payment.amount:,.2f}"

        await message.reply_text(confirmation)
        logger.info(f"Created payment {payment_id} in chat {chat_id}")

    except Exception as e:
        logger.error(f"Error creating payment: {e}", exc_info=True)
        await message.reply_text(
            "Couldn't record that payment. Please check your format. Examples:\n"
            "• paid 100\n"
            "• paid 50 usd\n"
            "• paid €30"
        )


async def _handle_receipt_confirmation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    db
) -> None:
    """Handle receipt confirmation response."""
    from src.services.receipt_service import ReceiptService

    message = update.message
    chat_id = message.chat_id
    user_id = message.from_user.id

    try:
        receipt_service = ReceiptService(db)
        pending = await receipt_service.get_pending_confirmation(chat_id, user_id)

        if not pending:
            # No pending confirmation
            return

        # Create expense from pending confirmation
        expense_service = ExpenseService(db)
        expense_id, splits = await expense_service.create_expense(
            chat_id=chat_id,
            message_id=message.message_id,
            payer_telegram_id=user_id,
            description=pending['description'],
            amount=pending['amount'],
            currency=pending['currency'],
            merchant_name=pending['merchant'],
            transaction_date=pending['transaction_date'],
            receipt_image_file_id=pending['receipt_file_id'],
            is_from_receipt=True,
            bot_id=context.bot.id
        )

        # Delete pending confirmation
        await receipt_service.delete_pending_confirmation(pending['id'])

        # Send confirmation
        chat_settings = await chat_model.get_chat_settings(db, chat_id)
        currency_parser = CurrencyParser()
        currency_symbol = currency_parser.get_symbol(chat_settings.default_currency)

        # Build debtor list
        debtor_lines = []
        for debtor_id, amount_owed in splits.items():
            debtor_name = await user_model.get_user_display_name(db, debtor_id)
            debtor_lines.append(f"{debtor_name} owes {currency_symbol}{amount_owed:,.2f}")

        if debtor_lines:
            debtors_text = ", ".join(debtor_lines)
            confirmation = f"✓ Receipt expense created: {pending['description']} ({debtors_text})"
        else:
            confirmation = f"✓ Receipt expense created: {pending['description']}"

        await message.reply_text(confirmation)
        logger.info(f"Created expense {expense_id} from receipt confirmation")

    except Exception as e:
        logger.error(f"Error confirming receipt: {e}", exc_info=True)


async def handle_new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sync new members to the database when they join the chat."""
    if not update.message:
        return

    chat_id = update.message.chat_id
    db_instance = get_db()
    db = await db_instance.get_connection()

    for new_member in update.message.new_chat_members:
        if new_member.is_bot:
            continue
        await user_model.create_or_update_user(
            db,
            telegram_id=new_member.id,
            username=new_member.username,
            first_name=new_member.first_name,
            last_name=new_member.last_name
        )
        await user_model.add_user_to_chat(db, chat_id, new_member.id)
        logger.info(f"Synced new member {new_member.id} (@{new_member.username}) to chat {chat_id}")
        await message.reply_text("Error creating expense from receipt. Please try again.")
