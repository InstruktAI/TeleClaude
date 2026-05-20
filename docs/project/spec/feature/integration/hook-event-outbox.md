---
id: 'project/spec/feature/integration/hook-event-outbox'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Per-session SQLite outbox between the telec-hook subprocess and the daemon, providing durable, coalesced, retry-safe transport for agent CLI hook events.'
---

# Hook Event Outbox — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/integration.md

## What it is

The SQLite-backed write-ahead queue (`HookOutbox` table) that decouples
short-lived `telec-hook` subprocesses from the long-running TeleClaude daemon.
The subprocess writes one row per accepted hook event; the daemon's hook
outbox worker (see `hook-outbox-dispatcher`) claims, dispatches, and deletes
those rows. The outbox is the only durable contract point between the agent
CLI process tree and the daemon — both sides survive across daemon restarts
and across long-running agent sessions.

The receiver-side writer carries one extra responsibility: a per-(session_id,
event_type) **latest-wins coalesce window**. Within the window, a new emit
for the same key overwrites the prior unclaimed row in place (payload +
timestamp updated, `attempt_count` reset, `last_error` cleared) instead of
inserting. Claimed rows are never replaced.

## Canonical fields

### Use cases

#### UC-OB1: Plain enqueue (no coalesce)

```gherkin
Given the receiver has resolved a TeleClaude session id
And the event type has no coalesce window
When enqueue_hook_event is called with session_id, event_type, payload, outbox_db
Then a new HookOutbox row is inserted with created_at = next_attempt_at = now, attempt_count = 0, locked_at = NULL
And the row is committed before the subprocess exits
```

#### UC-OB2: Coalesce overwrites prior unclaimed row

```gherkin
Given an unclaimed HookOutbox row exists for (session_id, AgentHookEvents.TOOL_USE) with created_at within 1.0 second
When enqueue_hook_event is called for the same key with latest_wins_within_s = 1.0
Then a SELECT inside the same transaction finds the prior row
And the existing row's payload is overwritten with the new payload_json
And created_at, next_attempt_at are set to now
And attempt_count is reset to 0, last_error to None
And no INSERT happens
And no second row is created
```

#### UC-OB3: Coalesce skipped when prior row is claimed

```gherkin
Given an in-flight HookOutbox row exists for (session_id, event_type) with locked_at != NULL
When enqueue_hook_event runs with a coalesce window
Then the WHERE locked_at IS NULL filter excludes the in-flight row
And a NEW row is inserted alongside the in-flight one
And both will be processed by the daemon worker
```

#### UC-OB4: Codex agent_stop uses a wider 10s coalesce window

```gherkin
Given args.agent == "codex" and event_type == AGENT_STOP
When the receiver computes debounce_window_s
Then debounce_window_s = _CODEX_NOTIFY_DEBOUNCE_WINDOW_S (10.0) — overriding the 1.0s baseline
And the wider window absorbs the burst of stop events Codex emits per turn
```

#### UC-OB5: NATIVE_METADATA_UPDATE coalesces at 1s baseline

```gherkin
Given the receiver writes NATIVE_METADATA_UPDATE on every hook that carries native_session_id or native_log_file
When two updates land in the same second
Then the second overwrites the first
And only one row is dispatched to the daemon for that window
```

#### UC-OB6: Outbox DB path resolution

```gherkin
Given the receiver needs an outbox DB path
When _get_default_outbox_db is called
Then get_outbox_db_path(TELECLAUDE_HOME) returns the canonical SQLite path
And the subprocess opens its own SQLAlchemy engine against that path (no daemon connection required)
```

#### UC-OB7: Error payload requires resolvable session id

```gherkin
Given the receiver encounters a contract violation that calls _emit_receiver_error_best_effort
When the helper tries to resolve a session id via _get_cached_session_id and _find_session_id_by_native
Then if neither lookup yields a session_id:
    - the helper logs "Receiver error with unknown session" at error level
    - NO HookOutbox row is enqueued
And if a session_id IS resolved:
    - a HookOutbox row with event_type="error" is enqueued
    - the payload contains message, source="hook_receiver", code, severity="error", retryable=false
    - details include agent, event_type, code
And _parse_receiver_input's JSON-decode and value-error paths do NOT pass raw_data,
    so unknown-session parse failures always take the log-only branch above
```

### Implementation pointers (v1)

- `teleclaude/hooks/receiver/__init__.py` —
  `enqueue_hook_event` (L420),
  `enqueue_checkpoint_seen` (L468),
  `_HOOK_COALESCE_WINDOWS_S` map (L105),
  `_CODEX_NOTIFY_DEBOUNCE_WINDOW_S` (L96),
  `_serialize_outbox_payload` (L411),
  `_build_receiver_error_payload` (L207),
  `_emit_receiver_error_best_effort` (L483) — note the unknown-session
  log-only branch.
- `teleclaude/hooks/receiver/_session.py` —
  `get_outbox_session` (L96),
  `_create_sync_engine` (L76, sync SQLAlchemy engine to the outbox DB).
- `teleclaude/core/db/connection_factory.py` — `get_outbox_db_path`
  (canonical path resolution).
- `teleclaude/core/db/_hooks.py` — `DbHooksMixin` for daemon-side outbox
  CRUD: `fetch_hook_outbox_batch`, `claim_hook_outbox_batch`,
  `mark_hook_outbox_failed`, `delete_hook_outbox_row`.
- `teleclaude/core/db/_rows.py` — `HookOutboxRow` TypedDict.
- Schema: `teleclaude/core/db_models.py` `HookOutbox` table — fields
  `session_id`, `event_type`, `payload`, `created_at`, `next_attempt_at`,
  `attempt_count`, `locked_at`, `last_error`.

### Cross-context references

- Producer side belongs (in v2) to `agent_runtime` along with the receiver.
- Consumer side is `hook-outbox-dispatcher` (this context).
- The outbox pattern itself echoes the v2 transactional outbox aggregate in
  `docs/project/spec/domain/integration.md` `Outbox Entry`, but v1 uses
  SQLite (not Postgres) and a per-process writer (not a shared producer
  API).

## Known caveats

- The outbox database is SQLite; concurrent receivers may experience busy
  errors during high-frequency tool_use bursts. Coalescing the bursty
  events into 1s windows reduces lock contention.
- `latest_wins_within_s` is enforced via two queries inside one SQLAlchemy
  transaction; there is a narrow race where two receivers running in
  parallel both see no prior row and both insert. This is observable as
  occasional duplicate near-simultaneous rows — the daemon worker tolerates
  duplicates by event_type semantics.
- Coalesce candidates require `attempt_count = 0` semantics implicitly —
  rows that already failed once (`attempt_count > 0`, `last_error` set)
  also coalesce because the WHERE filter only checks `locked_at IS NULL`;
  the incoming emit effectively retries the prior failure under the new
  payload. This is intentional but undocumented in v1.
- The outbox is local to each daemon host; cross-host hook delivery is not
  supported in v1.
- The `_serialize_outbox_payload` helper accepts pre-encoded JSON strings
  for test ergonomics; production callers always pass mappings.
