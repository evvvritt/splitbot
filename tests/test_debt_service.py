"""Tests for DebtService balance calculations."""

import pytest
import aiosqlite
from src.services.debt_service import DebtService


CHAT = -1001
EV = 1
MANU = 2

SCHEMA = """
CREATE TABLE users (telegram_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE chat_settings (chat_id INTEGER PRIMARY KEY, default_currency VARCHAR(3) DEFAULT 'EUR', split_ratio_user1 FLOAT, split_ratio_user2 FLOAT, user1_telegram_id INTEGER, user2_telegram_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE chat_members (chat_id INTEGER NOT NULL, telegram_id INTEGER NOT NULL, PRIMARY KEY (chat_id, telegram_id));
CREATE TABLE expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, message_id INTEGER, payer_telegram_id INTEGER, description TEXT, amount DECIMAL, original_amount DECIMAL, original_currency VARCHAR(3), base_currency VARCHAR(3), exchange_rate DECIMAL DEFAULT 1, merchant_name TEXT, transaction_date DATE, receipt_image_file_id TEXT, is_from_receipt BOOLEAN DEFAULT 0, custom_split BOOLEAN DEFAULT 0, is_deleted BOOLEAN DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(chat_id, message_id));
CREATE TABLE expense_splits (id INTEGER PRIMARY KEY AUTOINCREMENT, expense_id INTEGER, debtor_telegram_id INTEGER, amount_owed DECIMAL, percentage DECIMAL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE payments (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, message_id INTEGER, payer_telegram_id INTEGER, amount DECIMAL, original_amount DECIMAL, original_currency VARCHAR(3), base_currency VARCHAR(3), exchange_rate DECIMAL DEFAULT 1, is_deleted BOOLEAN DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(chat_id, message_id));
"""


async def _setup(db):
    for stmt in SCHEMA.strip().split("\n"):
        await db.execute(stmt)
    await db.execute("INSERT INTO users VALUES (?, 'ev', 'ev', NULL, CURRENT_TIMESTAMP)", (EV,))
    await db.execute("INSERT INTO users VALUES (?, 'manu', 'Emanuela', NULL, CURRENT_TIMESTAMP)", (MANU,))
    await db.execute("INSERT INTO chat_settings (chat_id) VALUES (?)", (CHAT,))
    await db.execute("INSERT INTO chat_members VALUES (?, ?)", (CHAT, EV))
    await db.execute("INSERT INTO chat_members VALUES (?, ?)", (CHAT, MANU))
    await db.commit()


async def _expense(db, msg_id, payer, amount, debtor, debtor_amount):
    """Insert an expense and its single split."""
    await db.execute(
        "INSERT INTO expenses (chat_id, message_id, payer_telegram_id, description, amount, original_amount, original_currency, base_currency) VALUES (?,?,?,?,?,?,?,?)",
        (CHAT, msg_id, payer, "test", amount, amount, "EUR", "EUR"),
    )
    cursor = await db.execute("SELECT last_insert_rowid()")
    exp_id = (await cursor.fetchone())[0]
    pct = round(debtor_amount / amount * 100, 2)
    await db.execute(
        "INSERT INTO expense_splits (expense_id, debtor_telegram_id, amount_owed, percentage) VALUES (?,?,?,?)",
        (exp_id, debtor, debtor_amount, pct),
    )
    await db.commit()


async def _payment(db, msg_id, payer, amount):
    await db.execute(
        "INSERT INTO payments (chat_id, message_id, payer_telegram_id, amount, original_amount, original_currency, base_currency) VALUES (?,?,?,?,?,?,?)",
        (CHAT, msg_id, payer, amount, amount, "EUR", "EUR"),
    )
    await db.commit()


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_basic_balance_no_payments():
    """Simple 2:1 split, ev pays €90 → Manu owes €30."""
    async with aiosqlite.connect(":memory:") as db:
        await _setup(db)
        await _expense(db, 1, EV, 90, MANU, 30)

        svc = DebtService(db)
        balances = await svc.calculate_balances(CHAT)

        assert balances[EV] == pytest.approx(30.0)
        assert balances[MANU] == pytest.approx(-30.0)
        assert sum(balances.values()) == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_balances_sum_to_zero_no_payments():
    """Balances always sum to zero when there are no payments."""
    async with aiosqlite.connect(":memory:") as db:
        await _setup(db)
        await _expense(db, 1, EV, 90, MANU, 30)    # Manu owes EV 30
        await _expense(db, 2, MANU, 60, EV, 40)    # EV owes Manu 40

        svc = DebtService(db)
        balances = await svc.calculate_balances(CHAT)

        assert sum(balances.values()) == pytest.approx(0.0)
        # Net: EV owes 40, is owed 30 → EV owes 10
        assert balances[EV] == pytest.approx(-10.0)
        assert balances[MANU] == pytest.approx(10.0)


