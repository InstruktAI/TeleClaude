---
description: 'SQLite persistence for sessions, hook outbox, memory, UX state, and agent metadata.'
visibility: 'public'
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

<!-- planned:distributed-todo-postgres -->

### Todo store distribution

The workflow todo store is the first store to move off the per-machine SQLite layout onto the shared **cluster database** — one Postgres instance for the whole fleet (more stores may follow later; the todo store is the first user). Every other store this document covers — `teleclaude.db`, `events.db`, `mirrors.db`, `hook_outbox.db`, and the memory tables — stays local SQLite, unchanged. The boundary is exact: only the todo store moves now.

- **Cluster-DB host topology.** The shared Postgres is hosted on the node designated by `computer.is_cluster_db_host` (exactly one per fleet). This is its own role, independent of `is_master` (the UI/mobile workhorse) and of `is_ingress_node` (the webhook edge). Today the cluster-DB host is _usually co-located on the ingress node_ by deployment convention — because there is no secure cross-node transport yet — but that is convention, not a requirement: the host may relocate once secure inter-node transport exists, with no change to this contract. The host binds Postgres to loopback plus the cluster's private network interface only and never the public interface. Every node connects through one DSN (`services.cluster_db.dsn` — loopback on the host itself, the host's private-network address from every other node). After migration a non-host node holds no live todo database; its local `.teleclaude/todos.db` becomes archival.
- **Provisioning.** Making the cluster DB usable for cutover is a setup-time responsibility of the cluster-DB host, carried by the platform's sanctioned service-setup path — the `make` install/lifecycle targets that already own host service mechanics (per the Agent Service Control policy / ADR-0041) — and gated on `computer.is_cluster_db_host`. On the host, setup ensures the Postgres instance exists, is initialized, and is bound to loopback plus the private network; `services.cluster_db.dsn` is the resolved connection string the daemon and CLI use. Non-host nodes provision nothing — they receive the host's DSN through config only. No new host-service wrapper is introduced; provisioning rides the existing `make`/daemon service-control layer.
- **Dual-engine connection factory.** `teleclaude/core/db/connection_factory.py` gains a Postgres engine path driven by `services.cluster_db.dsn`, used by the todo store alone; every other store keeps the existing SQLite factory. The store is already SQLAlchemy/SQLModel, so this is an engine/dialect swap plus reconciling the SQLite-isms in the raw `teleclaude/core/todos_db/schema.sql` (PRAGMAs, `AUTOINCREMENT`, the partial unique index, file-path target), not a new data layer.
- **Schema port, project-scoped from migration 0001.** The live todo schema (`todo`, `todo_state`, `todo_artifacts`, `todo_artifact_versions`, `todo_deps`, `todo_dispatch_claims`) ports to Postgres renaming nothing, in one initial migration. It adds exactly: a `project` row keyed by the `ProjectRef` identity (origin URL nullable metadata) with a `project_id` foreign key on every todo row and `(project_id, slug)` replacing the implicit per-database slug uniqueness; an `execution_host` column for durable execution ownership; and the promotion of `todo_dispatch_claims` to a cluster-wide, project-scoped atomic claim. Queryable lifecycle fields stay as they are; the JSON `state` blob stays a JSONB column with no premature column promotion; any new value sets reconcile against the live `LifecyclePhaseValue` and todo-kind vocabularies so no follow-on migration is needed.
- **Idempotent, reconciling migration.** Per-computer todo SQLite databases are reconciled — not blindly copied — into one authoritative row per `(project, slug)`. The migration runs once per (project, source computer), is SHA-tracked so re-runs are safe no-ops, and preserves slugs and the whole JSON state blob. Conflict resolution: for remote-backed projects git is the tiebreaker — the row consistent with `origin/<slug>` wins and sets `execution_host` to the computer holding that validated worktree (or NULL when merged/clean); for local-only projects the single source wins trivially. Verification is per-project pre/post counts plus a dry run against a copy of real data before the cutover commit.
- **Coordinated cutover.** Every todo read/write path — the chokepoint accessors `get_todos_db` / `get_todos_db_sync` / `todos_db_path` and all callers through them (HTTP API, integration, operations, roadmap, the orchestrator state machines, CLI handlers) — moves onto the Postgres-backed store in one coordinated step, with no dual source of truth and no per-file staging that leaves some callers on SQLite. The cutover is staged so it does not self-destruct the running orchestrator (whose own session imports the store).
<!-- /planned:distributed-todo-postgres -->

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

    VOICE_TRANSCRIPTIONS {
        int id PK
        text session_id
        text audio_path
        text origin
        text notice_message_id "nullable"
        text state "pending|in_progress|succeeded|failed|interrupted"
        int attempts
        text last_error "nullable"
        timestamp created_at
        timestamp updated_at
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

    VOICE_TRANSCRIPTIONS {
        text id PK
        text session_id
        text audio_path "absolute path on disk"
        text origin "discord|telegram"
        text notice_message_id "nullable; set post-send (the platform id only exists after the notice send returns)"
        text state "pending|in_progress|succeeded|failed|interrupted"
        int attempts "recovery resubmission count; capped"
        text last_error "nullable"
        timestamp created_at
        timestamp updated_at
    }

    SESSIONS ||--o{ HOOK_OUTBOX : "hook events"
    SESSIONS ||--o{ PENDING_MESSAGE_DELETIONS : "cleanup state"
    SESSIONS ||--o{ VOICE_TRANSCRIPTIONS : "in-flight transcription recovery"
    MEMORY_MANUAL_SESSIONS ||--o{ MEMORY_OBSERVATIONS : "project memory"
    MEMORY_MANUAL_SESSIONS ||--o{ MEMORY_SUMMARIES : "project summaries"
```

The daemon owns `voice_transcriptions`; it is the single source of truth for
the durability requirement in `@prd#scope` (a transcription in progress at
shutdown is not lost) and the recovery contract in `@prd#success-criteria`.
Adapter-side identity (`notice_message_id`, `origin`) is persisted so recovery
edits the _existing_ placeholder rather than emitting a duplicate, satisfying
`@prd#success-criteria` (edited in place, not a new duplicate message). The
`state` column carries the lifecycle the recovery flow keys off of; `audio_path`
lets recovery verify the captured audio still exists before resubmitting.

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

### 4. Voice transcription durability and recovery

1. The row is written in two grounded steps so the original placeholder is
   editable after a crash. First, **before** the speech-to-text call, a row is
   written `state=pending` with `audio_path` and `notice_message_id=NULL`.
   Second, the "🎤 Transcribing…" placeholder is sent, and the platform message
   id it returns is written back as `notice_message_id` (a single follow-up
   update). The crash window between these two steps is bounded by the recovery
   contract below: a row recovered with `notice_message_id=NULL` is resubmitted
   with a fresh placeholder rather than an edit, since no original placeholder is
   known to exist.
2. The row transitions `in_progress` when the speech-to-text call starts,
   `succeeded` once the transcription is fed to the session, and `failed` when
   the bounded speech-to-text call times out or terminally fails. Blocking STT
   backend setup must run off the event loop so this timeout can fire.
3. If the owning task is cancelled during shutdown (the voice flow runs as a
   tracked task, cancelled at shutdown step 9 before adapters stop at step 10 —
   see `daemon-lifecycle#shutdown-ordering`), the cancellation handler marks the
   row `interrupted` and, when `notice_message_id` is set, edits the placeholder
   in place.
4. On the next boot, a recovery pass (see
   `daemon-lifecycle#post-adapter-completion-tasks`) reads rows in
   `pending|in_progress|interrupted` and processes each **idempotently, keyed by
   row id**: it increments `attempts` and, if `attempts` exceeds the recovery
   cap (a small named bound), transitions the row to terminal `failed` with
   `last_error` recorded and edits the placeholder to a failure notice — so a
   repeatedly-failing transcription cannot loop on every boot. Within the cap, if
   `audio_path` still exists it resubmits (editing the original placeholder when
   `notice_message_id` is set, otherwise sending a fresh one); if the audio is
   gone it transitions to terminal `failed` and edits the placeholder to an
   audio-lost notice.
5. Terminal rows (`succeeded|failed`) and orphaned temp audio with no live row
   are pruned by runtime maintenance (step 5 below) — not by startup.

### 5. Runtime maintenance

1. Closed sessions older than the runtime retention window are purged.
2. Session TMPDIRs and session-owned workspace directories are reconciled against live DB session truth.
3. `session_map.json` is pruned as a cache; mappings survive only when the matching DB row is open or recoverable.
4. Operational DB tables prune terminal or orphan rows after the retention window:
   `operations`, `inbound_queue`, `webhook_outbox`, `hook_outbox.db`, `session_tokens`,
   `session_listeners`, `voice_assignments`, and `voice_transcriptions` (terminal
   `succeeded`/`failed` rows; orphaned temp audio with no live row is swept alongside).
5. `events.db` prunes resolved notifications and reviewed quarantined events after the retention window while preserving unresolved work.
6. Orphaned `/tmp/teleclaude_voice/voice_*` audio files are removed only when they are old enough and no recoverable `voice_transcriptions` row still references their path.
7. Runtime SQLite files (`teleclaude.db`, `hook_outbox.db`, `events.db`) are compacted only when freelist ratio and free-byte thresholds are exceeded. `mirrors.db` is excluded.

## Failure modes

- **Lock contention**: SQLite write conflicts delay/deny writes under pressure.
- **Migration failure**: Daemon startup aborts until schema issue is fixed.
- **Outbox backlog growth**: If worker path is unhealthy, undelivered rows accumulate.
- **Disk pressure**: WAL/table/freelist growth can degrade performance or fail writes; daemon maintenance checkpoints WAL and threshold-compacts runtime SQLite files.
- **Corrupt row payload**: Outbox row is deleted (with error logging) to avoid infinite retry loops.
- **Voice audio lost before recovery**: Recovery marks the row failed and resolves the original user notice instead of silently dropping the spoken input.
