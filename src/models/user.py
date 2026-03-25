"""User data access layer."""

from typing import Optional, List
from dataclasses import dataclass
from datetime import datetime
import aiosqlite


@dataclass
class User:
    """User data class."""
    telegram_id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    created_at: datetime


async def get_user(db: aiosqlite.Connection, telegram_id: int) -> Optional[User]:
    """
    Get user by Telegram ID.

    Args:
        db: Database connection
        telegram_id: Telegram user ID

    Returns:
        User or None if not found
    """
    cursor = await db.execute(
        """
        SELECT telegram_id, username, first_name, last_name, created_at
        FROM users
        WHERE telegram_id = ?
        """,
        (telegram_id,)
    )
    row = await cursor.fetchone()

    if row:
        return User(
            telegram_id=row[0],
            username=row[1],
            first_name=row[2],
            last_name=row[3],
            created_at=datetime.fromisoformat(row[4])
        )
    return None


async def create_or_update_user(
    db: aiosqlite.Connection,
    telegram_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None
) -> User:
    """
    Create new user or update existing.

    Args:
        db: Database connection
        telegram_id: Telegram user ID
        username: Telegram username
        first_name: User's first name
        last_name: User's last name

    Returns:
        User
    """
    await db.execute(
        """
        INSERT INTO users (telegram_id, username, first_name, last_name)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name,
            last_name = excluded.last_name
        """,
        (telegram_id, username, first_name, last_name)
    )
    await db.commit()

    return await get_user(db, telegram_id)


async def add_user_to_chat(
    db: aiosqlite.Connection,
    chat_id: int,
    telegram_id: int
) -> None:
    """
    Add user to chat.

    Args:
        db: Database connection
        chat_id: Telegram chat ID
        telegram_id: Telegram user ID
    """
    await db.execute(
        """
        INSERT OR IGNORE INTO chat_members (chat_id, telegram_id)
        VALUES (?, ?)
        """,
        (chat_id, telegram_id)
    )
    await db.commit()


async def get_chat_members(db: aiosqlite.Connection, chat_id: int) -> List[int]:
    """
    Get all members of a chat.

    Args:
        db: Database connection
        chat_id: Telegram chat ID

    Returns:
        List of Telegram user IDs
    """
    cursor = await db.execute(
        """
        SELECT telegram_id
        FROM chat_members
        WHERE chat_id = ?
        """,
        (chat_id,)
    )
    rows = await cursor.fetchall()
    return [row[0] for row in rows]


async def get_user_display_name(db: aiosqlite.Connection, telegram_id: int) -> str:
    """
    Get user's display name.

    Args:
        db: Database connection
        telegram_id: Telegram user ID

    Returns:
        Display name (first name, username, or ID)
    """
    user = await get_user(db, telegram_id)
    if user:
        if user.first_name:
            return user.first_name
        if user.username:
            return f"@{user.username}"
    return f"User {telegram_id}"


async def get_user_by_username(db: aiosqlite.Connection, username: str) -> Optional[User]:
    """
    Get user by Telegram username (case-insensitive).

    Args:
        db: Database connection
        username: Telegram username (without @)

    Returns:
        User or None if not found
    """
    cursor = await db.execute(
        """
        SELECT telegram_id, username, first_name, last_name, created_at
        FROM users
        WHERE LOWER(username) = LOWER(?)
        """,
        (username,)
    )
    row = await cursor.fetchone()

    if row:
        return User(
            telegram_id=row[0],
            username=row[1],
            first_name=row[2],
            last_name=row[3],
            created_at=datetime.fromisoformat(row[4])
        )
    return None


async def sync_chat_members_from_telegram(db: aiosqlite.Connection, chat_id: int, bot, exclude_bot: bool = True):
    """
    Sync all chat members from Telegram API to database.

    Args:
        db: Database connection
        chat_id: Telegram chat ID
        bot: Bot instance
        exclude_bot: Whether to exclude the bot itself

    Returns:
        List of synced user IDs
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        # Get chat administrators (always works)
        admins = await bot.get_chat_administrators(chat_id)

        synced_ids = []

        for admin in admins:
            user = admin.user

            # Skip bot if requested
            if exclude_bot and user.is_bot:
                continue

            # Create or update user
            await create_or_update_user(
                db,
                telegram_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name
            )

            # Add to chat
            await add_user_to_chat(db, chat_id, user.id)
            synced_ids.append(user.id)

        logger.info(f"Synced {len(synced_ids)} members from Telegram for chat {chat_id}")
        return synced_ids

    except Exception as e:
        logger.warning(f"Could not sync chat members from Telegram: {e}")
        return []
