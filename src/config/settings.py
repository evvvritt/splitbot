"""Configuration management using Pydantic settings."""

from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

    # Bot configuration
    TELEGRAM_BOT_TOKEN: str = Field(..., description="Telegram bot token from @BotFather")
    ANTHROPIC_API_KEY: str = Field(..., description="Anthropic API key for Claude Vision")

    # Database
    DATABASE_PATH: str = Field(default="data/splitbot.db", description="Path to SQLite database file")

    # Currency API
    CURRENCY_API_URL: str = Field(
        default="https://api.exchangerate-api.com/v4/latest/{base}",
        description="Currency exchange rate API URL template"
    )
    CURRENCY_CACHE_HOURS: int = Field(default=1, description="Hours to cache exchange rates")

    # Default settings
    DEFAULT_CURRENCY: str = Field(default="EUR", description="Default currency code")
    DEFAULT_SPLIT_RATIO_1: float = Field(default=0.5, description="Default split ratio for user 1")
    DEFAULT_SPLIT_RATIO_2: float = Field(default=0.5, description="Default split ratio for user 2")

    # Supported currencies
    SUPPORTED_CURRENCIES: str = Field(
        default="USD,EUR,GBP,JPY,INR,CAD,AUD,CHF,CNY,SEK,NZD,KRW,SGD,HKD,NOK,DKK,MXN,ZAR,BRL,ILS",
        description="Comma-separated list of supported currency codes"
    )

    # Receipt processing
    RECEIPT_CONFIRMATION_TIMEOUT: int = Field(
        default=600,
        description="Timeout in seconds for receipt confirmation (default: 10 minutes)"
    )

    # Limits
    MAX_EXPENSE_AMOUNT: float = Field(default=1_000_000, description="Maximum expense amount")
    MAX_HISTORY_ITEMS: int = Field(default=50, description="Maximum number of history items to display")
    MAX_CHAT_MEMBERS: int = Field(default=20, description="Maximum number of members in a chat (excluding bot)")

    # Logging
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")
    LOG_FILE: Optional[str] = Field(default="logs/splitbot.log", description="Log file path")

    @property
    def supported_currencies_set(self) -> set[str]:
        """Get supported currencies as a set."""
        return set(self.SUPPORTED_CURRENCIES.split(','))

    @property
    def currency_symbols(self) -> dict[str, str]:
        """Map of currency symbols to currency codes."""
        return {
            '$': 'USD',
            '€': 'EUR',
            '£': 'GBP',
            '¥': 'JPY',
            '₹': 'INR',
            'kr': 'SEK',
            'R$': 'BRL',
            '₩': 'KRW',
            '₪': 'ILS',
            'Fr': 'CHF',
        }


# Global settings instance
settings = Settings()
