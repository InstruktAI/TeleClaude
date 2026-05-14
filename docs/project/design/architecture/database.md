---
id: 'project/design/architecture/database'
type: 'design'
scope: 'project'
description: 'SQLite persistence for sessions, hook outbox, memory, UX state, and agent metadata.'
---

# Database — Design

## Purpose

- Persist daemon runtime state in `~/.teleclaude/teleclaude.db`.
- Provide durable command/session behavior across daemon restarts.
- Back hook delivery, UX cleanup state, agent availability, and memory storage.
- Transcript mirrors live in a separate `~/.teleclaude/mirrors.db` (see mirror database section).

## Invariants

- **Database Location**: All databases live under `~/.teleclaude/`. Main DB is `teleclaude.db`, events are `events.db`, mirrors are `mirrors.db`, and hook delivery uses `hook_outbox.db`.
- **Fail Before Serve**: Migrations run before interfaces are considered ready.
- **Headless Compatibility**: Sessions may have `tmux_session_name = NULL` and still be valid (`lifecycle_status='headless'`).
- **Durable Hook Queue**: Hook events are persisted before daemon processing. Processed events are hard-deleted (no soft-delete retention).
- **Best-effort Exactly-once Effects**: Outbox uses lock + idempotent handlers to tolerate retries.
- **Bounded Runtime State**: Operational rows are retained only while live or within the runtime retention window. Closed sessions, terminal queue rows, stale mappings, resolved event notifications, reviewed quarantines, session scratch directories, and session-owned workspaces are pruned by daemon maintenance.
- **Durable History Exclusion**: `mirrors.db`, memory tables, todo/project artifact databases, and other history domains are not pruned by runtime maintenance.
- Schema bootstraps from `teleclaude/core/schema.sql`.
- Incremental schema changes run through numbered migrations (`teleclaude/core/migrations/*.py`) tracked in `schema_migrations`.

### Core tables

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

## Primary flows

### 1. Session lifecycle persistence

1. Create row in `sessions` with ownership + launch metadata.
2. Update row over time (`last_activity`, output/input summaries, native IDs).
3. Close row by setting `closed_at` and lifecycle state.

### 2. Hook outbox delivery

1. Receiver inserts `hook_outbox` row.
2. Daemon claims row by setting `locked_at`.
3. On success: delete row.
4. On retryable failure: increment `attempt_count`, set `next_attempt_at`, store `last_error`.
5. On non-retryable/corrupt payload: delete row (logged as error).

### 3. Memory persistence

1. Save API call writes to `memory_observations`.
2. FTS virtual table/trigger path indexes observation text when available.
3. Context builder reads `memory_observations` + `memory_summaries` to render startup context.

### 4. Runtime maintenance

1. Closed sessions older than the runtime retention window are purged.
2. Session TMPDIRs and session-owned workspace directories are reconciled against live DB session truth.
3. `session_map.json` is pruned as a cache; mappings survive only when the matching DB row is open or recoverable.
4. Operational DB tables prune terminal or orphan rows after the retention window:
   `operations`, `inbound_queue`, `webhook_outbox`, `hook_outbox.db`, `session_tokens`,
   `session_listeners`, and `voice_assignments`.
5. `events.db` prunes resolved notifications and reviewed quarantined events after the retention window while preserving unresolved work.
6. Runtime SQLite files (`teleclaude.db`, `hook_outbox.db`, `events.db`) are compacted only when freelist ratio and free-byte thresholds are exceeded. `mirrors.db` is excluded.

## Failure modes

- **Lock contention**: SQLite write conflicts delay/deny writes under pressure.
- **Migration failure**: Daemon startup aborts until schema issue is fixed.
- **Outbox backlog growth**: If worker path is unhealthy, undelivered rows accumulate.
- **Disk pressure**: WAL/table/freelist growth can degrade performance or fail writes; daemon maintenance checkpoints WAL and threshold-compacts runtime SQLite files.
- **Corrupt row payload**: Outbox row is deleted (with error logging) to avoid infinite retry loops.
