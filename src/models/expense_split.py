"""Expense split data access layer."""

from typing import List
from dataclasses import dataclass
from datetime import datetime
import aiosqlite


@dataclass
class ExpenseSplit:
    """Expense split data class."""
    id: int
    expense_id: int
    debtor_telegram_id: int
    amount_owed: float
    percentage: float
    created_at: datetime


async def create_expense_split(
    db: aiosqlite.Connection,
    expense_id: int,
    debtor_telegram_id: int,
    amount_owed: float,
    percentage: float
) -> int:
    """
    Create an expense split record.

    Args:
        db: Database connection
        expense_id: Expense ID
        debtor_telegram_id: Telegram ID of person who owes
        amount_owed: Amount owed (in base currency)
        percentage: Percentage of expense owed

    Returns:
        Split ID
    """
    cursor = await db.execute(
        """
        INSERT INTO expense_splits (expense_id, debtor_telegram_id, amount_owed, percentage)
        VALUES (?, ?, ?, ?)
        """,
        (expense_id, debtor_telegram_id, amount_owed, percentage)
    )
    await db.commit()
    return cursor.lastrowid


async def create_expense_splits_bulk(
    db: aiosqlite.Connection,
    splits: List[tuple[int, int, float, float]]
) -> None:
    """
    Create multiple expense splits at once.

    Args:
        db: Database connection
        splits: List of (expense_id, debtor_telegram_id, amount_owed, percentage) tuples
    """
    await db.executemany(
        """
        INSERT INTO expense_splits (expense_id, debtor_telegram_id, amount_owed, percentage)
        VALUES (?, ?, ?, ?)
        """,
        splits
    )
    await db.commit()


async def get_expense_splits(
    db: aiosqlite.Connection,
    expense_id: int
) -> List[ExpenseSplit]:
    """
    Get all splits for an expense.

    Args:
        db: Database connection
        expense_id: Expense ID

    Returns:
        List of expense splits
    """
    cursor = await db.execute(
        """
        SELECT id, expense_id, debtor_telegram_id, amount_owed, percentage, created_at
        FROM expense_splits
        WHERE expense_id = ?
        """,
        (expense_id,)
    )
    rows = await cursor.fetchall()

    splits = []
    for row in rows:
        splits.append(ExpenseSplit(
            id=row[0],
            expense_id=row[1],
            debtor_telegram_id=row[2],
            amount_owed=row[3],
            percentage=row[4],
            created_at=datetime.fromisoformat(row[5])
        ))

    return splits


async def get_user_owed_amounts(
    db: aiosqlite.Connection,
    chat_id: int,
    telegram_id: int
) -> float:
    """
    Get total amount owed by a user in a chat.

    Args:
        db: Database connection
        chat_id: Telegram chat ID
        telegram_id: Telegram user ID

    Returns:
        Total amount owed
    """
    cursor = await db.execute(
        """
        SELECT COALESCE(SUM(es.amount_owed), 0)
        FROM expense_splits es
        JOIN expenses e ON es.expense_id = e.id
        WHERE e.chat_id = ?
          AND es.debtor_telegram_id = ?
          AND e.is_deleted = 0
        """,
        (chat_id, telegram_id)
    )
    row = await cursor.fetchone()
    return row[0] if row else 0.0


async def get_user_paid_amounts(
    db: aiosqlite.Connection,
    chat_id: int,
    telegram_id: int
) -> float:
    """
    Get total amount paid by a user in a chat.

    Args:
        db: Database connection
        chat_id: Telegram chat ID
        telegram_id: Telegram user ID

    Returns:
        Total amount paid
    """
    # Sum what others owe this user (i.e. their share of expenses this user paid)
    cursor = await db.execute(
        """
        SELECT COALESCE(SUM(es.amount_owed), 0)
        FROM expense_splits es
        JOIN expenses e ON es.expense_id = e.id
        WHERE e.chat_id = ?
          AND e.payer_telegram_id = ?
          AND e.is_deleted = 0
        """,
        (chat_id, telegram_id)
    )
    row = await cursor.fetchone()
    return row[0] if row else 0.0
