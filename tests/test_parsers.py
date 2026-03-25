"""Tests for message parsers."""

import pytest
from src.parsers.expense_parser import ExpenseParser
from src.parsers.payment_parser import PaymentParser
from src.parsers.currency_parser import CurrencyParser


class TestExpenseParser:
    """Test expense message parsing."""

    def test_basic_expense(self):
        """Test basic expense: '15 taxi'."""
        parser = ExpenseParser()
        result = parser.parse("15 taxi")

        assert result is not None
        assert result.amount == 15.0
        assert result.description == "taxi"
        assert result.currency == "DEFAULT"
        assert result.split_percentage is None

    def test_expense_with_currency_code(self):
        """Test expense with currency code: '50 usd boots'."""
        parser = ExpenseParser()
        result = parser.parse("50 usd boots")

        assert result is not None
        assert result.amount == 50.0
        assert result.description == "boots"
        assert result.currency == "USD"

    def test_expense_with_currency_symbol(self):
        """Test expense with currency symbol: '$50 boots'."""
        parser = ExpenseParser()
        result = parser.parse("$50 boots")

        assert result is not None
        assert result.amount == 50.0
        assert result.description == "boots"
        assert result.currency == "USD"

    def test_expense_with_euro_symbol(self):
        """Test expense with euro symbol: '€30 dinner'."""
        parser = ExpenseParser()
        result = parser.parse("€30 dinner")

        assert result is not None
        assert result.amount == 30.0
        assert result.description == "dinner"
        assert result.currency == "EUR"

    def test_expense_with_custom_split(self):
        """Test expense with custom split: '50 boots, 100%'."""
        parser = ExpenseParser()
        result = parser.parse("50 boots, 100%")

        assert result is not None
        assert result.amount == 50.0
        assert result.description == "boots"
        assert result.split_percentage == 100.0

    def test_expense_with_mentions(self):
        """Test expense with mentions: '200 dinner @alice @bob'."""
        parser = ExpenseParser()
        result = parser.parse("200 dinner @alice @bob")

        assert result is not None
        assert result.amount == 200.0
        assert result.description == "dinner @alice @bob"
        assert "alice" in result.mentioned_users
        assert "bob" in result.mentioned_users

    def test_invalid_expense(self):
        """Test invalid expense message."""
        parser = ExpenseParser()
        result = parser.parse("just some random text")

        assert result is None

    def test_decimal_amount(self):
        """Test expense with decimal amount: '15.50 taxi'."""
        parser = ExpenseParser()
        result = parser.parse("15.50 taxi")

        assert result is not None
        assert result.amount == 15.50


class TestPaymentParser:
    """Test payment message parsing."""

    def test_basic_payment(self):
        """Test basic payment: 'paid 100'."""
        parser = PaymentParser()
        result = parser.parse("paid 100")

        assert result is not None
        assert result.amount == 100.0
        assert result.currency == "DEFAULT"

    def test_payment_with_currency_code(self):
        """Test payment with currency code: 'paid 50 usd'."""
        parser = PaymentParser()
        result = parser.parse("paid 50 usd")

        assert result is not None
        assert result.amount == 50.0
        assert result.currency == "USD"

    def test_payment_with_currency_symbol(self):
        """Test payment with currency symbol: 'paid $100'."""
        parser = PaymentParser()
        result = parser.parse("paid $100")

        assert result is not None
        assert result.amount == 100.0
        assert result.currency == "USD"

    def test_payment_with_euro(self):
        """Test payment with euro: 'paid €30'."""
        parser = PaymentParser()
        result = parser.parse("paid €30")

        assert result is not None
        assert result.amount == 30.0
        assert result.currency == "EUR"

    def test_invalid_payment(self):
        """Test invalid payment message."""
        parser = PaymentParser()
        result = parser.parse("just some text")

        assert result is None


class TestCurrencyParser:
    """Test currency parsing."""

    def test_valid_currency_codes(self):
        """Test valid currency codes."""
        parser = CurrencyParser()

        assert parser.is_valid_currency("USD")
        assert parser.is_valid_currency("EUR")
        assert parser.is_valid_currency("GBP")

    def test_invalid_currency_code(self):
        """Test invalid currency code."""
        parser = CurrencyParser()

        assert not parser.is_valid_currency("XYZ")
        assert not parser.is_valid_currency("ABC")

    def test_get_symbol(self):
        """Test getting currency symbols."""
        parser = CurrencyParser()

        assert parser.get_symbol("USD") == "$"
        assert parser.get_symbol("EUR") == "€"
        assert parser.get_symbol("GBP") == "£"

    def test_normalize_currency(self):
        """Test currency normalization."""
        parser = CurrencyParser()

        assert parser.normalize_currency("$") == "USD"
        assert parser.normalize_currency("€") == "EUR"
        assert parser.normalize_currency("usd") == "USD"
        assert parser.normalize_currency("EUR") == "EUR"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
