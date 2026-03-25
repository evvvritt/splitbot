-- Splitbot Database Schema
-- SQLite database for expense tracking

-- Chat settings - per-chat configuration
CREATE TABLE IF NOT EXISTS chat_settings (
    chat_id INTEGER PRIMARY KEY,
    default_currency VARCHAR(3) NOT NULL DEFAULT 'EUR',
    split_ratio_user1 FLOAT,      -- NULL if >2 users
    split_ratio_user2 FLOAT,      -- NULL if >2 users
    user1_telegram_id INTEGER,    -- NULL if >2 users
    user2_telegram_id INTEGER,    -- NULL if >2 users
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Users - track users across all chats
CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    username VARCHAR(255),
    first_name VARCHAR(255),
    last_name VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Chat members - track which users are in which chats
CREATE TABLE IF NOT EXISTS chat_members (
    chat_id INTEGER NOT NULL,
    telegram_id INTEGER NOT NULL,
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chat_id, telegram_id),
    FOREIGN KEY (telegram_id) REFERENCES users(telegram_id) ON DELETE CASCADE
);

-- Expenses - track all expenses
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    payer_telegram_id INTEGER NOT NULL,
    description TEXT NOT NULL,
    amount DECIMAL(10, 2) NOT NULL,           -- Converted to base currency
    original_amount DECIMAL(10, 2) NOT NULL,
    original_currency VARCHAR(3) NOT NULL,
    base_currency VARCHAR(3) NOT NULL,
    exchange_rate DECIMAL(10, 6) NOT NULL,
    merchant_name VARCHAR(255),               -- From receipt OCR
    transaction_date DATE,                    -- From receipt OCR
    receipt_image_file_id VARCHAR(255),       -- Telegram file_id for receipt image
    is_from_receipt BOOLEAN DEFAULT 0,
    custom_split BOOLEAN DEFAULT 0,
    is_deleted BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (chat_id) REFERENCES chat_settings(chat_id) ON DELETE CASCADE,
    FOREIGN KEY (payer_telegram_id) REFERENCES users(telegram_id) ON DELETE CASCADE,
    UNIQUE(chat_id, message_id)
);

-- Expense splits - who owes what for each expense
CREATE TABLE IF NOT EXISTS expense_splits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_id INTEGER NOT NULL,
    debtor_telegram_id INTEGER NOT NULL,  -- Who owes
    amount_owed DECIMAL(10, 2) NOT NULL,  -- How much they owe (in base currency)
    percentage DECIMAL(5, 2) NOT NULL,    -- Percentage of total they owe
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (expense_id) REFERENCES expenses(id) ON DELETE CASCADE,
    FOREIGN KEY (debtor_telegram_id) REFERENCES users(telegram_id) ON DELETE CASCADE
);

-- Payments - track debt payments
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    payer_telegram_id INTEGER NOT NULL,
    amount DECIMAL(10, 2) NOT NULL,           -- Converted to base currency
    original_amount DECIMAL(10, 2) NOT NULL,
    original_currency VARCHAR(3) NOT NULL,
    base_currency VARCHAR(3) NOT NULL,
    exchange_rate DECIMAL(10, 6) NOT NULL,
    is_deleted BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (chat_id) REFERENCES chat_settings(chat_id) ON DELETE CASCADE,
    FOREIGN KEY (payer_telegram_id) REFERENCES users(telegram_id) ON DELETE CASCADE,
    UNIQUE(chat_id, message_id)
);

-- Exchange rates - cache for currency conversion
CREATE TABLE IF NOT EXISTS exchange_rates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_currency VARCHAR(3) NOT NULL,
    to_currency VARCHAR(3) NOT NULL,
    rate DECIMAL(10, 6) NOT NULL,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(from_currency, to_currency)
);

-- Pending confirmations - track receipts awaiting user confirmation
CREATE TABLE IF NOT EXISTS pending_confirmations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    user_telegram_id INTEGER NOT NULL,
    confirmation_message_id INTEGER NOT NULL,  -- Message ID of bot's confirmation message
    receipt_file_id VARCHAR(255) NOT NULL,
    extracted_amount DECIMAL(10, 2) NOT NULL,
    extracted_currency VARCHAR(3) NOT NULL,
    extracted_description TEXT NOT NULL,
    extracted_merchant VARCHAR(255),
    extracted_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,  -- Auto-expire after 10 minutes
    UNIQUE(chat_id, confirmation_message_id)
);

-- Audit log - track edits and deletes
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type VARCHAR(50) NOT NULL,
    entity_id INTEGER NOT NULL,
    action VARCHAR(50) NOT NULL,
    old_value TEXT,
    new_value TEXT,
    changed_by_telegram_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_expenses_chat_id ON expenses(chat_id);
CREATE INDEX IF NOT EXISTS idx_expenses_payer ON expenses(payer_telegram_id);
CREATE INDEX IF NOT EXISTS idx_expenses_deleted ON expenses(is_deleted);
CREATE INDEX IF NOT EXISTS idx_expense_splits_expense ON expense_splits(expense_id);
CREATE INDEX IF NOT EXISTS idx_expense_splits_debtor ON expense_splits(debtor_telegram_id);
CREATE INDEX IF NOT EXISTS idx_payments_chat_id ON payments(chat_id);
CREATE INDEX IF NOT EXISTS idx_payments_payer ON payments(payer_telegram_id);
CREATE INDEX IF NOT EXISTS idx_exchange_rates_pair ON exchange_rates(from_currency, to_currency);
CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_chat_members_chat ON chat_members(chat_id);
CREATE INDEX IF NOT EXISTS idx_pending_confirmations_chat ON pending_confirmations(chat_id);
CREATE INDEX IF NOT EXISTS idx_pending_confirmations_expires ON pending_confirmations(expires_at);
