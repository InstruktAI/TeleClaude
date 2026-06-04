---
id: 'project/spec/feature/integration/hook-outbox-dispatcher'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Integration-service worker that drains the hook outbox, classifies events critical vs bursty, enforces per-session backpressure with watermark hysteresis, and dispatches into the in-process event bus.'
---

# Hook Outbox Dispatcher — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/integration.md

## What it is

The background loop in the integration service that polls the hook
outbox, claims entries in batches under a lock TTL, fans out per-session
work to lightweight per-session worker tasks, and dispatches each entry
through one of three mutually-exclusive paths:

1. **Session-state mutation** (checkpoint-seen, native-metadata-update,
   native-session-refresh) → routed to in-process mutation handlers. No
   event-bus emit.
2. **Agent-error** → wrapped in an error event context and published on
   the event bus with cluster visibility. This is the ONLY event-bus
   emit path inside the dispatcher.
3. **All other agent events** (agent-session-start, user-prompt-submit,
   tool-use, agent-stop) → built into an agent-event context and passed
   directly to the local agent-event coordinator. The coordinator is
   awaited in-line (NOT fire-and-forget through the event bus) so that
   the per-session outbox worker only marks the entry delivered after
   the coordinator finishes.

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

## Canonical fields

### Use cases

#### UC-D1: Normal claim → dispatch → delete

```gherkin
Given an outbox entry exists with no claim lock and next-attempt-at <= now
When the worker's polling tick runs
Then a fetch-batch call returns the entry
And a claim-batch call atomically sets the claim lock (or refuses if another worker beat it)
And the entry is enqueued into the per-session pending queue
And the per-session worker task picks it up
And the dispatcher runs
And on success, the entry is removed from the outbox
And the processed-count metric is incremented
```

#### UC-D2: Stale non-lifecycle event evicted

```gherkin
Given an outbox entry with event type tool-use has creation timestamp older than the staleness TTL (300 seconds)
When the staleness check evaluates the entry during the polling tick
And the event type is not in the staleness-exempt set (agent-session-start, agent-stop, agent-error)
Then the entry is removed without dispatch
And the stale-dropped metric is incremented
And a summary log records the drop
```

#### UC-D3: Critical event reserves capacity

```gherkin
Given a session's pending queue is at maximum pending minus one
And a critical event (agent-stop) arrives via claim
Then it is accepted into pending despite being at capacity
And future bursty events are rejected or coalesced because the critical-reserve slots are reserved
```

#### UC-D4: Bursty same-type coalesce inside the dispatcher queue

```gherkin
Given the per-session pending queue has a bursty tool-use item not yet dispatched
And no critical event sits after it in pending
When another tool-use arrives via claim
Then the bursty-coalesce probe locates the existing tool-use
And the new item replaces the old in pending (same slot)
And the displaced entry id is added to the delete-on-coalesce list
And the coalesced-count metric is incremented
```

#### UC-D5: Watermark hysteresis pauses claims

```gherkin
Given a session's depth (pending + in-flight) >= the high watermark
When the pause guard evaluates the session
Then the session is added to the paused set
And subsequent fetch-batch calls exclude paused sessions
And claims resume only after depth drops to <= the low watermark
```

#### UC-D6: Session-state-mutation events bypass the event bus

```gherkin
Given a claimed entry has event type in {checkpoint-seen, native-metadata-update, native-session-refresh}
When the dispatcher runs
Then the session-state-mutation fork accepts the entry
And the corresponding mutation handler is invoked
And the entry is removed on success
And NO event-bus emit happens for these entries
```

#### UC-D6b: Non-error agent events use direct coordinator call

```gherkin
Given a claimed entry has event type in {agent-session-start, user-prompt-submit, tool-use, agent-stop}
When the dispatcher runs past the state-mutation fork
Then a typed agent payload is constructed for the event type
And an agent-event context is built
And the local agent-event coordinator is awaited DIRECTLY
And the outbox worker only marks the entry delivered AFTER the coordinator returns
And NO event-bus emit call is made for this path — outbox serialization depends on the coordinator completing before the entry is marked delivered; a fire-and-forget event-bus emit would not provide that guarantee
```

#### UC-D6c: Agent-error is the only event-bus emit path

```gherkin
Given a claimed entry has event type agent-error
When the dispatcher runs past the state-mutation fork
Then severity, retryable, code, details, and message are extracted from the payload
And an error event context is constructed with those fields plus the session id
And the event bus emits the error event with cluster visibility
And any cluster subscriber to error receives the event asynchronously
And the entry is then removed by the worker as processed
```

#### UC-D7: Retry with exponential backoff on retryable failure

```gherkin
Given the dispatcher raises a retryable exception (any error other than a "not found" value error or an "extra data" decoding error)
When the worker catches the exception
Then the attempt count is incremented
And next-attempt-at = now + the configured backoff for that attempt (base 1s, doubling, capped at 60s)
And the entry is marked failed with the last error recorded
And the claim lock is cleared so a later poll re-claims the entry
```

#### UC-D8: Missing-session non-start entry logs and removes (no exception)

````gherkin
Given a claimed entry has event type != agent-session-start
And the sessions store has no record for that session id
When the dispatcher evaluates the guard
Then it logs "ignoring hook event for unknown session (not session_start)" at debug
And returns normally (no exception raised)
And the outbox worker treats the dispatch as successful
And the entry is removed
And the processed-count metric is incremented
The entry is NOT classified as a non-retryable failure; the removal follows the normal "processed successfully" path.

#### UC-D8b: Non-retryable failures still drop on actual non-retryable errors

```gherkin
Given the dispatcher raises a value error whose message contains "not found", OR a decoding error with "extra data"
When the retryable-error classifier returns false
Then an error "hook outbox event dropped (non-retryable)" is emitted with entry id, attempt, and error
And the entry is removed without retry
And the processed-count metric is incremented
This branch covers payload-corruption type errors, not missing-session non-start entries (which are silent).
````

#### UC-D9: Periodic summary log

```gherkin
Given the summary interval elapses since the last summary
And processed-count, coalesced-count, stale-dropped-count, or queue depth is non-zero
When the summary helper runs
Then an INFO "hook outbox summary" log emits with processed, coalesced, stale-dropped, queue depth, p95/p99 lag samples
And the last-summary timestamp is updated
```

### Cross-context references

- Consumes from `hook-event-outbox` (this context, v1 in-context;
  `agent_runtime` in v2).
- Emits in-process event-bus events that domain contexts subscribe to:
  agent-event, agent-activity, session-started, session-updated,
  session-closed, error. These are the same event-bus events the
  `eventbus-hook-bridge` re-normalizes into hook events for the matcher.
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
- The deployment-fanout cross-host consumer is a separate worker task
  (see `deployment-version-fanout`); it does NOT consume from the hook
  outbox.
- Failure of a session-state-mutation handler is retried alongside
  normal dispatch retries; the handler is expected to be idempotent. v1
  handlers use last-wins semantics on the session record, so retries
  converge.
- Lag samples are kept in-memory only (bounded by a sample cap); the
  integration service does not persist or export them beyond the
  periodic summary log.
- The outbox worker is one task per integration service; per-session
  workers are spawned on demand and torn down after an idle timeout.
