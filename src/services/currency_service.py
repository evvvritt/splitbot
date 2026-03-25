"""Currency conversion service with API integration and caching."""

import httpx
import logging
from datetime import datetime, timedelta
from typing import Optional
import aiosqlite

from src.config import settings

logger = logging.getLogger(__name__)


class CurrencyService:
    """Service for currency conversion with caching."""

    def __init__(self, db: aiosqlite.Connection):
        """
        Initialize currency service.

        Args:
            db: Database connection
        """
        self.db = db
        self.api_url_template = settings.CURRENCY_API_URL
        self.cache_duration = timedelta(hours=settings.CURRENCY_CACHE_HOURS)

    async def get_rate(self, from_currency: str, to_currency: str) -> float:
        """
        Get exchange rate from one currency to another.

        Args:
            from_currency: Source currency code
            to_currency: Target currency code

        Returns:
            Exchange rate

        Raises:
            Exception: If rate cannot be fetched
        """
        # Same currency
        if from_currency == to_currency:
            return 1.0

        # Check cache first
        cached_rate = await self._get_cached_rate(from_currency, to_currency)
        if cached_rate is not None:
            logger.debug(f"Using cached rate: {from_currency} -> {to_currency} = {cached_rate}")
            return cached_rate

        # Fetch from API
        try:
            rate = await self._fetch_rate_from_api(from_currency, to_currency)
            await self._cache_rate(from_currency, to_currency, rate)
            logger.info(f"Fetched rate from API: {from_currency} -> {to_currency} = {rate}")
            return rate
        except Exception as e:
            logger.error(f"Failed to fetch exchange rate: {e}")
            # Try to use expired cache as fallback
            expired_rate = await self._get_cached_rate(from_currency, to_currency, allow_expired=True)
            if expired_rate is not None:
                logger.warning(f"Using expired cached rate as fallback: {from_currency} -> {to_currency} = {expired_rate}")
                return expired_rate
            raise

    async def convert(self, amount: float, from_currency: str, to_currency: str) -> tuple[float, float]:
        """
        Convert amount from one currency to another.

        Args:
            amount: Amount to convert
            from_currency: Source currency code
            to_currency: Target currency code

        Returns:
            Tuple of (converted_amount, exchange_rate)
        """
        rate = await self.get_rate(from_currency, to_currency)
        converted = round(amount * rate, 2)
        return converted, rate

    async def _get_cached_rate(
        self,
        from_currency: str,
        to_currency: str,
        allow_expired: bool = False
    ) -> Optional[float]:
        """
        Get cached exchange rate.

        Args:
            from_currency: Source currency code
            to_currency: Target currency code
            allow_expired: Whether to return expired cached rates

        Returns:
            Exchange rate or None if not found/expired
        """
        cursor = await self.db.execute(
            """
            SELECT rate, fetched_at
            FROM exchange_rates
            WHERE from_currency = ? AND to_currency = ?
            """,
            (from_currency, to_currency)
        )
        row = await cursor.fetchone()

        if row:
            rate, fetched_at_str = row
            fetched_at = datetime.fromisoformat(fetched_at_str)

            # Check if expired
            if not allow_expired:
                if datetime.now() - fetched_at > self.cache_duration:
                    return None

            return rate

        return None

    async def _fetch_rate_from_api(self, from_currency: str, to_currency: str) -> float:
        """
        Fetch exchange rate from API.

        Args:
            from_currency: Source currency code
            to_currency: Target currency code

        Returns:
            Exchange rate

        Raises:
            Exception: If API request fails
        """
        url = self.api_url_template.format(base=from_currency)

        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10.0)
            response.raise_for_status()
            data = response.json()

            if 'rates' not in data or to_currency not in data['rates']:
                raise ValueError(f"Currency {to_currency} not found in API response")

            return float(data['rates'][to_currency])

    async def _cache_rate(self, from_currency: str, to_currency: str, rate: float) -> None:
        """
        Cache exchange rate in database.

        Args:
            from_currency: Source currency code
            to_currency: Target currency code
            rate: Exchange rate
        """
        await self.db.execute(
            """
            INSERT OR REPLACE INTO exchange_rates (from_currency, to_currency, rate, fetched_at)
            VALUES (?, ?, ?, ?)
            """,
            (from_currency, to_currency, rate, datetime.now().isoformat())
        )
        await self.db.commit()
