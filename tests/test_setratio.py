"""
Integration test: /setratio only affects future non-custom expenses.

Flow:
  1. Set 60/40 ratio (EV pays 60%, MANU pays 40%)
  2. Add a non-custom expense and a custom expense
  3. Check balance
  4. Update ratio to 70/30
  5. Add another non-custom and custom expense
  6. Check final balance — old splits must be unchanged, new non-custom uses new ratio,
     custom expenses always use their explicit split regardless of ratio
"""

import pytest
import aiosqlite
from src.models import chat as chat_model
from src.services.expense_service import ExpenseService
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


async def _get_split(db, expense_id):
    cursor = await db.execute(
        "SELECT debtor_telegram_id, amount_owed, percentage FROM expense_splits WHERE expense_id = ?",
        (expense_id,),
    )
    return await cursor.fetchone()


@pytest.mark.asyncio
async def test_setratio_only_affects_future_expenses():
    """
    Full lifecycle: set ratio, add expenses, change ratio, add more expenses.
    Old splits are frozen; new non-custom expenses use the updated ratio;
    custom expenses always use their explicit split.
    """
    async with aiosqlite.connect(":memory:") as db:
        await _setup(db)
        svc = ExpenseService(db)
        debt = DebtService(db)
        msg = 0

        # --- Phase 1: ratio 60/40 (EV=60%, MANU=40%) ---
        await chat_model.update_split_ratio(db, CHAT, EV, MANU, 0.6, 0.4)

        # EV pays €100 (non-custom) → MANU owes 40% = €40
        msg += 1
        exp1, _ = await svc.create_expense(CHAT, msg, EV, "dinner", 100, "EUR")

        # MANU pays €200 (non-custom) → EV owes 60% = €120
        msg += 1
        exp2, _ = await svc.create_expense(CHAT, msg, MANU, "hotel", 200, "EUR")

        # EV pays €50 custom (MANU owes 100%) — ratio should be ignored
        msg += 1
        exp3, _ = await svc.create_expense(CHAT, msg, EV, "ev personal", 50, "EUR", split_percentage=100)

        # Check phase 1 balance:
        #   exp1: EV +40, MANU -40
        #   exp2: EV -120, MANU +120
        #   exp3: EV +50, MANU -50
        #   net:  EV -30, MANU +30
        balances = await debt.calculate_balances(CHAT)
        assert balances[EV] == pytest.approx(-30.0)
        assert balances[MANU] == pytest.approx(30.0)
        assert sum(balances.values()) == pytest.approx(0.0)

        # --- Phase 2: update ratio to 70/30 (EV=70%, MANU=30%) ---
        await chat_model.update_split_ratio(db, CHAT, EV, MANU, 0.7, 0.3)

        # EV pays €100 (non-custom) → MANU now owes 30% = €30 (new ratio)
        msg += 1
        exp4, _ = await svc.create_expense(CHAT, msg, EV, "groceries", 100, "EUR")

        # MANU pays €100 custom (EV owes 100% = €100) — ratio should be ignored
        msg += 1
        exp5, _ = await svc.create_expense(CHAT, msg, MANU, "manu personal", 100, "EUR", split_percentage=100)

        # Verify old expenses were NOT recalculated
        _, owed1, pct1 = await _get_split(db, exp1)
        assert owed1 == pytest.approx(40.0), "exp1 split should still reflect original 40%"
        assert pct1 == pytest.approx(40.0)

        _, owed2, pct2 = await _get_split(db, exp2)
        assert owed2 == pytest.approx(120.0), "exp2 split should still reflect original 60%"
        assert pct2 == pytest.approx(60.0)

        # Verify new non-custom expense uses new 30% ratio
        _, owed4, pct4 = await _get_split(db, exp4)
        assert owed4 == pytest.approx(30.0), "exp4 should use new 30% ratio"
        assert pct4 == pytest.approx(30.0)

        # Verify custom expenses are untouched by either ratio
        _, owed3, pct3 = await _get_split(db, exp3)
        assert owed3 == pytest.approx(50.0), "custom exp3 should be 100% of €50"
        assert pct3 == pytest.approx(100.0)

        _, owed5, pct5 = await _get_split(db, exp5)
        assert owed5 == pytest.approx(100.0), "custom exp5 should be 100% of €100"
        assert pct5 == pytest.approx(100.0)

        # Final balance:
        #   phase 1: EV -30, MANU +30
        #   exp4:     EV +30, MANU -30
        #   exp5:     EV -100, MANU +100
        #   net:      EV -100, MANU +100
        balances = await debt.calculate_balances(CHAT)
        assert balances[EV] == pytest.approx(-100.0)
        assert balances[MANU] == pytest.approx(100.0)
        assert sum(balances.values()) == pytest.approx(0.0)
