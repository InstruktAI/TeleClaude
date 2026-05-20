---
id: 'project/spec/feature/integration/hook-outbox-dispatcher'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Daemon worker that drains the SQLite hook outbox, classifies events critical vs bursty, enforces per-session backpressure with watermark hysteresis, and dispatches into the in-process EventBus.'
---

# Hook Outbox Dispatcher — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/integration.md

## What it is

The async background loop on the daemon that polls `HookOutbox`, claims
rows in batches under a lock TTL, fans out per-session work to lightweight
per-session worker tasks, and dispatches each row through one of three
mutually-exclusive paths:

1. **Session-state mutation** (`CHECKPOINT_SEEN`, `NATIVE_METADATA_UPDATE`,
   `NATIVE_SESSION_REFRESH`) → routed to in-process handlers in
   `teleclaude/core/hook_outbox_handlers.py`. No EventBus emit.
2. **`AGENT_ERROR`** → wrapped in an `ErrorEventContext` and published via
   `event_bus.emit(TeleClaudeEvents.ERROR, ..., visibility=CLUSTER)`. This
   is the ONLY EventBus emit path inside `_dispatch_hook_event`.
3. **All other agent events** (`AGENT_SESSION_START`, `USER_PROMPT_SUBMIT`,
   `TOOL_USE`, `AGENT_STOP`) → built into an `AgentEventContext` and
   passed directly to `await self._handle_agent_event(AGENT_EVENT, context)`.
   `_handle_agent_event` is awaited in-line (NOT fire-and-forget through
   the EventBus) so that the per-session outbox worker only marks the
   row delivered after the coordinator finishes.

The dispatcher exists because hook events are emitted from a short-lived
subprocess and must reach the daemon's in-process state machinery durably.

The dispatcher applies three layers of policy: **staleness eviction**
(non-lifecycle rows older than `HOOK_OUTBOX_STALENESS_TTL_S` are deleted
without processing), **event classification** (`critical` vs `bursty` —
critical events bypass capacity throttling and reserve queue slots), and
**watermark hysteresis** (per-session claim pause when queue depth exceeds
high watermark; resumes only after drainage past low watermark).

## Canonical fields

### Use cases

#### UC-D1: Normal claim → dispatch → delete

```gherkin
Given a HookOutbox row exists with locked_at IS NULL and next_attempt_at <= now
When the worker's polling tick runs
Then fetch_hook_outbox_batch returns the row
And claim_hook_outbox_batch atomically sets locked_at = now (or refuses if another worker beat it)
And the row is enqueued into the per-session HookOutboxSessionQueue.pending
And the per-session worker task picks it up
And _dispatch_hook_event is invoked
And on success, delete_hook_outbox_row removes the row from SQLite
And _hook_outbox_processed_count is incremented
```

#### UC-D2: Stale non-lifecycle event evicted

```gherkin
Given a HookOutbox row with event_type=TOOL_USE has created_at older than 300 seconds (HOOK_OUTBOX_STALENESS_TTL_S)
When _is_stale_outbox_row evaluates the row during the polling tick
And the event_type is not in HOOK_EVENT_STALENESS_EXEMPT (AGENT_SESSION_START, AGENT_STOP, AGENT_ERROR)
Then the row is deleted without dispatch
And _hook_outbox_stale_dropped_count is incremented
And a summary log records the drop
```

#### UC-D3: Critical event reserves capacity

```gherkin
Given a session's pending queue is at HOOK_OUTBOX_SESSION_MAX_PENDING - 1
And a critical event (AGENT_STOP) arrives via claim
Then it is accepted into pending despite being at capacity
And future bursty events are rejected/coalesced because HOOK_OUTBOX_SESSION_CRITICAL_RESERVE slots are reserved
```

#### UC-D4: Bursty same-type coalesce inside the daemon queue

```gherkin
Given the per-session pending queue has a bursty TOOL_USE item not yet dispatched
And no critical event sits after it in pending
When another TOOL_USE arrives via claim
Then _find_bursty_coalesce_index locates the existing TOOL_USE
And the new item replaces the old in pending (same slot)
And the displaced row id is added to delete-on-coalesce list
And _hook_outbox_coalesced_count is incremented
```

#### UC-D5: Watermark hysteresis pauses claims

