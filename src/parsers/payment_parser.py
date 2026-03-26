"""Parser for payment messages."""

import re
from dataclasses import dataclass
from typing import Optional
from src.config import settings


@dataclass
class ParsedPayment:
    """Parsed payment data."""
    amount: float
    currency: str  # 'DEFAULT' means use chat's default currency


class PaymentParser:
    """Parser for payment messages with regex patterns."""

    # Payment patterns (in priority order)
    PATTERNS = [
        # Pattern 1: "paid 100 usd" - with currency code
        r'^paid\s+(\d+(?:\.\d+)?)\s*([a-zA-Z]{3})$',

        # Pattern 2: "paid $100" - with currency symbol
        r'^paid\s+([$€£¥₹]|kr)\s*(\d+(?:\.\d+)?)$',

        # Pattern 3: "paid 100" - amount only (use default currency)
        r'^paid\s+(\d+(?:\.\d+)?)$',
    ]

    def __init__(self):
        """Initialize parser with currency symbol mapping."""
        self.currency_symbols = settings.currency_symbols

    @staticmethod
    def _normalize_input(text: str) -> str:
        """Normalize European-style amounts: comma decimal and amount+symbol order."""
        text = re.sub(r'(\d),(\d{1,2})(?=\D|$)', r'\1.\2', text)
        text = re.sub(r'(\d+(?:\.\d+)?)\s*([$€£¥₹])', r'\2\1', text)
        text = re.sub(r'(\d+(?:\.\d+)?)\s*kr\b', r'kr\1', text)
        return text

    def parse(self, message: str) -> Optional[ParsedPayment]:
        """
        Parse payment message and extract amount and currency.

        Args:
            message: Raw message text

        Returns:
            ParsedPayment object or None if parsing fails
        """
        message = self._normalize_input(message.strip()).lower()

        # Try pattern 1: with currency code
        match = re.match(self.PATTERNS[0], message, re.IGNORECASE)
        if match:
            amount_str, currency = match.groups()
            return ParsedPayment(
                amount=float(amount_str),
                currency=currency.upper()
            )

        # Try pattern 2: with currency symbol
        match = re.match(self.PATTERNS[1], message)
        if match:
            symbol, amount_str = match.groups()
            return ParsedPayment(
                amount=float(amount_str),
                currency=self.currency_symbols.get(symbol, 'USD')
            )

        # Try pattern 3: amount only (use default currency)
        match = re.match(self.PATTERNS[2], message)
        if match:
            amount_str = match.groups()[0]
            return ParsedPayment(
                amount=float(amount_str),
                currency='DEFAULT'  # Will be replaced with chat default
            )

        return None
