---
description: 'Integration-service worker that drains the hook outbox, classifies events critical vs bursty, enforces per-session backpressure with watermark hysteresis, and dispatches into the in-process event bus.'
visibility: 'public'
---

# Hook Outbox Dispatcher — Spec

## What it is

<!-- planned-change:antigravity-native-subagents-allowed -->

The background loop in the integration service that polls the hook
outbox, claims entries in batches under a lock TTL, fans out per-session
work to lightweight per-session worker tasks, and dispatches each entry
through one of three mutually-exclusive paths:

1. **Session-state mutation** (checkpoint-seen, native-metadata-update,
   native-session-refresh) → routed to in-process mutation handlers. No
   event-bus emit.

2. **Agent-error** → handed to the runtime's error-publication capability,
   preserving the error's existing reach and failure contract under
   `local/projects/teleclaude/design/architecture/event-delivery`. The outbox
   entry settles only after the runtime accepts publication; a publication
   failure remains eligible for the existing retry contract.

3. **All other agent events** (agent-session-start, user-prompt-submit,
   tool-use, agent-stop) → built into an agent-event context and passed
   directly to the local agent-event coordinator. The coordinator is
   awaited in-line (NOT fire-and-forget through the event bus) so that
   the per-session outbox worker only marks the entry delivered after
   the coordinator finishes.

<!-- change:antigravity-native-subagents-allowed -->

The background loop in the integration service that polls the hook
outbox, claims entries in batches under a lock TTL, fans out per-session
work to lightweight per-session worker tasks, and dispatches each entry
through one of four mutually-exclusive paths:

1. **Session-state mutation** (checkpoint-seen, native-metadata-update,
   native-session-refresh) → routed to in-process mutation handlers. No
   event-bus emit.

2. **Agent-error** → handed to the runtime's error-publication capability,
   preserving the error's existing reach and failure contract under
   `local/projects/teleclaude/design/architecture/event-delivery`. The outbox
   entry settles only after the runtime accepts publication; a publication
   failure remains eligible for the existing retry contract.

3. **All other agent events** (agent-session-start, user-prompt-submit,
   tool-use, agent-stop) → built into an agent-event context and passed
   directly to the local agent-event coordinator. The coordinator is
   awaited in-line (NOT fire-and-forget through the event bus) so that
   the per-session outbox worker only marks the entry delivered after
   the coordinator finishes.

4. **Checkpoint relay** → handed to control delivery as a checkpoint payload
   for the entry's session
   (`local/projects/teleclaude/design/architecture/checkpoint-system`). No
   event-bus emit. A checkpoint-relay entry is a lifecycle entry of the
   critical class: it is never evicted for staleness, throttled or coalesced,
   and it settles only once control delivery has accepted the handoff; a
   refused handoff is retryable.

<!-- /planned-change:antigravity-native-subagents-allowed -->

The dispatcher exists because hook events are emitted from a short-lived
subprocess and must reach the integration service's in-process state
machinery durably.

The dispatcher applies three layers of policy: **staleness eviction**
(non-lifecycle entries older than the staleness TTL are deleted without
processing), **event classification** (critical vs bursty — critical
events bypass capacity throttling and reserve queue slots), and
**watermark hysteresis** (per-session claim pause when queue depth
exceeds the high watermark; resumes only after drainage past the low
watermark).

Settlement distinguishes retryable failures, which are deferred for another
attempt, from non-retryable failures, which are logged and dropped. An
unknown-session event other than an authorized agent-session-start is ignored
and settled successfully; a shutdown refusal leaves the entry pending for
retry.

## Canonical fields

### Use cases

#### UC-D1: Normal claim → dispatch → delete

#### UC-D2: Stale non-lifecycle event evicted

#### UC-D3: Critical event reserves capacity

#### UC-D4: Bursty same-type coalesce inside the dispatcher queue

#### UC-D5: Watermark hysteresis pauses claims

#### UC-D6: Session-state-mutation events bypass the event bus

#### UC-D6b: Non-error agent events use direct coordinator call

#### UC-D6c: Agent-error publication precedes outbox settlement

#### UC-D7: Retry with exponential backoff on retryable failure

#### UC-D8: Missing-session non-start entry logs and removes (no exception)

#### UC-D8b: Non-retryable failures still drop on actual non-retryable errors

#### UC-D9: Periodic summary log

### Cross-context references

- Consumes from `hook-event-outbox` (this context, v1 in-context;
  `agent_runtime` in v2).

- Hands normalized runtime signals to `agent_runtime`; its completion and
  notification boundaries are defined by
  `local/projects/teleclaude/spec/feature/agent_runtime/daemon-lifecycle`.

- Invokes `headless-session-bootstrap-from-hook` when an
  agent-session-start arrives for a session that does not yet exist in
  the sessions store.
- Routes mutation entries to `session-state-mutation-via-outbox`
  handlers.

## Known caveats

- Watermark constants are clamped at startup: HIGH is capped at MAX
  PENDING, LOW is capped at HIGH-1, CRITICAL RESERVE is clamped to
  [0, MAX PENDING]. The clamping is intentional one-time normalization.
- Coalescing inside the dispatcher queue runs AFTER the receiver's
  coalesce window. Both layers exist because the receiver coalesces
  within ~1s burst windows; the dispatcher coalesces unclaimed bursty
  items that piled up while the worker was busy. They compose without
  double-counting.

- Failure of a session-state-mutation handler is retried alongside
  normal dispatch retries; the handler is expected to be idempotent. v1
  handlers use last-wins semantics on the session record, so retries
  converge.
- Lag samples are kept in-memory only (bounded by a sample cap); the
  integration service does not persist or export them beyond the
  periodic summary log.
- The outbox worker is one task per integration service; per-session
  workers are spawned on demand and torn down after an idle timeout.
