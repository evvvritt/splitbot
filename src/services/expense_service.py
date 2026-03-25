"""Expense management and split calculation service."""

import logging
from typing import List, Optional, Dict
from datetime import date
import aiosqlite

from src.models import chat as chat_model
from src.models import user as user_model
from src.models import expense as expense_model
from src.models import expense_split as split_model
from src.services.currency_service import CurrencyService

logger = logging.getLogger(__name__)


class ExpenseService:
    """Service for managing expenses and calculating splits."""

    def __init__(self, db: aiosqlite.Connection):
        """
        Initialize expense service.

        Args:
            db: Database connection
        """
        self.db = db
        self.currency_service = CurrencyService(db)

    async def create_expense(
        self,
        chat_id: int,
        message_id: int,
        payer_telegram_id: int,
        description: str,
        amount: float,
        currency: str,
        split_percentage: Optional[float] = None,
        mentioned_users: Optional[List[int]] = None,
        merchant_name: Optional[str] = None,
        transaction_date: Optional[date] = None,
        receipt_image_file_id: Optional[str] = None,
        is_from_receipt: bool = False,
        bot_id: Optional[int] = None
    ) -> tuple[int, Dict[int, float]]:
        """
        Create expense with splits.

        Args:
            chat_id: Telegram chat ID
            message_id: Telegram message ID
            payer_telegram_id: Telegram ID of person who paid
            description: Expense description
            amount: Amount in original currency
            currency: Currency code ('DEFAULT' will use chat's default)
            split_percentage: Custom split percentage (what others owe)
            mentioned_users: List of user IDs to split among (None = all chat members)
            merchant_name: Merchant name (from receipt)
            transaction_date: Transaction date (from receipt)
            receipt_image_file_id: Telegram file ID of receipt image
            is_from_receipt: Whether expense was created from receipt

        Returns:
            Tuple of (expense_id, dict of {user_id: amount_owed})
        """
        # Get chat settings
        chat_settings = await chat_model.get_or_create_chat_settings(self.db, chat_id)

        # Resolve currency
        if currency == 'DEFAULT':
            currency = chat_settings.default_currency

        # Convert to base currency
        base_currency = chat_settings.default_currency
        converted_amount, exchange_rate = await self.currency_service.convert(
            amount, currency, base_currency
        )

        # Create expense record
        expense_id = await expense_model.create_expense(
            self.db,
            chat_id=chat_id,
            message_id=message_id,
            payer_telegram_id=payer_telegram_id,
            description=description,
            amount=converted_amount,
            original_amount=amount,
            original_currency=currency,
            base_currency=base_currency,
            exchange_rate=exchange_rate,
            merchant_name=merchant_name,
            transaction_date=transaction_date,
            receipt_image_file_id=receipt_image_file_id,
            is_from_receipt=is_from_receipt,
            custom_split=(split_percentage is not None)
        )

        # Calculate and create splits
        splits = await self._calculate_splits(
            chat_id=chat_id,
            chat_settings=chat_settings,
            payer_telegram_id=payer_telegram_id,
            total_amount=converted_amount,
            split_percentage=split_percentage,
            mentioned_users=mentioned_users,
            bot_id=bot_id
        )

        # Create split records
        split_records = [
            (expense_id, user_id, amount_owed, percentage)
            for user_id, (amount_owed, percentage) in splits.items()
        ]
        await split_model.create_expense_splits_bulk(self.db, split_records)

        # Return expense ID and split amounts
        split_amounts = {user_id: amount_owed for user_id, (amount_owed, _) in splits.items()}
        return expense_id, split_amounts

    async def _calculate_splits(
        self,
        chat_id: int,
        chat_settings: chat_model.ChatSettings,
        payer_telegram_id: int,
        total_amount: float,
        split_percentage: Optional[float] = None,
        mentioned_users: Optional[List[int]] = None,
        bot_id: Optional[int] = None
    ) -> Dict[int, tuple[float, float]]:
        """
        Calculate who owes what for an expense.

        Args:
            chat_id: Telegram chat ID
            chat_settings: Chat settings
            payer_telegram_id: Telegram ID of person who paid
            total_amount: Total expense amount (in base currency)
            split_percentage: Custom split percentage (what others owe)
            mentioned_users: List of user IDs to split among

        Returns:
            Dict of {user_id: (amount_owed, percentage)}
        """
        # Determine who should split this expense
        if mentioned_users:
            # Use mentioned users only
            participants = mentioned_users
        else:
            # Use all chat members except payer and bot
            all_members = await user_model.get_chat_members(self.db, chat_id)
            participants = [
                uid for uid in all_members
                if uid != payer_telegram_id and uid != bot_id
            ]

        if not participants:
            logger.warning(f"No participants found for expense in chat {chat_id}")
            return {}

        splits = {}

        # Handle custom split percentage
        if split_percentage is not None:
            # split_percentage is what the OTHER person/people owe
            total_owed = total_amount * (split_percentage / 100.0)

            # Split evenly among participants
            amount_per_person = total_owed / len(participants)
            percentage_per_person = split_percentage / len(participants)

            for user_id in participants:
                splits[user_id] = (round(amount_per_person, 2), round(percentage_per_person, 2))

        # Handle 2-person chat with custom ratio
        elif (
            len(participants) == 1 and
            chat_settings.split_ratio_user1 is not None and
            chat_settings.split_ratio_user2 is not None
        ):
            # Determine which user is the participant
            participant_id = participants[0]

            # Determine ratio
            if participant_id == chat_settings.user1_telegram_id:
                ratio = chat_settings.split_ratio_user1
            elif participant_id == chat_settings.user2_telegram_id:
                ratio = chat_settings.split_ratio_user2
            elif chat_settings.user2_telegram_id in (0, None):
                # user2 was a placeholder — this is the first time we see the other person.
                # Resolve the placeholder and apply their ratio.
                ratio = chat_settings.split_ratio_user2
                await chat_model.update_split_ratio(
                    self.db, chat_id,
                    user1_id=chat_settings.user1_telegram_id,
                    user2_id=participant_id,
                    ratio1=chat_settings.split_ratio_user1,
                    ratio2=chat_settings.split_ratio_user2
                )
                logger.info(f"Resolved user2 placeholder to {participant_id} in chat {chat_id}")
            else:
                # 3+ person chat or unrecognised participant — even split
                ratio = 0.5

            amount_owed = total_amount * ratio
            percentage = ratio * 100

            splits[participant_id] = (round(amount_owed, 2), round(percentage, 2))

        # Default: even split among all participants
        else:
            amount_per_person = total_amount / (len(participants) + 1)  # +1 for payer
            percentage_per_person = 100.0 / (len(participants) + 1)

            for user_id in participants:
                splits[user_id] = (round(amount_per_person, 2), round(percentage_per_person, 2))

        return splits
