# Security Policy

## Scope

This project is a **local-only** desktop-style web app. It is designed to run on your own machine at `http://127.0.0.1:8000`, not on the public internet.

## Threat model

| Risk | Mitigation |
|------|------------|
| Session / API secrets leaked via git | `.env`, `data/*.session`, and databases are in `.gitignore` |
| API hash exposed in browser | `TELEGRAM_API_HASH` can stay in `.env` only; `/api/env-defaults` does not return it |
| Remote access to your Telegram account | Server binds to **127.0.0.1** only; do not expose port 8000 to LAN/WAN |
| Passwords in logs | Login codes and 2FA passwords are not logged |
| Path traversal on static files | SPA static handler resolves paths under `frontend/dist` only |
| SQL injection | SQLite queries use parameter binding |

## Recommendations

1. **Never commit** `.env`, `data/telegram.session`, or `data/transfer.db`.
2. **Do not run** behind a reverse proxy on `0.0.0.0` unless you understand the risk (anyone who can reach the port could use your session).
3. **Log out** when finished (removes local session and invalidates the Telethon login on Telegram’s side).
4. Review [Telegram’s API Terms of Service](https://core.telegram.org/api/terms) before bulk-forwarding messages.
5. Use a dedicated `api_id` / `api_hash` from [my.telegram.org](https://my.telegram.org/apps) for this tool.

## Reporting vulnerabilities

If you find a security issue, please open a **private** security advisory on GitHub or email the maintainer (add your contact in the repo). Do not post exploit details in public issues.

## Out of scope

- Hosting this app as a multi-user SaaS
- Storing user credentials on a server
- Bypassing Telegram rate limits or content restrictions
