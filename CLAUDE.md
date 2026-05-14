# splitbot

Telegram group expense-splitting bot written in Python.

## Python environment

Uses a local `venv/` directory (not `.venv`). Always activate before running anything:

```bash
source venv/bin/activate
```

Then run the bot or tests normally:

```bash
python3 main.py
python3 -m pytest tests/ -q
```

Quick one-liner for ad-hoc checks:

```bash
source venv/bin/activate && python3 -c "..."
```

## Deployment

Hosted on Fly.io (`splitbot-muddy-dawn-5545`, region: `ams`). Deploy with:

```bash
fly deploy
```

SQLite database is persisted on a Fly volume mounted at `/data/splitbot.db`. Do not run migrations locally against the prod DB — apply them via `fly ssh console` if needed.
