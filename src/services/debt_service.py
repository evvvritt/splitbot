"""Debt calculation service."""

import logging
from typing import Dict, List
import aiosqlite

from src.models import user as user_model
from src.models import expense_split as split_model
from src.models import payment as payment_model

logger = logging.getLogger(__name__)


class DebtService:
    """Service for calculating debts between users."""

    def __init__(self, db: aiosqlite.Connection):
        """
        Initialize debt service.

        Args:
            db: Database connection
        """
        self.db = db

    async def calculate_balances(self, chat_id: int) -> Dict[int, float]:
        """
        Calculate net balance for all users in a chat.

        Balance formula for each user:
        balance = (what they paid) - (what they owe) + (what they paid back)

        Positive balance = owed TO this user
        Negative balance = this user owes

        Args:
            chat_id: Telegram chat ID

        Returns:
            Dict of {user_id: balance}
        """
        # Get all chat members
        members = await user_model.get_chat_members(self.db, chat_id)

        balances = {}

        for user_id in members:
            # Amount user paid for expenses
            paid = await split_model.get_user_paid_amounts(self.db, chat_id, user_id)

            # Amount user owes
            owed = await split_model.get_user_owed_amounts(self.db, chat_id, user_id)

            # Amount user paid back
            paid_back = await payment_model.get_user_payment_total(self.db, chat_id, user_id)

            # Net balance = paid - owed + paid_back
            balance = paid - owed + paid_back

            balances[user_id] = round(balance, 2)

        return balances

    async def get_balance_summary(self, chat_id: int, currency_symbol: str = '') -> str:
        """
        Get human-readable balance summary.

        Args:
            chat_id: Telegram chat ID
            currency_symbol: Currency symbol for display

        Returns:
            Balance summary string
        """
        balances = await self.calculate_balances(chat_id)

        if not balances:
            return "No expenses tracked yet. Start by sending an expense like '15 taxi'!"

        # Check if all settled
        if all(abs(balance) < 0.01 for balance in balances.values()):
            return "All settled up!"

        # Build debt relationships
        summary_lines = []

        # Sort users by balance (debtors first, then creditors)
        sorted_users = sorted(balances.items(), key=lambda x: x[1])

        for user_id, balance in sorted_users:
            if abs(balance) < 0.01:  # Skip if essentially zero
                continue

            user_name = await user_model.get_user_display_name(self.db, user_id)

            if balance > 0:
                # This user is owed money
                summary_lines.append(f"{user_name} is owed {currency_symbol}{abs(balance):,.2f}")
            else:
                # This user owes money
                summary_lines.append(f"{user_name} owes {currency_symbol}{abs(balance):,.2f}")

        if not summary_lines:
            return "All settled up!"

        return "\n".join(summary_lines)

    async def simplify_debts(self, chat_id: int) -> List[tuple[int, int, float]]:
        """
        Simplify debts to minimize number of transactions.

        Args:
            chat_id: Telegram chat ID

        Returns:
            List of (debtor_id, creditor_id, amount) tuples
        """
        balances = await self.calculate_balances(chat_id)

        # Separate debtors and creditors
        debtors = [(uid, -bal) for uid, bal in balances.items() if bal < -0.01]
        creditors = [(uid, bal) for uid, bal in balances.items() if bal > 0.01]

        # Sort by amount
        debtors.sort(key=lambda x: x[1], reverse=True)
        creditors.sort(key=lambda x: x[1], reverse=True)

        transactions = []

        i, j = 0, 0
        while i < len(debtors) and j < len(creditors):
            debtor_id, debt = debtors[i]
            creditor_id, credit = creditors[j]

            # Amount to settle
            amount = min(debt, credit)

            transactions.append((debtor_id, creditor_id, round(amount, 2)))

            # Update remaining amounts
            debtors[i] = (debtor_id, debt - amount)
            creditors[j] = (creditor_id, credit - amount)

            # Move to next if settled
            if debtors[i][1] < 0.01:
                i += 1
            if creditors[j][1] < 0.01:
                j += 1

        return transactions

    async def get_simplified_debt_summary(self, chat_id: int, currency_symbol: str = '') -> str:
        """
        Get simplified debt summary showing who should pay whom.

        Args:
            chat_id: Telegram chat ID
            currency_symbol: Currency symbol for display

        Returns:
            Simplified debt summary string
        """
        transactions = await self.simplify_debts(chat_id)

        if not transactions:
            return "All settled up!"

        summary_lines = []

        for debtor_id, creditor_id, amount in transactions:
            debtor_name = await user_model.get_user_display_name(self.db, debtor_id)
            creditor_name = await user_model.get_user_display_name(self.db, creditor_id)

            summary_lines.append(f"{debtor_name} → {creditor_name}: {currency_symbol}{amount:,.2f}")

        return "\n".join(summary_lines)
