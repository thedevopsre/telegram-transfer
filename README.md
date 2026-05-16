# Telegram Saved Messages Transfer

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/YOUR_USERNAME/telegram-saved-messages-transfer/actions/workflows/ci.yml/badge.svg)](https://github.com/YOUR_USERNAME/telegram-saved-messages-transfer/actions/workflows/ci.yml)

Bulk-forward posts from your Telegram **Saved Messages** into a **private channel** you own — from your Mac, with a simple web UI.

> **Not affiliated with Telegram.** Uses the official [Telegram API](https://core.telegram.org) via [Telethon](https://docs.telethon.dev/) (user login). No bot token required.

---

## Why this exists

Telegram Desktop/Web makes it hard to select hundreds of Saved Messages and forward them to a channel. This tool:

- Runs **only on your computer** (`127.0.0.1`)
- Keeps your **session and API secrets local**
- Supports **filters**, **dry run**, **batch transfer**, and **resume** after restarts

---

## Features

- Login with phone + code + optional 2FA (cloud password)
- Browse Saved Messages with filters and pagination
- Select messages or **select all matching filter**
- Forward to a channel you can post in (e.g. a private channel you created)
- Dry run, progress bar, pause / resume / cancel
- SQLite job history (no duplicate sends after restart)
- **Log out** (clears local session)

---

## Requirements

- **macOS** (or any OS with Python 3.11+ and Node 18+)
- Telegram account
- [API ID & API hash](https://my.telegram.org/apps) from *API development tools*
- A **channel or group** where you can post (you as owner/admin)

---

## Quick start

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/telegram-saved-messages-transfer.git
cd telegram-saved-messages-transfer
```

### 2. Telegram API credentials

1. Open https://my.telegram.org/apps  
2. Create an application  
3. Copy **api_id** and **api_hash**

### 3. Configure environment (recommended)

```bash
cp .env.example .env
```

Edit `.env`:

```env
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=your_secret_hash_here
TELEGRAM_PHONE=+1234567890
```

Keeping `TELEGRAM_API_HASH` in `.env` avoids sending it through the browser.

### 4. Install and build

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

cd frontend
npm install
npm run build
cd ..
```

### 5. Run

```bash
source .venv/bin/activate
cd backend
python main.py
```

Open **http://127.0.0.1:8000**

---

## How to use

1. **Log in** — API ID, API hash (if not in `.env`), phone, Telegram code, 2FA password if enabled  
2. **Target channel** — choose your channel (e.g. *Franky Posts*)  
3. **Saved Messages** — filter, select posts, or *Select all matching filter*  
4. **Dry run** — see how many messages would transfer  
5. **Start transfer** — confirm and watch progress  
6. **Log out** when done (top-right button)

Transfers **forward** from Saved Messages by default (attribution preserved). Optional *copy mode* drops forward author. **Nothing is deleted** from Saved Messages.

---

## Development

**Backend:**

```bash
source .venv/bin/activate
cd backend && python main.py
```

**Frontend (hot reload):**

```bash
cd frontend && npm run dev
```

→ http://127.0.0.1:5173 (proxies API to port 8000)

**Tests:**

```bash
pytest backend/tests/ -v
```

---

## Project structure

```
├── backend/           # FastAPI + Telethon
│   ├── main.py
│   ├── telegram_client.py
│   ├── db.py
│   ├── jobs.py
│   └── tests/
├── frontend/          # React + Vite
├── data/              # Local session & DB (gitignored)
├── .env.example
├── LICENSE
└── SECURITY.md
```

---

## Local data (never commit)

| File | Purpose |
|------|---------|
| `data/telegram.session` | Telegram login session |
| `data/transfer.db` | Transfer jobs |
| `data/transfer.log` | Transfer log (no passwords) |
| `.env` | API credentials |

---

## Security

- Binds to **127.0.0.1** only — not reachable from other devices by default  
- Do **not** expose port 8000 to the internet  
- Do **not** commit `.env` or `data/`  
- See [SECURITY.md](SECURITY.md) for details and how to report issues  

---

## API reference

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/start` | Send login code |
| POST | `/auth/code` | Submit code |
| POST | `/auth/password` | Submit 2FA |
| POST | `/auth/logout` | Log out |
| GET | `/auth/status` | Login status |
| GET | `/dialogs` | Channels / groups |
| GET | `/messages` | Saved Messages |
| POST | `/jobs/start` | Start transfer |

Full interactive docs: http://127.0.0.1:8000/docs (local only)

---

## License

[MIT](LICENSE) — use, modify, and distribute with attribution.

---

## Disclaimer

You are responsible for complying with Telegram’s [Terms of Service](https://telegram.org/tos) and [API Terms](https://core.telegram.org/api/terms). Use reasonable rate limits; the tool handles `FloodWait` automatically but aggressive use may temporarily limit your account.
