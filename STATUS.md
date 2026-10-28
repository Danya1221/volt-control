# VOLT Control — implementation status

This is the beginning of the production codebase, **not a completed shop**.

## Implemented
- FastAPI and SQLAlchemy models with an empty database (no beta/demo products).
- Supplier records and ingestion of explicitly complete, current supplier batches.
- New SKU approval queue, manual hide, date-scoped supplier offers and lowest current cost.
- Category/model/SKU markups and admin-key protected API.
- Docker Compose with PostgreSQL and basic tests.

## Not implemented yet
- Telethon sessions, parsing multipart price lists, SIM anomaly review, audit history, full night/promo logic, Telegram Mini App and publishing, backups, production migrations, secure Telegram admin authentication.

## Local startup
1. Copy `.env.example` to `.env` and change `API_KEY` to a long random secret.
2. `docker compose up --build`
3. Open `http://127.0.0.1:8000/docs` and supply `X-API-Key` for admin routes.

**Security:** This repository is currently public. Never commit `.env`, Telegram sessions, API tokens or real supplier data. PostgreSQL password in Compose is a development placeholder and must be changed before any deployment. No Telegram publishing is enabled.
