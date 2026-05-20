---
id: 'project/spec/feature/integration/session-state-mutation-via-outbox'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Hook outbox events that mutate session-row state directly — checkpoint timestamps, native session/transcript binding, transcript history chain — without producing in-process EventBus events.'
---

# Session State Mutation via Outbox — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/integration.md

## What it is

A subset of hook outbox event types (`CHECKPOINT_SEEN`,
`NATIVE_METADATA_UPDATE`, `NATIVE_SESSION_REFRESH`) whose only effect is to
update fields on the session row. The hook outbox dispatcher routes these to
in-process handlers BEFORE the generic EventBus dispatch path. Unlike normal
hook events, they do NOT produce internal EventBus events; they are pure
state-keeping operations that ride the outbox to gain durability and ordering
across daemon restarts.

The most behaviorally interesting handler is `NATIVE_METADATA_UPDATE`, which
appends the previously stored `native_log_file` to a JSON list in
`transcript_files` whenever the transcript path changes. This produces an
in-order history of every transcript file the session ever used —
essential for session resume and Codex-style transcript chaining.

## Canonical fields

### Use cases

#### UC-SSM1: checkpoint_seen updates last_checkpoint_at

```gherkin
Given the receiver emitted a CHECKPOINT_SEEN row with checkpoint_at = "2026-05-19T10:00:00+00:00"
When the daemon worker dispatches the row
Then _handle_session_state_mutation_event detects CHECKPOINT_SEEN
And handle_checkpoint_seen calls db.update_session(session_id, last_checkpoint_at="2026-05-19T10:00:00+00:00")
And the row is deleted from the outbox
And NO EventBus event is emitted for this transition
```

#### UC-SSM2: native_metadata_update with new transcript path archives the old

```gherkin
Given the session row has native_log_file = "/var/log/claude/abc.jsonl"
And NATIVE_METADATA_UPDATE arrives with native_log_file = "/var/log/claude/def.jsonl"
When handle_native_metadata_update runs
Then it loads the session row
And detects the new path differs from the stored path
And _append_transcript_history reads the existing transcript_files JSON list
And appends "/var/log/claude/abc.jsonl" to the list (if not already present)
And serializes the chain back to transcript_files
And updates native_log_file to "/var/log/claude/def.jsonl"
And persists both fields atomically via db.update_session
```

#### UC-SSM3: native_metadata_update is a no-op when nothing changed

```gherkin
Given NATIVE_METADATA_UPDATE arrives with values identical to current session row state
When handle_native_metadata_update runs
Then no field in `updates` is set
And db.update_session is NOT invoked (early-exit when updates is empty)
And the row is still deleted from the outbox as successful processing
```

#### UC-SSM4: native_metadata_update on missing session is a no-op

```gherkin
Given handle_native_metadata_update is invoked for a session_id that does not exist
When db_handle.get_session returns None
Then the handler returns silently
And no error is raised
And the row is deleted as processed
```

#### UC-SSM5: native_session_refresh sets native_session_id directly

```gherkin
Given the receiver detected a native_session_id mismatch and emitted NATIVE_SESSION_REFRESH
When handle_native_session_refresh runs
Then it confirms the payload contains the "native_session_id" key
And invokes db_handle.update_session(session_id, native_session_id=<value>)
And the row is deleted from the outbox
```

#### UC-SSM6: native_session_refresh with null clears the binding

```gherkin
Given a NATIVE_SESSION_REFRESH row with payload {"native_session_id": null}
When handle_native_session_refresh runs
Then it calls db.update_session(session_id, native_session_id=None)
And the session row's native_session_id is cleared
```

#### UC-SSM7: agent rename on metadata update

```gherkin
Given a NATIVE_METADATA_UPDATE payload includes "agent": "codex"
And the session row's active_agent is "claude"
When handle_native_metadata_update runs
Then updates["active_agent"] = "codex"
And the session row's active_agent flips to "codex"
And the transcript chain rule fires separately if the transcript path also changed
```

#### UC-SSM8: Closed-session-guard bypass

```gherkin
Given the session's lifecycle_status is "closed"
And a NATIVE_METADATA_UPDATE row arrives
When _dispatch_hook_event runs
Then _handle_session_state_mutation_event runs FIRST (before the closed-session guard)
And the row is processed even though the session is closed
And the "Ignoring hook event for closed session" guard only fires for non-mutation rows
```

### Implementation pointers (v1)

- `teleclaude/core/hook_outbox_handlers.py` —
  `handle_checkpoint_seen` (L41),
  `handle_native_metadata_update` (L53),
  `handle_native_session_refresh` (L87),
  `_append_transcript_history` (L29),
  `optional_payload_str_value` (L23).
- `teleclaude/daemon_hook_outbox.py` —
  `_handle_session_state_mutation_event` (L422),
  the dispatch fork-point inside `_dispatch_hook_event` (L442) at the
  `if await self._handle_session_state_mutation_event(...)` line.
- `teleclaude/core/events.py` — `AgentHookEvents.CHECKPOINT_SEEN`,
  `NATIVE_METADATA_UPDATE`, `NATIVE_SESSION_REFRESH`.

### Cross-context references

- Producer is `agent-cli-hook-reception` (receiver emits these via
  `enqueue_checkpoint_seen` and `_persist_native_metadata`).
- Carrier is `hook-event-outbox` and `hook-outbox-dispatcher`.
- Consumer is the `agent_runtime` session row (v2 destination); v1 stores
  in the SQLite `sessions` table via the `SessionMutationDb` protocol.

## Known caveats

- The `transcript_files` chain is a JSON list serialized into a TEXT
  column; the handler defensively handles `None`/invalid JSON by treating
  the chain as empty.
- The handler deduplicates within the chain (appended only if the
  previous path is not already in the list) — but does NOT reorder; the
  list is append-only chronological order of replacements.
- These events deliberately bypass `EventVisibility.CLUSTER` propagation
  because they are an internal pre-event-bus state-keeping operation.
  Domain consumers who care about checkpoint timing should subscribe to
  the downstream EventBus event the next live update emits, not the
  outbox row.
- `handle_native_metadata_update` does NOT clear stale fields; it only
  applies non-empty string values from the payload.
- Idempotency comes from last-wins semantics — multiple identical updates
  converge on the same row state, so the daemon worker's retry loop is
  safe.