```gherkin
Given a session's depth (pending + in-flight) >= HOOK_OUTBOX_SESSION_CLAIM_HIGH_WATERMARK
When _should_pause_hook_outbox_claims evaluates the session
Then the session is added to _hook_outbox_claim_paused_sessions
And subsequent fetch_hook_outbox_batch calls exclude paused sessions
And claims resume only after depth drops to <= HOOK_OUTBOX_SESSION_CLAIM_LOW_WATERMARK
```

#### UC-D6: Session-state-mutation events bypass EventBus

```gherkin
Given a claimed row has event_type in {CHECKPOINT_SEEN, NATIVE_METADATA_UPDATE, NATIVE_SESSION_REFRESH}
When _dispatch_hook_event runs
Then _handle_session_state_mutation_event returns True
And the corresponding handler in teleclaude/core/hook_outbox_handlers.py is invoked
And the row is deleted on success
And NO EventBus emit happens for these rows
```

#### UC-D6b: Non-error agent events use direct coordinator call

```gherkin
Given a claimed row has event_type in {AGENT_SESSION_START, USER_PROMPT_SUBMIT, TOOL_USE, AGENT_STOP}
When _dispatch_hook_event runs past the state-mutation fork
Then build_agent_payload(event_type, data) constructs the typed payload
And AgentEventContext(session_id, event_type, data) is built
And self._handle_agent_event(TeleClaudeEvents.AGENT_EVENT, context) is awaited DIRECTLY
And the outbox worker only marks the row delivered AFTER _handle_agent_event returns
And NO event_bus.emit call is made for this path (the comment in source notes "Directly await coordinator — outbox serialization depends on this completing before the item is marked delivered. event_bus.emit would fire-and-forget.")
```

#### UC-D6c: AGENT_ERROR is the only EventBus emit path

```gherkin
Given a claimed row has event_type == AGENT_ERROR
When _dispatch_hook_event runs past the state-mutation fork
Then severity, retryable, code, details, message are extracted from data
And an ErrorEventContext is constructed with those fields plus session_id
And event_bus.emit(TeleClaudeEvents.ERROR, context, visibility=EventVisibility.CLUSTER) is invoked
And any cluster subscriber to ERROR receives the event asynchronously
And the row is then deleted by the worker as processed
```

#### UC-D7: Retry with exponential backoff on retryable failure

```gherkin
Given _dispatch_hook_event raises a retryable exception (any error other than ValueError "not found" or JSONDecodeError "Extra data")
When the worker catches the exception
Then attempt_count is incremented
And next_attempt_at = now + _hook_outbox_backoff(attempt) (base 1s, doubling, capped at 60s)
And mark_hook_outbox_failed records last_error
And locked_at is cleared so a later poll re-claims the row
```

#### UC-D8: Missing-session non-start row logs and deletes (no exception)

````gherkin
Given a claimed row has event_type != AGENT_SESSION_START
And db.get_session(session_id) returns None for that session
When _dispatch_hook_event evaluates the guard
Then it logs "Ignoring hook event for unknown session (not session_start)" at debug
And returns normally (no exception raised)
And the outbox worker treats the dispatch as successful
And delete_hook_outbox_row removes the row
And _hook_outbox_processed_count is incremented
The row is NOT classified as a non-retryable failure; the deletion follows the normal "processed successfully" path.

#### UC-D8b: Non-retryable failures still drop on actual non-retryable errors

