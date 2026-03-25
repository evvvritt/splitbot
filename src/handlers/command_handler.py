"""Handler for bot commands."""

import logging
from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import json
from src.models.database import get_db
from src.models import chat as chat_model
from src.models import user as user_model
from src.models import expense as expense_model
from src.models import payment as payment_model
from src.services.debt_service import DebtService
from src.services.expense_service import ExpenseService
from src.services.receipt_service import ReceiptService
from src.parsers.currency_parser import CurrencyParser
from src.config import settings

logger = logging.getLogger(__name__)


async def _is_admin_or_sender(context, chat_id: int, user_id: int, payer_telegram_id: int) -> bool:
    """Return True if user_id is a chat admin/creator or the original expense sender."""
    if user_id == payer_telegram_id:
        return True
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in ('administrator', 'creator')
    except Exception:
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    chat_id = update.message.chat_id

    # Check chat size
    try:
        member_count = await context.bot.get_chat_member_count(chat_id)
        human_count = member_count - 1  # Exclude bot

        if human_count > settings.MAX_CHAT_MEMBERS:
            await update.message.reply_text(
                f"⚠️ **Chat Too Large**\n\n"
                f"This chat has {human_count} members. Splitbot is designed for small groups "
                f"(max {settings.MAX_CHAT_MEMBERS} people) like couples, roommates, or friend groups.\n\n"
                f"For larger groups, please consider:\n"
                f"• Creating separate smaller chats\n"
                f"• Using a dedicated expense splitting service for large groups",
                parse_mode='Markdown'
            )
            return
    except Exception as e:
        logger.warning(f"Could not check chat size: {e}")

    await update.message.reply_text(
        "👋 Welcome to Splitbot!\n\n"
        "I help you track shared expenses in small group chats.\n\n"
        "**Quick Start:**\n"
        "1. Add me to a group chat with your friends/roommates\n"
        "2. Type '15 taxi' to track an expense\n"
        "3. Use /balance to see who owes what\n\n"
        "**More Features:**\n"
        "• Send a photo of a receipt for automatic tracking\n"
        "• Type 'paid 100' to record a payment\n"
        "• Use /setratio 2 1 to set custom split ratios\n"
        "• Use /setcurrency USD to change default currency\n\n"
        "Use /help for detailed information.",
        parse_mode='Markdown'
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    help_text = """
📖 **Help**

**Tracking Expenses:**
• `15 taxi` - Track €15 taxi expense
• `50 usd boots` - Track $50 boots
• `€30 dinner` - Track €30 dinner
• `50 boots, 100%` - You paid €50, others owe 100%
• `$200 dinner @alice @bob` - Split only among mentioned users

**Receipt / Invoice Upload:**
• Send a photo or PDF of a receipt/invoice
• Bot extracts amount, currency, merchant, date
• For invoices with a total, uses the total (not line items)
• Confirm or cancel with the inline buttons

**Owe (someone else paid for you):**
• `owe 15 taxi` - In a 2-person chat, other person paid €15, you owe them
• `owe @alice 15 taxi` - Alice paid €15, you owe her (works in any chat)
• `owe 50 usd dinner` - With explicit currency
• `owe 22 food, 100%` - You owe 100% (default applies the chat split ratio)

**Payments:**
• `paid 100` - Paid back €100
• `paid 50 usd` - Paid back $50
• `paid €30` - Paid back €30

**Commands:**
• /balance - Show current debts
• /history - Show recent expenses
• /settings - Show chat settings
• /setcurrency EUR - Set default currency
• /setratio 2 1 - Set split ratio (2/3 and 1/3)
• /delete - Reply to an expense to delete it
• /clear - Clear all expenses and payments
• /help - Show this help

**Need help?** Open an issue on GitHub or contact support.
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /balance command."""
    chat_id = update.message.chat_id

    db_instance = get_db()
    db = await db_instance.get_connection()

    try:
        # Get chat settings for currency
        chat_settings = await chat_model.get_chat_settings(db, chat_id)
        if not chat_settings:
            await update.message.reply_text(
                "No expenses tracked yet. Start by sending an expense like '15 taxi'!"
            )
            return

        currency_parser = CurrencyParser()
        currency_symbol = currency_parser.get_symbol(chat_settings.default_currency)

        # Get balance summary
        debt_service = DebtService(db)
        summary = await debt_service.get_simplified_debt_summary(chat_id, currency_symbol)

        await update.message.reply_text(f"💰 **Balance**\n\n{summary}", parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error getting balance: {e}", exc_info=True)
        await update.message.reply_text("Error calculating balance. Please try again.")


PAGE_SIZE = 10


async def _build_history_page(db, chat_id: int, page: int) -> tuple[str, InlineKeyboardMarkup | None]:
    """Build history text and pagination buttons for a given page (0-indexed)."""
    total = await expense_model.count_chat_expenses(db, chat_id)
    if total == 0:
        return "No expenses tracked yet.", None

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    page = max(0, min(page, total_pages - 1))

    expenses = await expense_model.get_chat_expenses(
        db, chat_id, limit=PAGE_SIZE, offset=page * PAGE_SIZE
    )

    currency_parser = CurrencyParser()
    lines = [f"📝 **Recent Expenses** (page {page + 1}/{total_pages})\n"]

    for exp in expenses:
        payer_name = await user_model.get_user_display_name(db, exp.payer_telegram_id)
        currency_symbol = currency_parser.get_symbol(exp.original_currency)
        date_str = (exp.transaction_date.strftime("%b %d") if exp.transaction_date else exp.created_at.strftime("%b %d"))
        amount_str = (
            f"{currency_symbol}{exp.original_amount:,.2f}"
            if currency_symbol != exp.original_currency
            else f"{exp.original_currency} {exp.original_amount:,.2f}"
        )
        line = f"• {date_str}: {payer_name} paid {amount_str} - {exp.description}"
        if exp.merchant_name:
            line += f" @ {exp.merchant_name}"
        if exp.custom_split:
            from src.models import expense_split as split_model
            splits = await split_model.get_expense_splits(db, exp.id)
            if splits:
                pct_parts = []
                for s in splits:
                    name = await user_model.get_user_display_name(db, s.debtor_telegram_id)
                    pct_parts.append(f"{name} {s.percentage:.0f}%")
                line += f" ({', '.join(pct_parts)})"
        lines.append(line)

    # Build pagination buttons
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("← Prev", callback_data=f"history_page_{chat_id}_{page - 1}"))
    if page < total_pages - 1:
        buttons.append(InlineKeyboardButton("Next →", callback_data=f"history_page_{chat_id}_{page + 1}"))

    markup = InlineKeyboardMarkup([buttons]) if buttons else None
    return "\n".join(lines), markup


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /history command."""
    chat_id = update.message.chat_id

    db_instance = get_db()
    db = await db_instance.get_connection()

    try:
        text, markup = await _build_history_page(db, chat_id, page=0)
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=markup)

    except Exception as e:
        logger.error(f"Error getting history: {e}", exc_info=True)
        await update.message.reply_text("Error getting history. Please try again.")


async def handle_history_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle history pagination button presses."""
    query = update.callback_query
    await query.answer()

    # callback_data: history_page_<chat_id>_<page>
    parts = query.data.split('_')
    chat_id = int(parts[2])
    page = int(parts[3])

    db_instance = get_db()
    db = await db_instance.get_connection()

    try:
        text, markup = await _build_history_page(db, chat_id, page)
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=markup)
    except Exception as e:
        logger.error(f"Error paginating history: {e}", exc_info=True)
        await query.edit_message_text("Error loading history page. Please try again.")


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /settings command."""
    chat_id = update.message.chat_id

    db_instance = get_db()
    db = await db_instance.get_connection()

    try:
        # Get chat settings
        chat_settings = await chat_model.get_or_create_chat_settings(db, chat_id)

        # Get chat members
        members = await user_model.get_chat_members(db, chat_id)
        member_count = len(members)

        settings_text = f"""