@pytest.mark.asyncio
async def test_payment_reduces_both_sides():
    """
    Regression: when debtor sends a payment, BOTH balances must update.

    Before fix: creditor's balance stayed inflated; after debtor's balance
    tipped positive, simplify_debts found no debtors → "All settled up!"
    """
    async with aiosqlite.connect(":memory:") as db:
        await _setup(db)
        # Manu paid a big expense early on — EV owes €248.81 (100% custom split)
        await _expense(db, 1, MANU, 248.81, EV, 248.81)
        # EV pays back €245.48
        await _payment(db, 2, EV, 245.48)
        # EV then pays several shared expenses (1/3 split → Manu owes 1/3)
        await _expense(db, 3, EV, 90, MANU, 30)   # chinese
        await _expense(db, 4, EV, 90, MANU, 30)   # shaniu
        await _expense(db, 5, EV, 54, MANU, 18)   # zweiners

        svc = DebtService(db)
        balances = await svc.calculate_balances(CHAT)

        # Sum must always be zero
        assert sum(balances.values()) == pytest.approx(0.0)

        # EV: paid 78 (others' share), owed 248.81, sent 245.48, received 0
        # → 78 - 248.81 + 245.48 - 0 = 74.67 (EV is creditor)
        assert balances[EV] == pytest.approx(74.67, abs=0.01)
        assert balances[MANU] == pytest.approx(-74.67, abs=0.01)


@pytest.mark.asyncio
async def test_no_false_settled_up_after_payment():
    """
    Regression: the bug caused "All settled up!" when both balances went
    positive after a debtor overpaid relative to the (broken) formula.
    Verify simplify_debts never returns empty when a real debt exists.
    """
    async with aiosqlite.connect(":memory:") as db:
        await _setup(db)
        await _expense(db, 1, MANU, 248.81, EV, 248.81)
        await _payment(db, 2, EV, 245.48)
        await _expense(db, 3, EV, 90, MANU, 30)
        await _expense(db, 4, EV, 90, MANU, 30)
        await _expense(db, 5, EV, 54, MANU, 18)

        svc = DebtService(db)
        transactions = await svc.simplify_debts(CHAT)

        assert len(transactions) > 0, "Should not be 'all settled up' — real debt exists"
        debtor_id, creditor_id, amount = transactions[0]
        assert debtor_id == MANU
        assert creditor_id == EV
        assert amount == pytest.approx(74.67, abs=0.01)


@pytest.mark.asyncio
async def test_balances_sum_to_zero_with_payments():
    """Zero-sum must hold even when payments are present."""
    async with aiosqlite.connect(":memory:") as db:
        await _setup(db)
        await _expense(db, 1, MANU, 248.81, EV, 248.81)
        await _payment(db, 2, EV, 245.48)
        await _expense(db, 3, EV, 90, MANU, 30)

        svc = DebtService(db)
        balances = await svc.calculate_balances(CHAT)

        assert sum(balances.values()) == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_fully_settled():
    """When debt is exactly paid off, balance should be zero."""
    async with aiosqlite.connect(":memory:") as db:
        await _setup(db)
        await _expense(db, 1, MANU, 90, EV, 60)   # EV owes Manu 60
        await _payment(db, 2, EV, 60)              # EV pays back exactly 60

        svc = DebtService(db)
        balances = await svc.calculate_balances(CHAT)
        transactions = await svc.simplify_debts(CHAT)

        assert balances[EV] == pytest.approx(0.0, abs=0.01)
        assert balances[MANU] == pytest.approx(0.0, abs=0.01)
        assert transactions == []


@pytest.mark.asyncio
async def test_direction_flips_after_many_expenses():
    """Creditor/debtor role can flip; simplify_debts must reflect that."""
    async with aiosqlite.connect(":memory:") as db:
        await _setup(db)
        await _expense(db, 1, MANU, 90, EV, 60)   # EV owes Manu 60
        await _payment(db, 2, EV, 60)              # EV pays back
        await _expense(db, 3, EV, 90, MANU, 30)   # Now Manu owes EV 30

        svc = DebtService(db)
        transactions = await svc.simplify_debts(CHAT)

        assert len(transactions) == 1
        debtor_id, creditor_id, amount = transactions[0]
        assert debtor_id == MANU
        assert creditor_id == EV
        assert amount == pytest.approx(30.0)
