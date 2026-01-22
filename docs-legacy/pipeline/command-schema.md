# Command Schema (Durable Outbox)

TeleClaude uses a durable outbox pattern for commands requiring exactly-once delivery and response tracking (primarily for the `telec` CLI via the API).

## Table: api_outbox

**Primary key**

- `id` (integer, autoincrement)

**Identity & Correlation**

- `request_id` (text, non-null) — Client-provided correlation ID.

**Request**

- `event_type` (text, non-null) — The TeleClaude event to trigger (e.g., `new_session`, `message`).
- `payload` (json, non-null) — The event payload (args, text, etc.).
- `metadata` (json, non-null) — MessageMetadata (adapter_type, project_path, etc.).

**State & Lifecycle**

- `created_at` (timestamp)
- `next_attempt_at` (timestamp) — For exponential backoff.
- `attempt_count` (integer)
- `last_error` (text, nullable)
- `delivered_at` (timestamp, nullable) — Non-null indicates completion.
- `locked_at` (timestamp, nullable) — Used by workers to claim rows.

**Response**

- `response` (json, nullable) — The response envelope from the event handler.

## Status Lifecycle

```
[Pending] (delivered_at IS NULL)
    → [Locked] (locked_at IS NOT NULL)
    → [Success/Failed] (delivered_at IS NOT NULL)
```

## Hook Outbox (Agent Events)

Agent lifecycle events (from hooks) use a similar `hook_outbox` table for reliable delivery to the daemon, ensuring transcripts are parsed and title updates occur even after daemon restarts.
