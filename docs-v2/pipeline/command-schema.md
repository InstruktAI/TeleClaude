# Command Schema (Internal)

## Table: commands

**Primary key**

- `command_id` (string, unique)

**Request**

- `command` (string)
- `payload` (json)
- `source` (string) — originating interface (telec, telegram, mcp, redis)

**Response Contract**

- `expected_events` (json list)
- `event_timeouts_ms` (json map: event → timeout)
- `partial_result` (json, optional)

**State**

- `status` (enum: queued | running | success | failed)
- `created_at` (timestamp)
- `started_at` (timestamp, nullable)
- `completed_at` (timestamp, nullable)
- `last_event` (string, nullable)
- `error_code` (string, nullable)
- `error_message` (string, nullable)

## Status Lifecycle

```
queued → running → success
queued → running → failed
```

## Completion Rules

- A command completes when all `expected_events` are observed within their timeout windows.
- Missing an expected event within its timeout window marks the command as failed.
- Commands may emit extra events; only `expected_events` are required for success.

## Naming

Public API responses use `request_id` as the external alias of `command_id`.
