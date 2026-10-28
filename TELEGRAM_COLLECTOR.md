# Telegram supplier collector (initial implementation)

The collector is **read-only**: it listens to new/edited messages, saves
snapshots in local SQLite, and catches up unseen messages after restart.
It does not automatically parse or publish supplier prices.

1. Install dependencies with `pip install -r requirements.txt`.
2. Copy `supplier_accounts.example.json` to `supplier_accounts.json`.
3. Replace example chats with supplier channels/chats accessible to each account.
4. Set `TG_API_ID_1`, `TG_API_HASH_1`, `TG_API_ID_2`, `TG_API_HASH_2`
   from your own Telegram application credentials. **Never commit these.**
5. Authorize each Telethon session locally, outside the repository, then run
   `python -m app.telegram_collector`. Non-interactive collection requires
   pre-authorized sessions.

Messages are stored in `data/supplier_messages.sqlite3`; session files are
stored under `sessions/`. Both paths must remain private.

**Current limits:** Recent-edit recovery checks the last 200 messages per chat;
older edits may be missed. Multipart assembly, deletion events, supplier-bot
conversations, flood-wait backoff, atomic batch application and reconciliation
are not implemented. SQLite collector storage is not yet integrated with the
PostgreSQL API. Do not deploy this as unattended production ingestion.
