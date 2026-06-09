---
id: project/spec/feature/agent_runtime/windowed-batch-write-and-dispatch
type: spec
domain: software-development
scope: project
visibility: public
delivered_by: [v2-agent-runtime]
description: Windowed batched write + change-notification dispatch for agent CLI hook events. Producer-side write coalescing with zero added latency on the publish path.
---

# Windowed Batch Write and Dispatch — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/agent_runtime.md

## What it is

The producer-side write batching + asynchronous dispatch mechanism that agent_runtime uses to handle high-frequency hook events from agent CLIs without overwhelming the durable store or the event bus. Three coordinated parts:

1. **Window collection** — incoming hook events are coalesced per session id in a short time window (~1s).
2. **Batched write** — at window tick (or urgent flush), a single transaction updates all affected sessions.
3. **Change-notification dispatch** — a trigger on the sessions store fires a notification on commit; a separate worker subscribes and publishes batched events with the updated records as payload.

The writer's transaction commits and returns. Event publication happens asynchronously in a different process. The writer NEVER pays the event-emission cost on the hot path.

This mechanism is producer-side; consumer-side batching (if needed) is a separate optimization layered on top.

## Canonical fields

### Use cases

#### Window collection

```
Given an agent CLI hook event arrives at the agent_runtime service via inter-process delivery from the hook shim
When the service processes the event
Then the event is added to the current window's dirty-set, keyed by session id
And multiple events for the same session in the same window are coalesced (latest-wins or commutative-merge per field)
And no durable write happens at this point
```

#### Window tick (normal flush)

```
Given the window timer ticks (configurable, default ~1s)
And the dirty-set is non-empty
When the window flush executes
Then a single transaction opens
And executes one batched update for all affected sessions (one statement, set-based update over dirty session ids)
And the trigger on the sessions store fires a change notification on commit naming the affected session ids
And the transaction commits
And the dirty-set is cleared
And a new window begins
```

#### Urgent flush (latency-sensitive hooks)

```
Given an agent CLI hook of kind agent_stop OR session_end arrives
When the hook receiver classifies the event as urgent
Then the current window is flushed IMMEDIATELY (without waiting for the timer tick)
And the batched write executes
And the change notification fires
And consumers see the urgent event with minimal latency
And the window restarts fresh
```

#### Change-notification dispatch

```
Given the event-publisher worker is subscribed to the session-changed notification channel
When the notification fires with affected session ids
Then the worker receives the notification asynchronously (writer already returned)
And the worker reads the session records for those session ids (single batched read)
And constructs a batched event with the records as payload
And publishes the event (CLUSTER visibility)
And consumers receive the batched event and iterate
```

#### Backstop poll (listener recovery)

```
Given the event-publisher worker is disconnected from the durable store (worker crashed, restarting)
And notifications fired during the disconnect are lost (the notification channel does not queue)
When the worker reconnects
Then every N seconds (default 5s), the worker also runs:
  read every session record with `updated_at > $last_published_at`
And publishes a batched event with any records found
And advances last_published_at
And duplicates from notify + poll overlap are deduped by consumers via (session_id, updated_at)
```

#### Durability under crash

```
Given the agent_runtime service crashes mid-window (events in dirty-set, not yet flushed)
When the service restarts
Then the dirty-set is LOST (in-memory only)
And the lost events are NOT recovered
And this is the accepted trade-off — the hook shim does NOT retry beyond its ~10s window
And the agent CLI does NOT replay hooks
And render lane + transcript lane safety nets reconstruct live observability
And the next hook for an affected session catches the state forward
```

```
Given the agent_runtime service crashes mid-write (window flushed, transaction in progress)
When the service restarts
Then the transaction is atomic — either fully committed or fully rolled back
And no partial state exists
And on commit, the change notification fires; on rollback, no notification
And consumers see only committed state
```

#### Idempotency of batched writes

```
Given the same hook event is processed twice (e.g., the hook shim retried after a transient service hiccup)
When the batched write executes for both
Then the operations are commutative (timestamps merge latest-wins; counter fields are not double-incremented because hook payloads carry the absolute count)
And the resulting session state is correct
And no duplicate events are emitted (notification dedup via (session_id, updated_at))
```

### Cross-context references

- Producer of events consumed: the agent_runtime hook receiver (receives from the hook shim subprocess via inter-process delivery)
- Consumers: any subscriber to `agent_runtime.session.started` / `session.updated` / `agent_runtime.session.ended` events (frontend, session_mirrors at session-end, etc.)
- Coordinates with: `transport-rules.md` (the change-axis test placing agent CLI hooks in agent_runtime; the "durable store → event bus dispatch" pattern)

## Allowed values

- Window size (default): 1 second. Configurable via `polling.window_size_ms`.
- Urgent hook kinds (default): `agent_stop`, `session_end`. Extensible via config.
- Backstop poll interval (default): 5 seconds. Configurable.

## Known caveats

- **Up to one window of hooks lost on service crash.** Acceptable per design — agent CLIs don't replay; render lane + transcript lane recover live state.
- **Notification payloads are bounded.** The notification carries only session ids; the listener reads the actual records. This is by design to keep notifications small.
- **Backstop poll has 5s lag on recovery.** A crash + restart during peak activity may delay some events by up to one poll interval. Acceptable; the data is durable.
- **Consumers must dedup** on `(session_id, updated_at)` because the backstop poll may overlap with notification-driven publishes during recovery.
- **The window collects ALL hooks for ALL sessions** — no per-session windows. One global timer + one global dirty-set keyed by session id.
- **`session_end` and `agent_stop` are urgent for different reasons.** session_end carries the native transcript file path needed by session_mirrors for extraction; delay impacts mirror-extraction freshness. agent_stop is UI-critical; users need to see the agent finished. Both bypass the window.
