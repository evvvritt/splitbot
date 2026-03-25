"""Database initialization and connection management."""

import aiosqlite
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class Database:
    """Database connection and initialization manager."""

    def __init__(self, db_path: str):
        """
        Initialize database manager.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._connection: Optional[aiosqlite.Connection] = None

    async def initialize(self):
        """Initialize database schema."""
        # Ensure database directory exists
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        # Read schema file
        schema_path = Path(__file__).parent.parent.parent / "migrations" / "schema.sql"
        with open(schema_path, 'r') as f:
            schema_sql = f.read()

        # Execute schema
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(schema_sql)
            await db.commit()
            logger.info(f"Database initialized at {self.db_path}")

    async def get_connection(self) -> aiosqlite.Connection:
        """
        Get database connection.

        Returns:
            Active database connection
        """
        if self._connection is None:
            self._connection = await aiosqlite.connect(self.db_path)
            # Enable foreign keys
            await self._connection.execute("PRAGMA foreign_keys = ON")
        return self._connection

    async def close(self):
        """Close database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None
            logger.info("Database connection closed")

    async def execute(self, query: str, params: tuple = ()):
        """
        Execute a query.

        Args:
            query: SQL query
            params: Query parameters

        Returns:
            Cursor object
        """
        conn = await self.get_connection()
        return await conn.execute(query, params)

    async def execute_many(self, query: str, params_list: list[tuple]):
        """
        Execute a query with multiple parameter sets.

        Args:
            query: SQL query
            params_list: List of parameter tuples
        """
        conn = await self.get_connection()
        await conn.executemany(query, params_list)
        await conn.commit()

    async def fetch_one(self, query: str, params: tuple = ()) -> Optional[tuple]:
        """
        Fetch one row.

        Args:
            query: SQL query
            params: Query parameters

        Returns:
            Single row or None
        """
        cursor = await self.execute(query, params)
        return await cursor.fetchone()

    async def fetch_all(self, query: str, params: tuple = ()) -> list[tuple]:
        """
        Fetch all rows.

        Args:
            query: SQL query
            params: Query parameters

        Returns:
            List of rows
        """
        cursor = await self.execute(query, params)
        return await cursor.fetchall()

    async def commit(self):
        """Commit current transaction."""
        conn = await self.get_connection()
        await conn.commit()


# Global database instance
_db_instance: Optional[Database] = None


def get_db(db_path: Optional[str] = None) -> Database:
    """
    Get global database instance.

    Args:
        db_path: Optional database path (used for initialization)

    Returns:
        Database instance
    """
    global _db_instance
    if _db_instance is None:
        if db_path is None:
            from src.config import settings
            db_path = settings.DATABASE_PATH
        _db_instance = Database(db_path)
    return _db_instance
