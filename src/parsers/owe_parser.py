"""Parser for 'owe' messages (recording expenses paid by someone else)."""

import re
from dataclasses import dataclass
from typing import Optional
from src.config import settings


@dataclass
class ParsedOwe:
    """Parsed owe data."""
    username: Optional[str]          # @mention target (without @); None = infer from 2-person chat
    amount: float
    currency: str                    # 'DEFAULT' means use chat's default currency
    description: str
    split_percentage: Optional[float] = None  # None = use default ratio


class OweParser:
    """Parser for 'owe ...' messages."""

    # --- WITH SPLIT (description non-greedy, split required) ---
    # Comma split:  "owe [..] AMOUNT [CURR] DESCRIPTION, SPLIT%"
    # Space split:  "owe [..] AMOUNT [CURR] DESCRIPTION SPLIT%"
    _SPLIT_COMMA = r',\s*(\d+(?:\.\d+)?)%'
    _SPLIT_SPACE = r'\s+(\d+(?:\.\d+)?)%'

    # --- WITHOUT SPLIT (description greedy, consumes the rest) ---
    _DESC_GREEDY = r'(.+)'

    # --- Non-greedy description used when split is required ---
    _DESC_LAZY = r'(.+?)'

    PATTERNS = [
        # ── WITH @mention ──────────────────────────────────────────────────────

        # 1a: @user + currency code + desc + comma-split
        (r'^owe\s+@(\w+)\s+(\d+(?:\.\d+)?)\s+([a-zA-Z]{3})\s+([^,]+)' + _SPLIT_COMMA + r'$', 'user_code_desc_split'),
        # 1b: @user + currency code + desc + space-split
        (r'^owe\s+@(\w+)\s+(\d+(?:\.\d+)?)\s+([a-zA-Z]{3})\s+' + _DESC_LAZY + _SPLIT_SPACE + r'$', 'user_code_desc_split'),
        # 1c: @user + currency code + desc (no split)
        (r'^owe\s+@(\w+)\s+(\d+(?:\.\d+)?)\s+([a-zA-Z]{3})\s+' + _DESC_GREEDY + r'$', 'user_code_desc'),

        # 2a: @user + currency symbol + desc + comma-split
        (r'^owe\s+@(\w+)\s+([$€£¥₹]|kr)\s*(\d+(?:\.\d+)?)\s+([^,]+)' + _SPLIT_COMMA + r'$', 'user_sym_desc_split'),
        # 2b: @user + currency symbol + desc + space-split
        (r'^owe\s+@(\w+)\s+([$€£¥₹]|kr)\s*(\d+(?:\.\d+)?)\s+' + _DESC_LAZY + _SPLIT_SPACE + r'$', 'user_sym_desc_split'),
        # 2c: @user + currency symbol + desc (no split)
        (r'^owe\s+@(\w+)\s+([$€£¥₹]|kr)\s*(\d+(?:\.\d+)?)\s+' + _DESC_GREEDY + r'$', 'user_sym_desc'),

        # 3a: @user + desc + comma-split
        (r'^owe\s+@(\w+)\s+(\d+(?:\.\d+)?)\s+([^,]+)' + _SPLIT_COMMA + r'$', 'user_desc_split'),
        # 3b: @user + desc + space-split
        (r'^owe\s+@(\w+)\s+(\d+(?:\.\d+)?)\s+' + _DESC_LAZY + _SPLIT_SPACE + r'$', 'user_desc_split'),
        # 3c: @user + desc (no split)
        (r'^owe\s+@(\w+)\s+(\d+(?:\.\d+)?)\s+' + _DESC_GREEDY + r'$', 'user_desc'),

        # ── WITHOUT @mention ───────────────────────────────────────────────────

        # 4a: currency code + desc + comma-split
        (r'^owe\s+(\d+(?:\.\d+)?)\s+([a-zA-Z]{3})\s+([^,]+)' + _SPLIT_COMMA + r'$', 'code_desc_split'),
        # 4b: currency code + desc + space-split
        (r'^owe\s+(\d+(?:\.\d+)?)\s+([a-zA-Z]{3})\s+' + _DESC_LAZY + _SPLIT_SPACE + r'$', 'code_desc_split'),
        # 4c: currency code + desc (no split)
        (r'^owe\s+(\d+(?:\.\d+)?)\s+([a-zA-Z]{3})\s+' + _DESC_GREEDY + r'$', 'code_desc'),

        # 5a: currency symbol + desc + comma-split
        (r'^owe\s+([$€£¥₹]|kr)\s*(\d+(?:\.\d+)?)\s+([^,]+)' + _SPLIT_COMMA + r'$', 'sym_desc_split'),
        # 5b: currency symbol + desc + space-split
        (r'^owe\s+([$€£¥₹]|kr)\s*(\d+(?:\.\d+)?)\s+' + _DESC_LAZY + _SPLIT_SPACE + r'$', 'sym_desc_split'),
        # 5c: currency symbol + desc (no split)
        (r'^owe\s+([$€£¥₹]|kr)\s*(\d+(?:\.\d+)?)\s+' + _DESC_GREEDY + r'$', 'sym_desc'),

        # 6a: desc + comma-split
        (r'^owe\s+(\d+(?:\.\d+)?)\s+([^,\d%][^,]*)' + _SPLIT_COMMA + r'$', 'desc_split'),
        # 6b: desc + space-split  (non-greedy desc)
        (r'^owe\s+(\d+(?:\.\d+)?)\s+' + _DESC_LAZY + _SPLIT_SPACE + r'$', 'desc_split'),
        # 6c: desc only (no split)
        (r'^owe\s+(\d+(?:\.\d+)?)\s+' + _DESC_GREEDY + r'$', 'desc'),
    ]

    def __init__(self):
        self.currency_symbols = settings.currency_symbols

    def parse(self, message: str) -> Optional[ParsedOwe]:
        text = message.strip()
        if not text.lower().startswith('owe '):
            return None

        syms = self.currency_symbols

        for pattern, kind in self.PATTERNS:
            m = re.match(pattern, text, re.IGNORECASE)
            if not m:
                continue
            g = m.groups()

            if kind == 'user_code_desc_split':
                user, amt, cur, desc, pct = g
                return ParsedOwe(user, float(amt), cur.upper(), desc.strip(), float(pct))
            elif kind == 'user_code_desc':
                user, amt, cur, desc = g
                return ParsedOwe(user, float(amt), cur.upper(), desc.strip())
            elif kind == 'user_sym_desc_split':
                user, sym, amt, desc, pct = g
                return ParsedOwe(user, float(amt), syms.get(sym, 'USD'), desc.strip(), float(pct))
            elif kind == 'user_sym_desc':
                user, sym, amt, desc = g
                return ParsedOwe(user, float(amt), syms.get(sym, 'USD'), desc.strip())
            elif kind == 'user_desc_split':
                user, amt, desc, pct = g
                return ParsedOwe(user, float(amt), 'DEFAULT', desc.strip(), float(pct))
            elif kind == 'user_desc':
                user, amt, desc = g
                return ParsedOwe(user, float(amt), 'DEFAULT', desc.strip())
            elif kind == 'code_desc_split':
                amt, cur, desc, pct = g
                return ParsedOwe(None, float(amt), cur.upper(), desc.strip(), float(pct))
            elif kind == 'code_desc':
                amt, cur, desc = g
                return ParsedOwe(None, float(amt), cur.upper(), desc.strip())
            elif kind == 'sym_desc_split':
                sym, amt, desc, pct = g
                return ParsedOwe(None, float(amt), syms.get(sym, 'USD'), desc.strip(), float(pct))
            elif kind == 'sym_desc':
                sym, amt, desc = g
                return ParsedOwe(None, float(amt), syms.get(sym, 'USD'), desc.strip())
            elif kind == 'desc_split':
                amt, desc, pct = g
                return ParsedOwe(None, float(amt), 'DEFAULT', desc.strip(), float(pct))
            elif kind == 'desc':
                amt, desc = g
                return ParsedOwe(None, float(amt), 'DEFAULT', desc.strip())

        return None
