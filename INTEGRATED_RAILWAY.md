# One Railway service: API + optional Telegram supplier monitoring

The existing `volt-control` service runs FastAPI and, when explicitly enabled,
starts up to two read-only Telethon clients in the same process. PostgreSQL is
the only persistent store for integrated collector messages and cursors.
No demo suppliers or products are inserted.

## Railway variables

Keep `DATABASE_URL=${{Postgres.DATABASE_URL}}` and `API_KEY` as already set.

To activate monitoring, set:

- `VOLT_COLLECTOR_ENABLED=1`
- `TG_API_ID_1`, `TG_API_HASH_1`, `TG_SESSION_1`
- Optionally `TG_API_ID_2`, `TG_API_HASH_2`, `TG_SESSION_2`
- `VOLT_SUPPLIER_CONFIG_JSON` — a single-line JSON string such as:

```json
{"accounts":[{"name":"supplier-reader-1","api_id_env":"TG_API_ID_1","api_hash_env":"TG_API_HASH_1","session_env":"TG_SESSION_1","chats":["@example_supplier_channel"]}]}
```

The example chat is a placeholder, not a real supplier. Replace it with a
channel/group the account is already permitted to read. For a second account,
add another object with the corresponding `_2` environment variable names.

Generate a Telethon `StringSession` **locally**, after authorizing your own
account using Telegram's login flow. Store the resulting session string only
in Railway secret variables. Never commit or send it in chat.

Do not enable the collector until actual authorized sessions and real chat
identifiers have been configured. Default is OFF.

## Operational limits

- Keep exactly one Railway replica and one Uvicorn worker. Multiple replicas
  would run duplicate Telegram clients.
- Read-only: captures new messages, edits, missed messages since the cursor,
  and rereads the latest 200 messages on restart.
- Captured messages are stored in `supplier_telegram_messages`, cursors in
  `supplier_telegram_cursors`. This does NOT yet parse and approve supplier
  batches, drive supplier bots, or publish products.
- No Telegram sessions are stored on disk. The session strings remain in
  Railway environment variables. PostgreSQL persists message snapshots.
- `/health` exposes collector state: `disabled`, `running`, or `retrying`.
  A `running` state means the supervisor has started, not proof of successful
  Telegram authentication. Check Railway deploy logs for collector errors.
- Avoid using the Railway service as a general public collector endpoint.
  The administrative endpoints still require `X-API-Key`.