⚙️ **Chat Settings**

**Default Currency:** {chat_settings.default_currency}
**Chat Members:** {member_count}

**Split Ratio:**
"""

        if chat_settings.split_ratio_user1 and chat_settings.split_ratio_user2:
            user1_name = await user_model.get_user_display_name(db, chat_settings.user1_telegram_id)
            user2_name = await user_model.get_user_display_name(db, chat_settings.user2_telegram_id)
            settings_text += f"• {user1_name}: {chat_settings.split_ratio_user1*100:.0f}%\n"
            settings_text += f"• {user2_name}: {chat_settings.split_ratio_user2*100:.0f}%\n"
        else:
            settings_text += "• Even split (50/50)\n"

        settings_text += "\n**Commands:**\n"
        settings_text += "• /setcurrency <CODE> - Change default currency\n"
        settings_text += "• /setratio <ratio1> <ratio2> - Set custom split ratio"

        await update.message.reply_text(settings_text, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error getting settings: {e}", exc_info=True)
        await update.message.reply_text("Error getting settings. Please try again.")


async def set_currency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /setcurrency command."""
    chat_id = update.message.chat_id

    # Parse currency from command
    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "Usage: /setcurrency <CODE>\n\n"
            "Examples:\n"
            "• /setcurrency EUR\n"
            "• /setcurrency USD\n"
            "• /setcurrency GBP"
        )
        return

    currency_code = context.args[0].upper()

    # Validate currency
    currency_parser = CurrencyParser()
    if not currency_parser.is_valid_currency(currency_code):
        await update.message.reply_text(
            f"Invalid currency: {currency_code}\n\n"
            f"Supported currencies: {settings.SUPPORTED_CURRENCIES}"
        )
        return

    db_instance = get_db()
    db = await db_instance.get_connection()

    try:
        # Update currency
        await chat_model.update_default_currency(db, chat_id, currency_code)

        await update.message.reply_text(
            f"✓ Default currency updated to {currency_code}"
        )

    except Exception as e:
        logger.error(f"Error setting currency: {e}", exc_info=True)
        await update.message.reply_text("Error updating currency. Please try again.")


