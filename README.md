# Telegram Expense Tracking Bot

A Telegram bot for tracking shared expenses in group chats. Designed for couples or small groups — just type expenses naturally, no app required.

## Features

- **Natural expense tracking** — type `15 taxi` and it's logged
- **Owe tracking** — `owe 50 dinner` records an expense someone else paid for you
- **Multi-currency** — `50 usd boots`, `€30 dinner`, automatic conversion to a base currency
- **Custom splits** — `50 boots, 100%` or `50 boots 100%` (comma optional)
- **Receipt & invoice OCR** — send a photo or PDF, bot extracts the total using Claude
- **Configurable split ratio** — `/setratio 2 1` for 2/3 and 1/3 splits
- **Edit handling** — edit any expense/payment message and the bot updates automatically
- **Paginated history** — `/history` with ← Prev / Next → buttons
- **Delete with confirmation** — reply to any expense with `/delete`
- **Admin-only `/clear`** — wipe the chat's history with confirmation

## Setup

### Requirements

- Python 3.11+
- Telegram bot token (from [@BotFather](https://t.me/botfather))
- Anthropic API key (for receipt OCR — [console.anthropic.com](https://console.anthropic.com))

### Install

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in TELEGRAM_BOT_TOKEN and ANTHROPIC_API_KEY in .env
python main.py
```

### BotFather setup

After creating the bot, you **must disable group privacy mode** so the bot can see non-command messages:

1. Message [@BotFather](https://t.me/botfather)
2. `/mybots` → select your bot
3. **Bot Settings** → **Group Privacy** → **Turn off**

## Usage

### Expenses

```
15 taxi                     → you paid €15, split by default ratio
50 usd boots                → with currency code
€30 dinner                  → with currency symbol
50 boots, 100%              → you paid, other person owes 100%
50 boots 100%               → comma is optional
$200 dinner @alice @bob     → split only among mentioned users
```

### Owe (someone else paid for you)

```
owe 15 taxi                 → in a 2-person chat, other person paid
owe @alice 50 dinner        → alice paid, you owe her (any chat size)
owe 22 groceries, 100%      → you owe 100% (default applies split ratio)
owe 50 usd dinner           → with explicit currency
```

### Payments

```
paid 100
paid 50 usd
paid €30
```

### Receipt / Invoice Upload

Send a photo or PDF of a receipt or invoice. The bot uses Claude to extract the total amount, currency, merchant, and date — then shows inline confirm/cancel buttons. For invoices with a total line, the total is used (not individual line items).

### Commands

| Command | Description |
|---|---|
| `/balance` | Show who owes whom |
| `/history` | Paginated expense history |
| `/settings` | Show chat settings |
| `/setcurrency EUR` | Set default currency |
| `/setratio 2 1` | Set split ratio (recalculates existing expenses) |
| `/delete` | Reply to an expense to delete it |
| `/clear` | Clear all expenses and payments (admin only) |
| `/help` | Show help |

### Editing

Edit any expense or payment message in Telegram and the bot automatically updates the record and recalculates splits.

## Deployment (Fly.io)

```bash
brew install flyctl
fly auth login
fly launch --no-deploy
fly volumes create bot_data --size 1 --region ams
fly secrets set TELEGRAM_BOT_TOKEN="..."
fly secrets set ANTHROPIC_API_KEY="..."
fly deploy
```

The SQLite database is stored on a persistent Fly volume at `/data/splitbot.db`.

## Project Structure

```
src/
├── config/       # Settings (env vars)
├── handlers/     # Telegram message/command/photo handlers
├── models/       # SQLite data access layer
├── parsers/      # Regex parsers for expenses, payments, owe
└── services/     # Business logic (splits, debt, currency, receipt OCR)
migrations/
├── schema.sql    # Full DB schema (applied on startup)
main.py           # Entry point
fly.toml          # Fly.io deployment config
Dockerfile
```

## Costs

| Service | Cost |
|---|---|
| Exchange rate API | Free (1,500 req/month, cached 1hr) |
| Claude OCR (receipts) | ~$0.003 per image/PDF |
| Fly.io hosting | Free tier (with credit card on file) |

~100 receipts/month ≈ $0.30/month total.
