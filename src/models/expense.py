"""Expense data access layer."""

from typing import Optional, List
from dataclasses import dataclass
from datetime import datetime, date
import aiosqlite


@dataclass
class Expense:
    """Expense data class."""
    id: int
    chat_id: int
    message_id: int
    payer_telegram_id: int
    description: str
    amount: float
    original_amount: float
    original_currency: str
    base_currency: str
    exchange_rate: float
    merchant_name: Optional[str]
    transaction_date: Optional[date]
    receipt_image_file_id: Optional[str]
    is_from_receipt: bool
    custom_split: bool
    is_deleted: bool
    created_at: datetime
    updated_at: datetime


async def create_expense(
    db: aiosqlite.Connection,
    chat_id: int,
    message_id: int,
    payer_telegram_id: int,
    description: str,
    amount: float,
    original_amount: float,
    original_currency: str,
    base_currency: str,
    exchange_rate: float,
    merchant_name: Optional[str] = None,
    transaction_date: Optional[date] = None,
    receipt_image_file_id: Optional[str] = None,
    is_from_receipt: bool = False,
    custom_split: bool = False
) -> int:
    """
    Create new expense.

    Args:
        db: Database connection
        chat_id: Telegram chat ID
        message_id: Telegram message ID
        payer_telegram_id: Telegram ID of person who paid
        description: Expense description
        amount: Amount in base currency
        original_amount: Amount in original currency
        original_currency: Original currency code
        base_currency: Base currency code
        exchange_rate: Exchange rate used
        merchant_name: Merchant name (from receipt)
        transaction_date: Transaction date (from receipt)
        receipt_image_file_id: Telegram file ID of receipt image
        is_from_receipt: Whether expense was created from receipt
        custom_split: Whether expense uses custom split percentage

    Returns:
        Expense ID
    """
    cursor = await db.execute(
        """
        INSERT INTO expenses (
            chat_id, message_id, payer_telegram_id, description,
            amount, original_amount, original_currency, base_currency,
            exchange_rate, merchant_name, transaction_date,
            receipt_image_file_id, is_from_receipt, custom_split
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chat_id, message_id, payer_telegram_id, description,
            amount, original_amount, original_currency, base_currency,
            exchange_rate, merchant_name, transaction_date,
            receipt_image_file_id, is_from_receipt, custom_split
        )
    )
    await db.commit()
    return cursor.lastrowid


async def get_expense(db: aiosqlite.Connection, expense_id: int) -> Optional[Expense]:
    """
    Get expense by ID.

    Args:
        db: Database connection
        expense_id: Expense ID

    Returns:
        Expense or None
    """
    cursor = await db.execute(
        """
        SELECT id, chat_id, message_id, payer_telegram_id, description,
               amount, original_amount, original_currency, base_currency,
               exchange_rate, merchant_name, transaction_date,
               receipt_image_file_id, is_from_receipt, custom_split, is_deleted,
               created_at, updated_at
        FROM expenses
        WHERE id = ?
        """,
        (expense_id,)
    )
    row = await cursor.fetchone()

    if row:
        return Expense(
            id=row[0],
            chat_id=row[1],
            message_id=row[2],
            payer_telegram_id=row[3],
            description=row[4],
            amount=row[5],
            original_amount=row[6],
            original_currency=row[7],
            base_currency=row[8],
            exchange_rate=row[9],
            merchant_name=row[10],
            transaction_date=date.fromisoformat(row[11]) if row[11] else None,
            receipt_image_file_id=row[12],
            is_from_receipt=bool(row[13]),
            custom_split=bool(row[14]),
            is_deleted=bool(row[15]),
            created_at=datetime.fromisoformat(row[16]),
            updated_at=datetime.fromisoformat(row[17])
        )
    return None


async def get_chat_expenses(
    db: aiosqlite.Connection,
    chat_id: int,
    include_deleted: bool = False,
    limit: int = 50,
    offset: int = 0
) -> List[Expense]:
    """
    Get expenses for a chat.

    Args:
        db: Database connection
        chat_id: Telegram chat ID
        include_deleted: Whether to include deleted expenses
        limit: Maximum number of expenses to return
        offset: Number of expenses to skip (for pagination)

    Returns:
        List of expenses
    """
    query = """
        SELECT id, chat_id, message_id, payer_telegram_id, description,
               amount, original_amount, original_currency, base_currency,
               exchange_rate, merchant_name, transaction_date,
               receipt_image_file_id, is_from_receipt, custom_split, is_deleted,
               created_at, updated_at
        FROM expenses
        WHERE chat_id = ?
    """
    params = [chat_id]

    if not include_deleted:
        query += " AND is_deleted = 0"

    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.append(limit)
    params.append(offset)

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()

    expenses = []
    for row in rows:
        expenses.append(Expense(
            id=row[0],
            chat_id=row[1],
            message_id=row[2],
            payer_telegram_id=row[3],
            description=row[4],
            amount=row[5],
            original_amount=row[6],
            original_currency=row[7],
            base_currency=row[8],
            exchange_rate=row[9],
            merchant_name=row[10],
            transaction_date=date.fromisoformat(row[11]) if row[11] else None,
            receipt_image_file_id=row[12],
            is_from_receipt=bool(row[13]),
            custom_split=bool(row[14]),
            is_deleted=bool(row[15]),
            created_at=datetime.fromisoformat(row[16]),
            updated_at=datetime.fromisoformat(row[17])
        ))

    return expenses


async def count_chat_expenses(
    db: aiosqlite.Connection,
    chat_id: int
) -> int:
    """Return total number of non-deleted expenses for a chat."""
    cursor = await db.execute(
        "SELECT COUNT(*) FROM expenses WHERE chat_id = ? AND is_deleted = 0",
        (chat_id,)
    )
    return (await cursor.fetchone())[0]


async def delete_expense(db: aiosqlite.Connection, expense_id: int) -> None:
    """
    Soft delete an expense.

    Args:
        db: Database connection
        expense_id: Expense ID
    """
    await db.execute(
        """
        UPDATE expenses
        SET is_deleted = 1, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (expense_id,)
    )
    await db.commit()


async def update_expense(
    db: aiosqlite.Connection,
    expense_id: int,
    description: Optional[str] = None,
    amount: Optional[float] = None
) -> None:
    """
    Update an expense.

    Args:
        db: Database connection
        expense_id: Expense ID
        description: New description
        amount: New amount
    """
    updates = []
    params = []

    if description is not None:
        updates.append("description = ?")
        params.append(description)

    if amount is not None:
        updates.append("amount = ?")
        params.append(amount)

    if not updates:
        return

    updates.append("updated_at = CURRENT_TIMESTAMP")
    params.append(expense_id)

    query = f"UPDATE expenses SET {', '.join(updates)} WHERE id = ?"
    await db.execute(query, params)
    await db.commit()
