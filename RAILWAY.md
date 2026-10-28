# Railway deployment

The `volt-control` service is built from the repository Dockerfile and listens on Railway's `PORT`.

## Required variables in volt-control → Variables

- `DATABASE_URL=${{Postgres.DATABASE_URL}}` — reference the Railway PostgreSQL service variable. SQLAlchemy's psycopg3 driver may need the URL scheme converted to `postgresql+psycopg://`; see below.
- `API_KEY` — a long randomly generated secret (never commit it).

**Important:** Railway commonly supplies a URL starting with `postgresql://`. The API uses SQLAlchemy and installs psycopg3, so if the service fails with a PostgreSQL driver error, configure `DATABASE_URL` as `postgresql+psycopg://` plus the connection credentials, or use the adapter normalization in the application.

## First deployment
1. Wait for the API deployment to finish.
2. Check deployment logs for errors.
3. Generate a public domain in the service's Settings → Networking.
4. Open `https://YOUR-DOMAIN/health`; expected `{"ok":true,"demo_data":false}`.

No supplier accounts are started by the API service. Telegram sessions must be configured later in a separate worker with persistent storage. Never put Telegram sessions in GitHub.
