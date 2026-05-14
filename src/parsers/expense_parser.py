"""Parser for expense messages."""

import re
from dataclasses import dataclass
from typing import Optional
from src.config import settings


@dataclass
class ParsedExpense:
    """Parsed expense data."""
    amount: float
    description: str
    currency: str  # 'DEFAULT' means use chat's default currency
    split_percentage: Optional[float] = None  # None means use default split
    mentioned_users: list[str] = None  # List of @mentioned usernames

    def __post_init__(self):
        if self.mentioned_users is None:
            self.mentioned_users = []


class ExpenseParser:
    """Parser for expense messages with regex patterns."""

    # Expense patterns (in priority order)
    PATTERNS = [
        # Pattern 1: amount + currency code + description + split: "50 usd boots, 100%"
        r'^(\d+(?:\.\d+)?)\s*([a-zA-Z]{3})\s+([^,]+),\s*(\d+(?:\.\d+)?)%?$',

        # Pattern 2: symbol + amount + description + split: "$50 boots, 100%"
        r'^([$€£¥₹]|kr)\s*(\d+(?:\.\d+)?)\s+([^,]+),\s*(\d+(?:\.\d+)?)%?$',

        # Pattern 3: amount + description + split with comma (default currency): "50 boots, 100%"
        r'^(\d+(?:\.\d+)?)\s+([^,]+),\s*(\d+(?:\.\d+)?)%?$',

        # Pattern 4: amount + description + split without comma (default currency): "50 boots 100%"
        r'^(\d+(?:\.\d+)?)\s+(.+?)\s+(\d+(?:\.\d+)?)%?$',

        # Pattern 5: amount + currency code + description: "50 usd boots"
        r'^(\d+(?:\.\d+)?)\s*([a-zA-Z]{3})\s+(.+)$',

        # Pattern 6: symbol + amount + description: "$50 boots"
        r'^([$€£¥₹]|kr)\s*(\d+(?:\.\d+)?)\s+(.+)$',

        # Pattern 7: amount + description (use default currency): "50 boots"
        r'^(\d+(?:\.\d+)?)\s+(.+)$',
    ]

    # Pattern for extracting @ mentions
    MENTION_PATTERN = r'@(\w+)'

    def __init__(self):
        """Initialize parser with currency symbol mapping."""
        self.currency_symbols = settings.currency_symbols
        self.valid_currencies = settings.supported_currencies_set

    @staticmethod
    def _normalize_input(text: str) -> str:
        """Normalize European-style amounts before pattern matching.

        Handles comma as decimal separator (36,41 → 36.41) and
        amount-then-symbol order (36.41€ → €36.41).
        """
        # Comma decimal: only when exactly 1-2 digits follow (avoids split "100%")
        text = re.sub(r'(\d),(\d{1,2})(?=\D|$)', r'\1.\2', text)
        # Amount+symbol → symbol+amount so existing patterns match
        text = re.sub(r'(\d+(?:\.\d+)?)\s*([$€£¥₹])', r'\2\1', text)
        text = re.sub(r'(\d+(?:\.\d+)?)\s*kr\b', r'kr\1', text)
        return text

    def parse(self, message: str) -> Optional[ParsedExpense]:
        """
        Parse expense message and extract components.

        Args:
            message: Raw message text

        Returns:
            ParsedExpense object or None if parsing fails
        """
        message = self._normalize_input(message.strip())

        # Try pattern 1: amount + currency code + description + split
        match = re.match(self.PATTERNS[0], message, re.IGNORECASE)
        if match and match.group(2).upper() in self.valid_currencies:
            amount_str, currency, description, split_str = match.groups()
            mentioned_users = self._extract_mentions(description)
            return ParsedExpense(
                amount=float(amount_str),
                currency=currency.upper(),
                description=description.strip(),
                split_percentage=float(split_str),
                mentioned_users=mentioned_users
            )

        # Try pattern 2: symbol + amount + description + split
        match = re.match(self.PATTERNS[1], message)
        if match:
            symbol, amount_str, description, split_str = match.groups()
            mentioned_users = self._extract_mentions(description)
            return ParsedExpense(
                amount=float(amount_str),
                currency=self.currency_symbols.get(symbol, 'USD'),
                description=description.strip(),
                split_percentage=float(split_str),
                mentioned_users=mentioned_users
            )

        # Try pattern 3: amount + description + split with comma (default currency)
        match = re.match(self.PATTERNS[2], message)
        if match:
            amount_str, description, split_str = match.groups()
            mentioned_users = self._extract_mentions(description)
            return ParsedExpense(
                amount=float(amount_str),
                currency='DEFAULT',
                description=description.strip(),
                split_percentage=float(split_str),
                mentioned_users=mentioned_users
            )

        # Try pattern 4: amount + description + split without comma (default currency)
        match = re.match(self.PATTERNS[3], message)
        if match:
            amount_str, description, split_str = match.groups()
            mentioned_users = self._extract_mentions(description)
            return ParsedExpense(
                amount=float(amount_str),
                currency='DEFAULT',
                description=description.strip(),
                split_percentage=float(split_str),
                mentioned_users=mentioned_users
            )

        # Try pattern 5: amount + currency code + description
        match = re.match(self.PATTERNS[4], message, re.IGNORECASE)
        if match and match.group(2).upper() in self.valid_currencies:
            amount_str, currency, description = match.groups()
            mentioned_users = self._extract_mentions(description)
            return ParsedExpense(
                amount=float(amount_str),
                currency=currency.upper(),
                description=description.strip(),
                mentioned_users=mentioned_users
            )

        # Try pattern 6: symbol + amount + description
        match = re.match(self.PATTERNS[5], message)
        if match:
            symbol, amount_str, description = match.groups()
            mentioned_users = self._extract_mentions(description)
            return ParsedExpense(
                amount=float(amount_str),
                currency=self.currency_symbols.get(symbol, 'USD'),
                description=description.strip(),
                mentioned_users=mentioned_users
            )

        # Try pattern 7: amount + description (default currency)
        match = re.match(self.PATTERNS[6], message)
        if match:
            amount_str, description = match.groups()
            mentioned_users = self._extract_mentions(description)
            return ParsedExpense(
                amount=float(amount_str),
                currency='DEFAULT',  # Will be replaced with chat default
                description=description.strip(),
                mentioned_users=mentioned_users
            )

        return None

    def _extract_mentions(self, text: str) -> list[str]:
        """
        Extract @ mentions from text.

        Args:
            text: Text containing potential mentions

        Returns:
            List of mentioned usernames (without @)
        """
        matches = re.findall(self.MENTION_PATTERN, text)
        return [match for match in matches]
