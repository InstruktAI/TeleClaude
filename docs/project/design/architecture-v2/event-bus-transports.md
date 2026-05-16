---
description: 'Single-transport Redis event bus for v2. Local in-coroutine sync uses Tokio channels — not events.'
id: 'project/design/architecture-v2/event-bus-transports'
scope: 'project'
type: 'design'
---

# Event Bus Transports — Design

## Required reads

- @docs/project/design/architecture-v2/overview.md
- @docs/project/design/architecture-v2/transport-rules.md
- @docs/project/design/architecture-v2/services.md

## Purpose

Define the event bus contract for v2: one transport, one contract, one set of
guarantees. Replaces v1's dual-transport (LOCAL in-process + CLUSTER Redis)
model — that pattern is on the redesign list as the bug-factory it was.

## Inputs/Outputs

**Inputs:**

- the v2 architectural rule that services are crates consumed as SDK
- the v1 dual-transport bus and its failure modes (visibility misclassification,
  silent cross-process delivery loss)
- the actual concurrency story: Tokio + Postgres MVCC handles the writer load
  Python could not, removing the original reason for the LOCAL fast-path

**Outputs:**

- the single transport for events (Redis Streams + pub/sub)
- the local-coroutine sync primitive that is explicitly not an event
- the event naming convention
- the visibility/scope model (or lack thereof)

## Invariants

- **One transport for events: Redis.** No in-process fast-path. No "LOCAL"
  visibility. Every event goes through Redis Streams (durable events) or
  Redis pub/sub (ephemeral notifications), depending on the contract the
  channel needs.
- **In-coroutine completion signals are not events.** They use Tokio
  primitives (`oneshot`, `broadcast`, `mpsc`) and are named accordingly.
  They never use `event_bus.emit()`.
- **The bus surface is one shape.** `event_bus::emit(event)` and
  `event_bus::subscribe(channel)` have one contract: same envelope, same
  durability semantics per channel, same idempotency rules.
- **Idempotency by envelope key.** Every event carries an `idempotency_key`
  so consumer-group redelivery converges to at-most-once handler firing.
- **Cross-process delivery is the default.** Any event emitted is visible to
  any process subscribed to the channel. There is no opt-out for "local
  only."
- **Redis pool sizing is operational, not architectural.** If Redis pool
  exhausts under load, tune the pool — don't invent a second transport to
  avoid it.

## Primary flows

### The two Redis surfaces (one transport)

Redis offers two delivery mechanisms; both are part of the bus:

| Surface | Use | Durability | Replay |
|---|---|---|---|
| **Redis Streams** (`XADD`/`XREADGROUP`) | Domain events with consumer groups, retry, DLQ | Durable | Yes |
| **Redis Pub/Sub** (`PUBLISH`/`SUBSCRIBE`) | Live notifications, cache invalidation, ephemeral fanout | Ephemeral | No |

A channel's contract picks the surface:

- `workflow.todo.*` — Streams. Domain events that must be processed
  reliably; consumer groups handle scale; retries on handler failure.
- `tui.snapshot.refresh` — Pub/Sub. Live notifications to subscribed TUIs;
  fine to drop if no subscriber is alive.

The bus crate exposes both via one consistent API. Service authors specify the
surface at channel definition time (or per-emit if needed). The bus is one
transport with two delivery modes, both Redis-backed.

### What is and isn't an event

**Events** are domain facts emitted by services for other interested parties to
react to:
- `workflow.todo.created`
- `agent_runtime.session.started`
- `identity.token.issued`
- `integration.outbox.dead_lettered`

Events are public. Other services subscribe based on need. They have schemas in
the emitting service's `events.rs`. They go through the bus.

**Non-events** are in-coroutine coordination signals that have one waiter and
no fanout:
- "Wait for this child task to complete" → `tokio::sync::oneshot`
- "Notify many waiters when a value is available" → `tokio::sync::broadcast`
- "Producer-consumer queue between two tasks" → `tokio::sync::mpsc`

Non-events stay in the same process. They are not events. They do not use
`event_bus::emit()`. Calling them events conflates two different abstractions
and reintroduces the v1 LOCAL-vs-CLUSTER confusion under a different name.

### Channel naming

`{service}.{aggregate}.{verb_past}` — lowercase snake. Examples:

- `workflow.todo.created`
- `workflow.todo.updated`
- `workflow.todo.phase_advanced`
- `workflow.roadmap.entry_moved`
- `agent_runtime.session.started`
- `agent_runtime.session.ended`
- `identity.principal.created`
- `identity.token.issued`
- `identity.token.revoked`
- `integration.outbox.appended`
- `integration.outbox.delivered`
- `integration.outbox.dead_lettered`

Enforced as a guardrail at the schema-registration site. Reviewers reject any
channel name that doesn't match.

### Event envelope

Every event is an envelope:

```rust
pub struct EventEnvelope {
    pub channel: String,           // workflow.todo.created
    pub idempotency_key: String,   // unique per logical event
    pub emitted_at: DateTime<Utc>,
    pub principal: Option<Principal>,  // who triggered this
    pub payload: serde_json::Value,    // schema-validated against events.rs
}
```