```gherkin
Given _dispatch_hook_event raises a ValueError whose message contains "not found", OR a JSONDecodeError with "Extra data"
When _is_retryable_hook_error returns False
Then logger.error("Hook outbox event dropped (non-retryable)", row_id, attempt, error) is emitted
And delete_hook_outbox_row removes the row without retry
And _hook_outbox_processed_count is incremented
This branch covers payload-corruption type errors, not missing-session non-start rows (which are silent).
````

#### UC-D9: Periodic summary log

```gherkin
Given HOOK_OUTBOX_SUMMARY_INTERVAL_S elapses since the last summary
And processed_count, coalesced_count, stale_dropped_count, or queue_depth is non-zero
When _maybe_log_hook_outbox_summary runs
Then an INFO log "Hook outbox summary" emits with processed, coalesced, stale_dropped, queue_depth, p95/p99 lag samples
And _hook_outbox_last_summary_at is updated
```

### Implementation pointers (v1)

- `teleclaude/daemon_hook_outbox.py` — `_DaemonHookOutboxMixin` (L106):
  `_hook_outbox_worker` (L550, poll loop),
  `_dispatch_hook_event` (L442),
  `_handle_session_state_mutation_event` (L422),
  `_is_stale_outbox_row` (L174),
  `_classify_hook_event` (L192),
  `_find_bursty_coalesce_index` (L211),
  `_should_pause_hook_outbox_claims` (L248),
  `_hook_outbox_backoff` (L351),
  `_is_retryable_hook_error` (L357),
  `_maybe_log_hook_outbox_summary` (L316),
  `_record_hook_lag_sample` (L281),
  `_process_outbox_item` (L873).
- `teleclaude/core/hook_outbox_queue.py` — `HookOutboxQueueItem` (L13),
  `HookOutboxSessionQueue` (L22, per-session pending + claimed_row_ids + lock).
- `teleclaude/core/db/_hooks.py` — `DbHooksMixin` row mutations.
- Configuration (env-driven, see file head):
  `HOOK_OUTBOX_POLL_INTERVAL_S=1`,
  `HOOK_OUTBOX_BATCH_SIZE=25`,
  `HOOK_OUTBOX_LOCK_TTL_S=30`,
  `HOOK_OUTBOX_BASE_BACKOFF_S=1`,
  `HOOK_OUTBOX_MAX_BACKOFF_S=60`,
  `HOOK_OUTBOX_SESSION_MAX_PENDING=32`,
  `HOOK_OUTBOX_SESSION_CRITICAL_RESERVE=8`,
  `HOOK_OUTBOX_STALENESS_TTL_S=300`.
- Event classes:
  `HOOK_EVENT_CLASS_CRITICAL = {AGENT_SESSION_START, USER_PROMPT_SUBMIT,
AGENT_STOP, AGENT_ERROR, CHECKPOINT_SEEN, NATIVE_METADATA_UPDATE,
NATIVE_SESSION_REFRESH}`;
  `HOOK_EVENT_CLASS_BURSTY = {TOOL_USE}`.

### Cross-context references

- Consumes from `hook-event-outbox` (this context, v1 in-context;
  agent_runtime in v2).
- Emits in-process EventBus events that domain contexts subscribe to:
  `AGENT_EVENT`, `AGENT_ACTIVITY`, `SESSION_STARTED`, `SESSION_UPDATED`,
  `SESSION_CLOSED`, `ERROR`. These are the same EventBus events the
  `eventbus-hook-bridge` re-normalizes into HookEvents for the matcher.
- Invokes `headless-session-bootstrap-from-hook` when an
  `AGENT_SESSION_START` arrives for a session that does not yet exist in
  the sessions table.
- Routes mutation rows to `session-state-mutation-via-outbox` handlers.

## Known caveats

- Watermark constants are clamped at startup: HIGH watermark is capped at
  MAX_PENDING, LOW is capped at HIGH-1, CRITICAL_RESERVE is clamped to
  [0, MAX_PENDING]. The clamping logs a constant-redefinition pyright
  suppression — intentional one-time normalization.
- Coalescing inside the daemon queue runs AFTER the receiver's coalesce
  window. Both layers exist because the receiver coalesces within ~1s
  burst windows; the daemon coalesces unclaimed bursty items that piled
  up while the worker was busy. They compose without double-counting.
- The "deployment fanout" Redis stream consumer is a separate worker
  task (see `deployment-version-fanout`); it does NOT consume from the
  hook outbox.
- Failure of a session-state-mutation handler is retried alongside normal
  dispatch retries; the handler is expected to be idempotent. v1 handlers
  use last-wins semantics on the session row, so retries converge.
- Lag samples are kept in-memory only (cap `HOOK_OUTBOX_MAX_LAG_SAMPLES =
2048`); the daemon does not persist or export them beyond the periodic
  summary log.
- `_hook_outbox_worker` is one task per daemon; per-session workers are
  spawned on demand and torn down after `HOOK_OUTBOX_SESSION_IDLE_TIMEOUT_S`.
