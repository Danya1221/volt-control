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

## Supplier parsing increment
- `app/price_parser.py` extracts conservative candidate rows from text and returns review/ignored lines.
- `POST /admin/price-lists/preview` accepts `{"text":"..."}` under the admin API key and **does not write to the database**.
- Missing/ambiguous smartphone SIM configurations require manual review.
- Parser tests added in `tests/test_price_parser.py`.
- **Not yet connected to Telegram.** No multipart assembly, supplier-specific mapping, or production-grade format coverage yet. Tests have not been executed in CI.

## Telegram collector foundation
- Added read-only Telethon collector for up to two pre-authorized user accounts.
- New/edited message snapshots, restart catch-up, per-chat cursors.
- See TELEGRAM_COLLECTOR.md for setup and limitations. Not integrated with PostgreSQL or automated publishing.


## Mini App: этап подключения аккаунтов
- Добавлены owner-only Mini App, QR-вход в два слота с поддержкой Telegram 2FA, шифрование сессий и сохранение их в PostgreSQL.
- Чаты для чтения задаются в панели; мониторинг запускается в том же процессе и восстанавливается после перезапуска. См. MINIAPP_RAILWAY.md.
- QR-вход и сбор в реальном Railway/Telegram ещё требуют проверки после настройки секретов. Автоматические тесты используют имитацию Telegram и SQLite.
- Сбор сообщений всё ещё не связан с применением прайсов. Обработка, управление товарами и публикация каталога через Mini App не завершены.

## Просмотр сообщений поставщиков
- Mini App показывает сохранённые текстовые сообщения по каждому подключённому аккаунту и позволяет предварительно разобрать строковый прайс без записи товаров или применения цен.
- Сборщик не запускает ботов поставщиков и не обрабатывает файлы, вложения и многочастные прайсы. Каталог и публикация остаются незавершёнными.
