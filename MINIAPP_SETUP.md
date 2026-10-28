# VOLT Control Mini App — Railway setup

The Mini App UI is served at:
https://volt-control-production.up.railway.app/miniapp

**Use the button in the owner-only Telegram bot to open it.** Opening the URL
directly in a browser does not provide Telegram-signed initData, so protected
API calls will return 401.

## Required Railway variables (volt-control service)

Existing:
- `DATABASE_URL=${{Postgres.DATABASE_URL}}`
- `API_KEY`

For the admin bot:
- `TG_BOT_TOKEN` — token of @prostootdushi22_bot, stored as a secret
- `VOLT_OWNER_TG_ID` — owner's numeric Telegram user ID
- `VOLT_BOT_ENABLED=1`

For the Mini App:
- `VOLT_MINIAPP_ENABLED=1`
- `VOLT_MINIAPP_URL=https://volt-control-production.up.railway.app/miniapp`
- `TG_API_ID` — Telegram application ID from my.telegram.org
- `TG_API_HASH` — Telegram application hash from my.telegram.org
- `VOLT_SESSION_ENCRYPTION_KEY` — a fresh Fernet key, generated locally with:
  `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

**Do not paste credentials, codes, session strings or encryption keys into chat
or GitHub.** Store them only in Railway Variables. Back up the encryption key
securely: losing it makes stored sessions unrecoverable.

Keep `VOLT_COLLECTOR_ENABLED` unset or `0`. The Mini App has its own
PostgreSQL-backed readers. Run exactly one Railway replica and one Uvicorn
worker to avoid duplicate polling and monitor sessions.

## Using the app

1. Wait for successful Railway deployment and verify `/health`.
2. In Telegram, open @prostootdushi22_bot as the owner and send `/start`.
3. Tap **Открыть VOLT Control**.
4. Choose slot 1 or 2 and use QR login. **QR login requires a second device**
   with the desired Telegram account already signed in. In Telegram on that
   device, open Settings → Devices → Link Desktop Device and scan the QR.
5. Enter the Telegram two-step password in the Mini App if requested.
6. Add allowed supplier chat usernames or numeric IDs, one per line.
7. View captured messages and preview parsing.

**Current scope:** read-only monitoring and parser preview. Supplier price
batches are not yet automatically approved, priced or published. Do not use
this as a live retail catalog until the review and publication pipeline is
implemented and tested.
