---
id: 'project/design/architecture/database'
type: 'design'
scope: 'project'
description: 'SQLite persistence for sessions, hook outbox, memory, UX state, and agent metadata.'
---

# Database — Design

## Purpose

- Persist all daemon runtime state in a single SQLite database (`teleclaude.db`).
- Provide durable command/session behavior across daemon restarts.
- Back hook delivery, UX cleanup state, agent availability, and memory storage.

## Storage model

- Single DB file per repo root: `teleclaude.db`.
- Schema bootstraps from `teleclaude/core/schema.sql`.
- Incremental schema changes run through numbered migrations (`teleclaude/core/migrations/*.py`) tracked in `schema_migrations`.

## Core tables

```mermaid
erDiagram
    SESSIONS {
        text session_id PK
        text computer_name
        text tmux_session_name "nullable for headless"
        text lifecycle_status "active|headless|closing|closed"
        text native_session_id "nullable"
        text native_log_file "nullable"
        timestamp created_at
        timestamp last_activity
        timestamp closed_at
    }

    HOOK_OUTBOX {
        int id PK
        text session_id
        text event_type
        text payload "JSON"
        text created_at
        text next_attempt_at
        int attempt_count
        text last_error
        text delivered_at
        text locked_at
    }

    PENDING_MESSAGE_DELETIONS {
        int id PK
        text session_id
        text message_id
        text deletion_type "user_input|feedback"
        timestamp created_at
    }

    AGENT_AVAILABILITY {
        text agent PK
        int available
        text unavailable_until
        text reason
    }

    VOICE_ASSIGNMENTS {
        text id PK
        text service_name
        text voice
        timestamp assigned_at
    }

    MEMORY_OBSERVATIONS {
        int id PK
        text memory_session_id
        text project
        text type
        text title
        text narrative
        int created_at_epoch
    }

    MEMORY_SUMMARIES {
        int id PK
        text memory_session_id
        text project
        text request
        int created_at_epoch
    }

    MEMORY_MANUAL_SESSIONS {
        text memory_session_id PK
        text project UNIQUE
        int created_at_epoch
    }

    SESSIONS ||--o{ HOOK_OUTBOX : "hook events"
    SESSIONS ||--o{ PENDING_MESSAGE_DELETIONS : "cleanup state"
    MEMORY_MANUAL_SESSIONS ||--o{ MEMORY_OBSERVATIONS : "project memory"
    MEMORY_MANUAL_SESSIONS ||--o{ MEMORY_SUMMARIES : "project summaries"
```

## Inputs/Outputs

**Inputs:**

- Session lifecycle updates from command handlers and coordinator.
- Hook receiver outbox inserts.
- UI cleanup tracking updates.
- Memory API writes/searches.
- Agent availability updates from orchestration tools.

**Outputs:**

- Durable session and hook state for restart recovery.
- Queryable snapshots for API/cache layers.
- Retryable hook delivery queue (`hook_outbox`).
- Persistent memory observations/summaries for context injection and search.

## Invariants

- **Single Database File**: Production daemon state lives in one SQLite file (`teleclaude.db`) per repo root.
- **Fail Before Serve**: Migrations run before interfaces are considered ready.
- **Headless Compatibility**: Sessions may have `tmux_session_name = NULL` and still be valid (`lifecycle_status='headless'`).
- **Durable Hook Queue**: Hook events are persisted before daemon processing.
- **Best-effort Exactly-once Effects**: Outbox uses lock + idempotent handlers to tolerate retries.

## Primary flows

### 1. Session lifecycle persistence

1. Create row in `sessions` with ownership + launch metadata.
2. Update row over time (`last_activity`, output/input summaries, native IDs).
3. Close row by setting `closed_at` and lifecycle state.

### 2. Hook outbox delivery

1. Receiver inserts `hook_outbox` row (`delivered_at = NULL`).
2. Daemon claims row by setting `locked_at`.
3. On success: set `delivered_at`.
4. On retryable failure: increment `attempt_count`, set `next_attempt_at`, store `last_error`.
5. On non-retryable/corrupt payload: mark delivered with error.

### 3. Memory persistence

1. Save API call writes to `memory_observations`.
2. FTS virtual table/trigger path indexes observation text when available.
3. Context builder reads `memory_observations` + `memory_summaries` to render startup context.

## Failure modes

- **Lock contention**: SQLite write conflicts delay/deny writes under pressure.
- **Migration failure**: Daemon startup aborts until schema issue is fixed.
- **Outbox backlog growth**: If worker path is unhealthy, undelivered rows accumulate.
- **Disk pressure**: WAL/table growth can degrade performance or fail writes.
- **Corrupt row payload**: Outbox row is marked delivered-with-error to avoid infinite retry loops.
