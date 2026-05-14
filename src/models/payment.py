"""Payment data access layer."""

from typing import List, Optional
from dataclasses import dataclass
from datetime import datetime
import aiosqlite


@dataclass
class Payment:
    """Payment data class."""
    id: int
    chat_id: int
    message_id: int
    payer_telegram_id: int
    amount: float
    original_amount: float
    original_currency: str
    base_currency: str
    exchange_rate: float
    is_deleted: bool
    created_at: datetime


async def create_payment(
    db: aiosqlite.Connection,
    chat_id: int,
    message_id: int,
    payer_telegram_id: int,
    amount: float,
    original_amount: float,
    original_currency: str,
    base_currency: str,
    exchange_rate: float
) -> int:
    """
    Create a new payment.

    Args:
        db: Database connection
        chat_id: Telegram chat ID
        message_id: Telegram message ID
        payer_telegram_id: Telegram ID of person who paid
        amount: Amount in base currency
        original_amount: Amount in original currency
        original_currency: Original currency code
        base_currency: Base currency code
        exchange_rate: Exchange rate used

    Returns:
        Payment ID
    """
    cursor = await db.execute(
        """
        INSERT INTO payments (
            chat_id, message_id, payer_telegram_id, amount,
            original_amount, original_currency, base_currency, exchange_rate
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chat_id, message_id, payer_telegram_id, amount,
            original_amount, original_currency, base_currency, exchange_rate
        )
    )
    await db.commit()
    return cursor.lastrowid


async def get_payment(db: aiosqlite.Connection, payment_id: int) -> Optional[Payment]:
    """
    Get payment by ID.

    Args:
        db: Database connection
        payment_id: Payment ID

    Returns:
        Payment or None
    """
    cursor = await db.execute(
        """
        SELECT id, chat_id, message_id, payer_telegram_id, amount,
               original_amount, original_currency, base_currency,
               exchange_rate, is_deleted, created_at
        FROM payments
        WHERE id = ?
        """,
        (payment_id,)
    )
    row = await cursor.fetchone()

    if row:
        return Payment(
            id=row[0],
            chat_id=row[1],
            message_id=row[2],
            payer_telegram_id=row[3],
            amount=row[4],
            original_amount=row[5],
            original_currency=row[6],
            base_currency=row[7],
            exchange_rate=row[8],
            is_deleted=bool(row[9]),
            created_at=datetime.fromisoformat(row[10])
        )
    return None


async def get_chat_payments(
    db: aiosqlite.Connection,
    chat_id: int,
    include_deleted: bool = False
) -> List[Payment]:
    """
    Get all payments for a chat.

    Args:
        db: Database connection
        chat_id: Telegram chat ID
        include_deleted: Whether to include deleted payments

    Returns:
        List of payments
    """
    query = """
        SELECT id, chat_id, message_id, payer_telegram_id, amount,
               original_amount, original_currency, base_currency,
               exchange_rate, is_deleted, created_at
        FROM payments
        WHERE chat_id = ?
    """
    params = [chat_id]

    if not include_deleted:
        query += " AND is_deleted = 0"

    query += " ORDER BY created_at DESC"

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()

    payments = []
    for row in rows:
        payments.append(Payment(
            id=row[0],
            chat_id=row[1],
            message_id=row[2],
            payer_telegram_id=row[3],
            amount=row[4],
            original_amount=row[5],
            original_currency=row[6],
            base_currency=row[7],
            exchange_rate=row[8],
            is_deleted=bool(row[9]),
            created_at=datetime.fromisoformat(row[10])
        ))

    return payments


async def get_user_payment_total(
    db: aiosqlite.Connection,
    chat_id: int,
    telegram_id: int
) -> float:
    """
    Get total amount paid back by a user.

    Args:
        db: Database connection
        chat_id: Telegram chat ID
        telegram_id: Telegram user ID

    Returns:
        Total amount paid
    """
    cursor = await db.execute(
        """
        SELECT COALESCE(SUM(amount), 0)
        FROM payments
        WHERE chat_id = ?
          AND payer_telegram_id = ?
          AND is_deleted = 0
        """,
        (chat_id, telegram_id)
    )
    row = await cursor.fetchone()
    return row[0] if row else 0.0


async def get_others_payment_total(
    db: aiosqlite.Connection,
    chat_id: int,
    telegram_id: int
) -> float:
    """
    Get total payments made by other users in a chat (i.e. received by this user).

    In a 2-person chat this equals what was paid TO this user.
    """
    cursor = await db.execute(
        """
        SELECT COALESCE(SUM(amount), 0)
        FROM payments
        WHERE chat_id = ?
          AND payer_telegram_id != ?
          AND is_deleted = 0
        """,
        (chat_id, telegram_id)
    )
    row = await cursor.fetchone()
    return row[0] if row else 0.0


async def delete_payment(db: aiosqlite.Connection, payment_id: int) -> None:
    """
    Soft delete a payment.

    Args:
        db: Database connection
        payment_id: Payment ID
    """
    await db.execute(
        """
        UPDATE payments
        SET is_deleted = 1
        WHERE id = ?
        """,
        (payment_id,)
    )
    await db.commit()