async def set_ratio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /setratio command."""
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id

    db_instance = get_db()
    db = await db_instance.get_connection()

    # Ensure the user who sent the command is in the database
    await user_model.create_or_update_user(
        db,
        telegram_id=user_id,
        username=update.message.from_user.username,
        first_name=update.message.from_user.first_name,
        last_name=update.message.from_user.last_name
    )
    await user_model.add_user_to_chat(db, chat_id, user_id)

    # Parse ratios from command
    if not context.args or len(context.args) != 2:
        await update.message.reply_text(
            "Usage: /setratio <ratio1> <ratio2>\n\n"
            "Examples:\n"
            "• /setratio 2 1 - You pay 2/3, other person pays 1/3\n"
            "• /setratio 1 1 - Even split (50/50)\n"
            "• /setratio 3 1 - You pay 75%, other person pays 25%"
        )
        return

    try:
        ratio1 = float(context.args[0])
        ratio2 = float(context.args[1])

        if ratio1 <= 0 or ratio2 <= 0:
            await update.message.reply_text("Ratios must be positive numbers.")
            return

        # Normalize to percentages
        total = ratio1 + ratio2
        ratio1_normalized = ratio1 / total
        ratio2_normalized = ratio2 / total

    except ValueError:
        await update.message.reply_text("Invalid ratio values. Please use numbers (e.g., /setratio 2 1)")
        return

    try:
        # Get actual chat member count from Telegram
        chat_member_count = await context.bot.get_chat_member_count(chat_id)
        logger.info(f"Chat has {chat_member_count} total members (including bot)")

        # Subtract 1 for the bot itself
        human_count = chat_member_count - 1

        if human_count != 2:
            await update.message.reply_text(
                f"Custom split ratios only work in 2-person chats. "
                f"This chat has {human_count} human members."
            )
            return

        # Get tracked members from database (excluding the bot itself)
        all_members = await user_model.get_chat_members(db, chat_id)
        bot_id = context.bot.id
        human_members = [uid for uid in all_members if uid != bot_id]
        logger.info(f"Tracked {len(human_members)} human members in database: {human_members}")

        # Determine the other user ID
        if len(human_members) == 2:
            # Both users have sent messages - we know both IDs
            other_user_id = next(uid for uid in human_members if uid != user_id)
        elif len(human_members) == 1:
            # Only one user (the sender) has interacted so far
            # Set ratio with placeholder for other user
            other_user_id = None
        else:
            # Shouldn't happen, but handle it
            other_user_id = None

        # Update split ratio
        if other_user_id is not None:
            await chat_model.update_split_ratio(
                db, chat_id,
                user1_id=user_id,
                user2_id=other_user_id,
                ratio1=ratio1_normalized,
                ratio2=ratio2_normalized
            )

            # Recalculate all existing non-custom expense splits with the new ratio
            recalculated = await _recalculate_expense_splits(
                db, chat_id, user_id, other_user_id, ratio1_normalized, ratio2_normalized
            )

            other_user_name = await user_model.get_user_display_name(db, other_user_id)
            await update.message.reply_text(
                f"✓ Split ratio updated:\n"
                f"• You: {ratio1_normalized*100:.0f}%\n"
                f"• {other_user_name}: {ratio2_normalized*100:.0f}%\n\n"
                f"📊 Recalculated {recalculated} existing expenses with new ratio.\n"
                f"Use /balance to see updated totals."
            )
        else:
            # Other user will be synced when first expense is created
            await chat_model.update_split_ratio(
                db, chat_id,
                user1_id=user_id,
                user2_id=0,  # Placeholder
                ratio1=ratio1_normalized,
                ratio2=ratio2_normalized
            )

            await update.message.reply_text(
                f"✓ Split ratio set:\n"
                f"• You: {ratio1_normalized*100:.0f}%\n"
                f"• Other person: {ratio2_normalized*100:.0f}%"
            )

    except Exception as e:
        logger.error(f"Error setting ratio: {e}", exc_info=True)
        await update.message.reply_text("Error updating ratio. Please try again.")


async def _recalculate_expense_splits(
    db,
    chat_id: int,
    user1_id: int,
    user2_id: int,
    ratio1: float,
    ratio2: float
) -> int:
    """
    Recalculate all non-custom expense splits with new ratio.

    Args:
        db: Database connection
        chat_id: Chat ID
        user1_id: First user ID
        user2_id: Second user ID
        ratio1: New ratio for user 1
        ratio2: New ratio for user 2

    Returns:
        Number of expenses recalculated
    """
    # Get all non-custom expenses in this chat
    cursor = await db.execute(
        """
        SELECT id, payer_telegram_id, amount
        FROM expenses
        WHERE chat_id = ? AND is_deleted = 0 AND custom_split = 0
        """,
        (chat_id,)
    )
    expenses = await cursor.fetchall()

    recalculated_count = 0

    for expense_id, payer_id, amount in expenses:
        # Delete old splits for this expense
        await db.execute(
            "DELETE FROM expense_splits WHERE expense_id = ?",
            (expense_id,)
        )

        # Determine who owes (the other person)
        if payer_id == user1_id:
            debtor_id = user2_id
            amount_owed = amount * ratio2
            percentage = ratio2 * 100
        else:
            debtor_id = user1_id
            amount_owed = amount * ratio1
            percentage = ratio1 * 100

        # Create new split with updated ratio
        await db.execute(
            """
            INSERT INTO expense_splits (expense_id, debtor_telegram_id, amount_owed, percentage)
            VALUES (?, ?, ?, ?)
            """,
            (expense_id, debtor_id, round(amount_owed, 2), round(percentage, 2))
        )

        recalculated_count += 1

    await db.commit()
    logger.info(f"Recalculated {recalculated_count} expense splits for chat {chat_id}")

    return recalculated_count


async def delete_expense(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /delete command."""
    chat_id = update.message.chat_id
    db_instance = get_db()
    db = await db_instance.get_connection()

    # Check if this is a reply to a message (expense tracking message)
    if update.message.reply_to_message:
        replied_message_id = update.message.reply_to_message.message_id

        try:
            # Find expense by message_id
            cursor = await db.execute(
                """
                SELECT id, description, original_amount, original_currency, payer_telegram_id
                FROM expenses
                WHERE chat_id = ? AND message_id = ? AND is_deleted = 0
                """,
                (chat_id, replied_message_id)
            )
            expense_row = await cursor.fetchone()

            if not expense_row:
                await update.message.reply_text(
                    "No expense found for this message.\n\n"
                    "Try replying to the original expense message or use /delete <expense_id>"
                )
                return

            expense_id, description, amount, currency, payer_id = expense_row

            # Check permission
            requester_id = update.message.from_user.id
            if not await _is_admin_or_sender(context, chat_id, requester_id, payer_id):
                await update.message.reply_text("⚠️ You can only delete your own expenses (or be a chat admin).")
                return

            # Get payer name
            payer_name = await user_model.get_user_display_name(db, payer_id)

            # Create confirmation buttons
            keyboard = [
                [
                    InlineKeyboardButton("✓ Yes, delete", callback_data=f"delete_confirm_{expense_id}"),
                    InlineKeyboardButton("✗ Cancel", callback_data=f"delete_cancel_{expense_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            from src.parsers.currency_parser import CurrencyParser
            currency_parser = CurrencyParser()
            currency_symbol = currency_parser.get_symbol(currency)

            await update.message.reply_text(
                f"⚠️ **Delete Expense**\n\n"
                f"**Amount:** {currency_symbol}{amount:,.2f}\n"
                f"**Description:** {description}\n"
                f"**Paid by:** {payer_name}\n\n"
                f"Delete this expense?",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return

        except Exception as e:
            logger.error(f"Error finding expense by message: {e}", exc_info=True)
            await update.message.reply_text("Error finding expense. Please try again.")
            return

    # Standard usage with expense ID
    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "Usage:\n"
            "• Reply to an expense message with /delete\n"
            "• Or use /delete <expense_id>\n\n"
            "Use /history to see expense IDs."
        )
        return

    try:
        expense_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid expense ID. Please use a number.")
        return

    try:
        # Get expense
        expense = await expense_model.get_expense(db, expense_id)

        if not expense:
            await update.message.reply_text("Expense not found.")
            return

        # Verify it's in this chat
        if expense.chat_id != chat_id:
            await update.message.reply_text("Expense not found in this chat.")
            return

        # Check permission
        requester_id = update.message.from_user.id
        if not await _is_admin_or_sender(context, chat_id, requester_id, expense.payer_telegram_id):
            await update.message.reply_text("⚠️ You can only delete your own expenses (or be a chat admin).")
            return

        # Get payer name
        payer_name = await user_model.get_user_display_name(db, expense.payer_telegram_id)

        # Create confirmation buttons
        keyboard = [
            [
                InlineKeyboardButton("✓ Yes, delete", callback_data=f"delete_confirm_{expense_id}"),
                InlineKeyboardButton("✗ Cancel", callback_data=f"delete_cancel_{expense_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        from src.parsers.currency_parser import CurrencyParser
        currency_parser = CurrencyParser()
        currency_symbol = currency_parser.get_symbol(expense.original_currency)

        await update.message.reply_text(
            f"⚠️ **Delete Expense**\n\n"
            f"**Amount:** {currency_symbol}{expense.original_amount:,.2f}\n"
            f"**Description:** {expense.description}\n"
            f"**Paid by:** {payer_name}\n\n"
            f"Delete this expense?",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error deleting expense: {e}", exc_info=True)
        await update.message.reply_text("Error deleting expense. Please try again.")


async def handle_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle confirmation button callback for /delete command."""
    query = update.callback_query
    await query.answer()

    logger.info(f"Delete callback triggered: {query.data}")

    # Parse callback data
    callback_data = query.data
    if callback_data.startswith('delete_confirm_'):
        action = 'confirm'
        expense_id = int(callback_data.replace('delete_confirm_', ''))
    elif callback_data.startswith('delete_cancel_'):
        action = 'cancel'
        expense_id = int(callback_data.replace('delete_cancel_', ''))
    else:
        logger.error(f"Invalid callback data: {callback_data}")
        await query.edit_message_text("Error: Invalid callback data.")
        return

    logger.info(f"Parsed action: {action}, expense_id: {expense_id}")

    if action == "cancel":
        await query.edit_message_text("✓ Delete cancelled.")
        logger.info(f"Delete cancelled for expense {expense_id}")
        return

    # Proceed with deletion
    db_instance = get_db()
    db = await db_instance.get_connection()

    try:
        # Get expense details before deletion
        expense = await expense_model.get_expense(db, expense_id)

        if not expense:
            await query.edit_message_text("Error: Expense not found.")
            return

        # Check permission
        user_id = query.from_user.id
        if not await _is_admin_or_sender(context, expense.chat_id, user_id, expense.payer_telegram_id):
            await query.answer("You can only delete your own expenses.", show_alert=True)
            return

        # Delete expense
        await expense_model.delete_expense(db, expense_id)

        await query.edit_message_text(
            f"✓ Expense deleted!\n\n"
            f"**Description:** {expense.description}\n"
            f"**Amount:** {expense.original_currency} {expense.original_amount:,.2f}",
            parse_mode='Markdown'
        )

        logger.info(f"Deleted expense {expense_id}: {expense.description}")

    except Exception as e:
        logger.error(f"Error deleting expense: {e}", exc_info=True)
        await query.edit_message_text("Error deleting expense. Please try again.")


async def clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /clear command - clear all expenses and payments with confirmation."""
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id

    # Only allow admins to clear history in group chats
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status not in ('administrator', 'creator'):
            await update.message.reply_text("⚠️ Only chat admins can clear the history.")
            return
    except Exception:
        pass  # Private chats have no admin concept — allow it

    db_instance = get_db()
    db = await db_instance.get_connection()

    try:
        # Count expenses and payments
        expense_cursor = await db.execute(
            "SELECT COUNT(*) FROM expenses WHERE chat_id = ? AND is_deleted = 0",
            (chat_id,)
        )
        expense_count = (await expense_cursor.fetchone())[0]

        payment_cursor = await db.execute(
            "SELECT COUNT(*) FROM payments WHERE chat_id = ? AND is_deleted = 0",
            (chat_id,)
        )
        payment_count = (await payment_cursor.fetchone())[0]

        if expense_count == 0 and payment_count == 0:
            await update.message.reply_text("No history to clear.")
            return

        # Create confirmation buttons
        keyboard = [
            [
                InlineKeyboardButton("✓ Yes, clear all", callback_data=f"clear_confirm_{chat_id}"),
                InlineKeyboardButton("✗ Cancel", callback_data=f"clear_cancel_{chat_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"⚠️ **Clear History**\n\n"
            f"This will delete:\n"
            f"• {expense_count} expense(s)\n"
            f"• {payment_count} payment(s)\n\n"
            f"This action cannot be undone. Are you sure?",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error in clear command: {e}", exc_info=True)
        await update.message.reply_text("Error checking history. Please try again.")


async def handle_clear_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle confirmation button callback for /clear command."""
    query = update.callback_query
    await query.answer()

    logger.info(f"Clear callback triggered: {query.data}")

    # Parse callback data - handle negative chat IDs properly
    callback_data = query.data
    if callback_data.startswith('clear_confirm_'):
        action = 'confirm'
        chat_id = int(callback_data.replace('clear_confirm_', ''))
    elif callback_data.startswith('clear_cancel_'):
        action = 'cancel'
        chat_id = int(callback_data.replace('clear_cancel_', ''))
    else:
        logger.error(f"Invalid callback data: {callback_data}")
        await query.edit_message_text("Error: Invalid callback data.")
        return

    logger.info(f"Parsed action: {action}, chat_id: {chat_id}")

    # Verify chat ID matches
    if chat_id != query.message.chat_id:
        logger.error(f"Chat ID mismatch: {chat_id} != {query.message.chat_id}")
        await query.edit_message_text("Error: Chat ID mismatch.")
        return

    if action == "cancel":
        await query.edit_message_text("✓ Clear cancelled.")
        logger.info(f"Clear cancelled for chat {chat_id}")
        return

    # Proceed with clearing
    db_instance = get_db()
    db = await db_instance.get_connection()

    try:
        logger.info(f"Starting clear for chat {chat_id}")

        # Count before deletion
        expense_cursor = await db.execute(
            "SELECT COUNT(*) FROM expenses WHERE chat_id = ? AND is_deleted = 0",
            (chat_id,)
        )
        expense_count = (await expense_cursor.fetchone())[0]

        payment_cursor = await db.execute(
            "SELECT COUNT(*) FROM payments WHERE chat_id = ? AND is_deleted = 0",
            (chat_id,)
        )
        payment_count = (await payment_cursor.fetchone())[0]

        logger.info(f"Found {expense_count} expenses and {payment_count} payments to delete")

        # Soft delete all expenses
        await db.execute(
            "UPDATE expenses SET is_deleted = 1 WHERE chat_id = ? AND is_deleted = 0",
            (chat_id,)
        )

        # Soft delete all payments
        await db.execute(
            "UPDATE payments SET is_deleted = 1 WHERE chat_id = ? AND is_deleted = 0",
            (chat_id,)
        )

        await db.commit()
        logger.info(f"Database commit successful")

        await query.edit_message_text(
            f"✓ History cleared!\n\n"
            f"Deleted:\n"
            f"• {expense_count} expense(s)\n"
            f"• {payment_count} payment(s)"
        )

        logger.info(f"Cleared history for chat {chat_id}: {expense_count} expenses, {payment_count} payments")

    except Exception as e:
        logger.error(f"Error clearing history: {e}", exc_info=True)
        await query.edit_message_text("Error clearing history. Please try again.")


async def handle_receipt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Add/Cancel buttons from receipt confirmation."""
    query = update.callback_query
    await query.answer()

    callback_data = query.data
    if callback_data.startswith('receipt_confirm_'):
        user_id = int(callback_data.replace('receipt_confirm_', ''))
        action = 'confirm'
    else:
        user_id = int(callback_data.replace('receipt_cancel_', ''))
        action = 'cancel'

    chat_id = query.message.chat_id

    if action == 'cancel':
        await query.edit_message_text("Receipt cancelled.")
        return

    db_instance = get_db()
    db = await db_instance.get_connection()

    try:
        receipt_service = ReceiptService(db)
        pending = await receipt_service.get_pending_confirmation(chat_id, user_id)

        if not pending:
            await query.edit_message_text("Receipt confirmation expired. Please send the image again.")
            return

        # Parse the JSON list stored in description
        items = json.loads(pending['description'])

        expense_service = ExpenseService(db)
        chat_settings = await chat_model.get_chat_settings(db, chat_id)
        currency_parser = CurrencyParser()
        currency_symbol = currency_parser.get_symbol(chat_settings.default_currency)

        created = []
        for i, item in enumerate(items):
            expense_id, splits = await expense_service.create_expense(
                chat_id=chat_id,
                message_id=pending['confirmation_message_id'] * 1000 + i,  # unique per item
                payer_telegram_id=user_id,
                description=item['description'],
                amount=item['amount'],
                currency=item['currency'] or chat_settings.default_currency,
                merchant_name=item.get('merchant'),
                transaction_date=date.fromisoformat(item['date']) if item.get('date') else None,
                receipt_image_file_id=pending['receipt_file_id'],
                is_from_receipt=True,
                bot_id=context.bot.id
            )

            debtor_parts = []
            for debtor_id, amount_owed in splits.items():
                debtor_name = await user_model.get_user_display_name(db, debtor_id)
                debtor_parts.append(f"{debtor_name} owes {currency_symbol}{amount_owed:,.2f}")

            line = f"✓ {currency_parser.get_symbol(item['currency'])}{item['amount']:,.2f} {item['description']}"
            if debtor_parts:
                line += f" ({', '.join(debtor_parts)})"
            created.append(line)

        await receipt_service.delete_pending_confirmation(pending['id'])

        await query.edit_message_text("\n".join(created))
        logger.info(f"Created {len(created)} expense(s) from receipt for user {user_id} in chat {chat_id}")

    except Exception as e:
        logger.error(f"Error confirming receipt: {e}", exc_info=True)
        await query.edit_message_text("Error creating expenses from receipt. Please try again.")
