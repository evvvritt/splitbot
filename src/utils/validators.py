"""Input validation utilities."""

from src.config import settings


class ValidationError(Exception):
    """Custom exception for validation errors."""
    pass


class CurrencyError(ValidationError):
    """Custom exception for currency-related errors."""
    pass


def validate_amount(amount: float) -> float:
    """
    Validate expense/payment amount.

    Args:
        amount: Amount to validate

    Returns:
        Validated amount (rounded to 2 decimals)

    Raises:
        ValidationError: If amount is invalid
    """
    if amount <= 0:
        raise ValidationError("Amount must be greater than 0")

    if amount > settings.MAX_EXPENSE_AMOUNT:
        raise ValidationError(f"Amount exceeds maximum ({settings.MAX_EXPENSE_AMOUNT})")

    return round(amount, 2)


def validate_currency(currency: str) -> str:
    """
    Validate currency code.

    Args:
        currency: Currency code to validate

    Returns:
        Uppercased currency code

    Raises:
        CurrencyError: If currency is not supported
    """
    currency = currency.upper()

    if currency not in settings.supported_currencies_set:
        raise CurrencyError(
            f"Unsupported currency: {currency}. "
            f"Supported: {settings.SUPPORTED_CURRENCIES}"
        )

    return currency


def validate_split_percentage(percentage: float) -> float:
    """
    Validate split percentage.

    Args:
        percentage: Percentage to validate (0-100)

    Returns:
        Validated percentage

    Raises:
        ValidationError: If percentage is invalid
    """
    if percentage < 0 or percentage > 100:
        raise ValidationError("Split percentage must be between 0 and 100")

    return percentage


def validate_description(description: str, max_length: int = 200) -> str:
    """
    Validate expense description.

    Args:
        description: Description to validate
        max_length: Maximum length allowed

    Returns:
        Validated description (stripped)

    Raises:
        ValidationError: If description is invalid
    """
    description = description.strip()

    if not description:
        raise ValidationError("Description cannot be empty")

    if len(description) > max_length:
        raise ValidationError(f"Description too long (max {max_length} characters)")

    return description
