"""Currency detection and validation utilities."""

import re
from typing import Optional
from src.config import settings


class CurrencyParser:
    """Parser for currency codes and symbols."""

    def __init__(self):
        """Initialize parser with currency mappings."""
        self.currency_symbols = settings.currency_symbols
        self.supported_currencies = settings.supported_currencies_set

        # Reverse mapping: code to symbol
        self.currency_codes_to_symbols = {
            'USD': '$',
            'EUR': '€',
            'GBP': '£',
            'JPY': '¥',
            'INR': '₹',
            'SEK': 'kr',
        }

    def extract_currency(self, text: str) -> Optional[str]:
        """
        Extract currency code or symbol from text.

        Args:
            text: Text potentially containing currency

        Returns:
            Currency code (e.g., 'USD') or None
        """
        text = text.strip()

        # Check for currency symbols
        for symbol, code in self.currency_symbols.items():
            if symbol in text:
                return code

        # Check for currency codes (3-letter words)
        match = re.search(r'\b([A-Z]{3})\b', text, re.IGNORECASE)
        if match:
            potential_code = match.group(1).upper()
            if self.is_valid_currency(potential_code):
                return potential_code

        return None

    def is_valid_currency(self, currency_code: str) -> bool:
        """
        Check if currency code is supported.

        Args:
            currency_code: 3-letter currency code

        Returns:
            True if supported, False otherwise
        """
        return currency_code.upper() in self.supported_currencies

    def get_symbol(self, currency_code: str) -> str:
        """
        Get currency symbol for a currency code.

        Args:
            currency_code: 3-letter currency code (e.g., 'USD')

        Returns:
            Currency symbol (e.g., '$') or the code itself if no symbol exists
        """
        return self.currency_codes_to_symbols.get(currency_code, currency_code)

    def normalize_currency(self, currency: str) -> str:
        """
        Normalize currency input to standard 3-letter code.

        Args:
            currency: Currency code or symbol

        Returns:
            Normalized 3-letter currency code
        """
        # If it's a symbol, convert to code
        if currency in self.currency_symbols:
            return self.currency_symbols[currency]

        # If it's already a code, just uppercase it
        if len(currency) == 3:
            return currency.upper()

        # Default to USD if we can't determine
        return 'USD'
