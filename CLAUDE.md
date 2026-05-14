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
