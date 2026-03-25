"""Output formatting utilities."""

from datetime import datetime, date
from typing import List


def format_currency(amount: float, currency_symbol: str = '') -> str:
    """
    Format amount with currency symbol.

    Args:
        amount: Amount to format
        currency_symbol: Currency symbol (e.g., '$', '€')

    Returns:
        Formatted string (e.g., '$15.00')
    """
    return f"{currency_symbol}{amount:,.2f}"


def format_date(date_obj: date) -> str:
    """
    Format date in readable format.

    Args:
        date_obj: Date to format

    Returns:
        Formatted date string (e.g., 'Jan 15')
    """
    return date_obj.strftime("%b %d")


def format_datetime(dt: datetime) -> str:
    """
    Format datetime in readable format.

    Args:
        dt: Datetime to format

    Returns:
        Formatted datetime string (e.g., 'Jan 15, 14:30')
    """
    return dt.strftime("%b %d, %H:%M")


def format_percentage(ratio: float) -> str:
    """
    Format ratio as percentage.

    Args:
        ratio: Ratio (0.0 to 1.0)

    Returns:
        Formatted percentage string (e.g., '66%')
    """
    return f"{ratio * 100:.0f}%"


def format_expense_list(expenses: List[dict], currency_symbol: str = '') -> str:
    """
    Format list of expenses as text.

    Args:
        expenses: List of expense dictionaries
        currency_symbol: Currency symbol

    Returns:
        Formatted expense list
    """
    if not expenses:
        return "No expenses found."

    lines = []
    for exp in expenses:
        line = f"• {format_date(exp['date'])}: {exp['payer']} paid {format_currency(exp['amount'], currency_symbol)} - {exp['description']}"
        lines.append(line)

    return "\n".join(lines)


def truncate_text(text: str, max_length: int = 50) -> str:
    """
    Truncate text with ellipsis if too long.

    Args:
        text: Text to truncate
        max_length: Maximum length

    Returns:
        Truncated text
    """
    if len(text) <= max_length:
        return text

    return text[:max_length - 3] + "..."
