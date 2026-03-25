"""Chat settings data access layer."""

from typing import Optional
from dataclasses import dataclass
from datetime import datetime
import aiosqlite


@dataclass
class ChatSettings:
    """Chat settings data class."""
    chat_id: int
    default_currency: str
    split_ratio_user1: Optional[float]
    split_ratio_user2: Optional[float]
    user1_telegram_id: Optional[int]
    user2_telegram_id: Optional[int]
    created_at: datetime
    updated_at: datetime


async def get_chat_settings(db: aiosqlite.Connection, chat_id: int) -> Optional[ChatSettings]:
    """
    Get chat settings.

    Args:
        db: Database connection
        chat_id: Telegram chat ID

    Returns:
        ChatSettings or None if not found
    """
    cursor = await db.execute(
        """
        SELECT chat_id, default_currency, split_ratio_user1, split_ratio_user2,
               user1_telegram_id, user2_telegram_id, created_at, updated_at
        FROM chat_settings
        WHERE chat_id = ?
        """,
        (chat_id,)
    )
    row = await cursor.fetchone()

    if row:
        return ChatSettings(
            chat_id=row[0],
            default_currency=row[1],
            split_ratio_user1=row[2],
            split_ratio_user2=row[3],
            user1_telegram_id=row[4],
            user2_telegram_id=row[5],
            created_at=datetime.fromisoformat(row[6]),
            updated_at=datetime.fromisoformat(row[7])
        )
    return None


async def create_chat_settings(
    db: aiosqlite.Connection,
    chat_id: int,
    default_currency: str = 'EUR'
) -> ChatSettings:
    """
    Create new chat settings.

    Args:
        db: Database connection
        chat_id: Telegram chat ID
        default_currency: Default currency code

    Returns:
        Created ChatSettings
    """
    await db.execute(
        """
        INSERT INTO chat_settings (chat_id, default_currency)
        VALUES (?, ?)
        """,
        (chat_id, default_currency)
    )
    await db.commit()

    return await get_chat_settings(db, chat_id)


async def update_default_currency(
    db: aiosqlite.Connection,
    chat_id: int,
    currency: str
) -> None:
    """
    Update default currency for chat.

    Args:
        db: Database connection
        chat_id: Telegram chat ID
        currency: New default currency code
    """
    await db.execute(
        """
        UPDATE chat_settings
        SET default_currency = ?, updated_at = CURRENT_TIMESTAMP
        WHERE chat_id = ?
        """,
        (currency, chat_id)
    )
    await db.commit()


async def update_split_ratio(
    db: aiosqlite.Connection,
    chat_id: int,
    user1_id: int,
    user2_id: int,
    ratio1: float,
    ratio2: float
) -> None:
    """
    Update split ratio for 2-person chat.

    Args:
        db: Database connection
        chat_id: Telegram chat ID
        user1_id: First user's Telegram ID
        user2_id: Second user's Telegram ID
        ratio1: First user's ratio (e.g., 0.67 for 2/3)
        ratio2: Second user's ratio (e.g., 0.33 for 1/3)
    """
    await db.execute(
        """
        UPDATE chat_settings
        SET split_ratio_user1 = ?,
            split_ratio_user2 = ?,
            user1_telegram_id = ?,
            user2_telegram_id = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE chat_id = ?
        """,
        (ratio1, ratio2, user1_id, user2_id, chat_id)
    )
    await db.commit()


async def get_or_create_chat_settings(
    db: aiosqlite.Connection,
    chat_id: int,
    default_currency: str = 'EUR'
) -> ChatSettings:
    """
    Get existing chat settings or create if doesn't exist.

    Args:
        db: Database connection
        chat_id: Telegram chat ID
        default_currency: Default currency code

    Returns:
        ChatSettings
    """
    settings = await get_chat_settings(db, chat_id)
    if settings is None:
        settings = await create_chat_settings(db, chat_id, default_currency)
    return settings