The bus serializes/deserializes envelopes. Services pattern-match on
`channel` and deserialize `payload` to the expected type.

### Emitting

```rust
event_bus.emit(EventEnvelope {
    channel: "workflow.todo.created".into(),
    idempotency_key: format!("todo-{}-created", todo.id),
    emitted_at: Utc::now(),
    principal: Some(ctx.principal.clone()),
    payload: serde_json::to_value(TodoCreatedPayload { /* ... */ })?,
}).await?;
```

The bus crate writes to the configured Redis surface (Streams or Pub/Sub) for
that channel.

### Subscribing

```rust
let mut sub = event_bus.subscribe("workflow.todo.*").await?;
while let Some(envelope) = sub.next().await {
    if event_bus.already_handled(&envelope.idempotency_key) {
        continue;
    }
    handle_event(envelope).await?;
    event_bus.mark_handled(&envelope.idempotency_key).await?;
}
```

The bus tracks handler successes by idempotency key to prevent redelivery
from causing duplicate handler firing.

### Idempotency

Every envelope carries `idempotency_key`. The bus records handler successes
keyed by it. If Redis Streams redelivers (consumer group retry, restart-
recovery, etc.), the bus suppresses re-firing for any handler that already
succeeded.

This is the dedup primitive that makes "at-least-once delivery" (Streams'
contract) safe for handlers that want "at-most-once execution."

### Redis as failure mode

If Redis is down, events can't emit. Services that need to emit will fail
their operation. That is the correct behavior — the failure is the signal.

There is no in-memory fallback queue. There is no local-file outbox for
events. (The legitimate outbox pattern for *external delivery* lives in the
integration service's `outbox` schema — that's about reliable delivery to
external systems like Telegram, not about internal event bus durability.)

Services that need to be resilient to brief Redis outages can retry; the bus
crate provides retry helpers. Long Redis outages are operational incidents,
not application-handled failures.

### Connection pooling

Tokio + `redis-rs` (or `fred`) handles thousands of concurrent connections
without breaking a sweat. Pool sized at startup; tuned via config. There is
no architectural reason to avoid Redis for events.

If a hot path's Redis cost is too high, the answer is one of:

1. **Tune the pool / pipelining.** Usually solves it.
2. **Batch emits.** Multiple related events in one round-trip.
3. **Re-examine whether the emit is needed at all.** If a thousand events
   per second are being emitted for something only one local subscriber
   cares about, that's a domain modeling problem, not a transport problem.

The answer is never "add an in-process fast-path." That's the v1 mistake.

### Subscription topology

For TUI/browser live updates:

- TUI subscribes to Redis pub/sub channels for live events relevant to its
  views (workflow.*, agent_runtime.session.*, etc.).
- Browser cannot subscribe to Redis directly. The frontend custom server in
  `frontend/server.ts` subscribes to Redis on the browser's behalf and pushes
  via WebSocket. Same event source, different delivery mechanism for clients
  that aren't local Rust binaries.

For background workers:

- Workers (integration outbox drainer, etc.) subscribe to Streams via
  consumer groups. Consumer groups handle parallelism and retry.

For services consuming other services' events:

- Service A subscribes to service B's relevant channels at startup. Receives
  events as they emit. Reacts according to its domain logic.

## Failure modes

- **Reintroducing dual-transport "for performance."** Tempting when one
  channel feels expensive. The performance cost of going through Redis is
  almost always negligible compared to the operations the event represents.
  Tune Redis, not the architecture.
- **Naming Tokio channels as events.** `let (tx, rx) = oneshot::channel::<AgentReady>()` is a non-event. Don't call it `agent_ready_event`. Don't put it in `events.rs`. Don't tempt anyone to extract it to the bus later.
- **Misusing pub/sub for durable events.** Pub/sub drops messages if no
  subscriber is alive. Domain events that must be processed reliably go on
  Streams, not pub/sub.
- **Misusing Streams for live UI notifications.** Streams persist
  indefinitely (until pruned), build up consumer-group state, are heavier
  than pub/sub. UI freshness notifications use pub/sub.
- **Cross-service request/response via the bus.** "Service A emits a
  request event, service B emits a response event." The bus is for facts,
  not queries. Cross-service queries go through the service crate's public
  function. Events are for after-the-fact notification, not synchronous
  coordination.
- **Skipping idempotency keys.** "This emit is one-time, doesn't need a
  key." Consumer-group redelivery is real; idempotency keys are how
  handlers stay at-most-once.
- **Adding a fallback queue for Redis downtime.** Same anti-pattern as the
  hook outbox DB. Redis being down is an operational incident; the bus
  doesn't paper over it.

## See Also

- @docs/project/design/architecture-v2/overview.md
- @docs/project/design/architecture-v2/transport-rules.md
- @docs/project/design/architecture-v2/services.md
- @docs/project/design/architecture-v2/redesign-list.md — dual-transport bus
  is on the anti-pattern list.
- @docs/project/design/architecture-v2/file-layout.md — `crates/event_bus/` is
  the infrastructure crate.
