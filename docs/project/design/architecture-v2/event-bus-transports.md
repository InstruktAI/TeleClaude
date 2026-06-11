---
description: 'Three-scope Redis event bus for v2 (Local mandatory + Cluster/Public optional). Explicit per-emit scoping, subscriber-side merge across configured scopes. In-coroutine sync uses Tokio channels — not events.'
visibility: 'public'
---

# Event Bus Transports — Design

## Required reads

- docs/project/design/architecture-v2/overview.md
- docs/project/design/architecture-v2/transport-rules.md
- docs/project/design/architecture-v2/services.md

## Purpose

Define the event bus contract for v2: one transport TYPE (Redis), three
SCOPES (Local, Cluster, Public) each served by a separate Redis client
instance. The bus routes events by the explicit scope on the envelope.
Single-computer installs run with Local only — Cluster and Public are
opt-in infrastructure for multi-host meshes and cross-mesh federation
respectively.

Replaces v1's dual-transport (LOCAL in-process + CLUSTER Redis) model.
v1's "LOCAL" meant in-process direct dispatch — that's the bug-factory on
the redesign list. v2's "LOCAL" means a local-host Redis instance: still
real Redis with real pub/sub semantics, still durable behavior, just an
instance the daemon talks to locally (not the cluster mesh). The in-process
fast-path stays gone.

## Inputs/Outputs

**Inputs:**

- the v2 architectural rule that services are crates consumed as SDK
- the v1 dual-transport bus and its failure modes (visibility
  misclassification, silent cross-process delivery loss, in-process
  fast-path conflated with scope)
- the actual concurrency story: Tokio + Postgres MVCC handles the writer
  load Python could not, removing the original reason for any in-process
  fast-path
- the three deployment shapes the platform supports: single-computer
  install (Local only), personal mesh (Local + Cluster), federated mesh
  (Local + Cluster + Public)

**Outputs:**

- the three-scope transport model (three Redis clients, one bus)
- the explicit scope on every event envelope
- the routing rules (emit → one scope; subscribe → scope-set)
- the graceful-degradation semantics (silent drop on absent optional scope)
- the local-coroutine sync primitive that is explicitly not an event
- the event naming convention

## Invariants

- **One transport TYPE: Redis. Three SCOPES via separate Redis client
  instances.** Local is a local-host Redis. Cluster is the personal mesh's
  Redis. Public is a cloud-hosted hub Redis. All three are real Redis with
  Streams + Pub/Sub semantics. There is no in-process fast-path under any
  scope.
- **Local is mandatory. Cluster and Public are optional.** Single-computer
  installs configure only Local. Adding a mesh adds Cluster. Joining
  federation adds Public. Operators opt in per scope.
- **Explicit scoping on emit.** Every event carries `envelope.scope: Local
| Cluster | Public`. The bus routes that emit to the matching client
  only. Emitting at scope=Cluster does NOT also fire on Local. The
  application chooses scope at emit time and the bus respects it
  literally.
- **Subscriber-side merge across configured scopes.** A subscription is
  `{channel pattern, scope-set}`. The bus reads from each configured
  client in the set and merges the streams under one subscription handle.
  A subscriber that wants everything declares `{Local, Cluster, Public}`;
  on a Local-only deployment it just receives Local events. The bus
  never errors on a subscription declaring scopes not configured —
  absent clients are silently skipped in the merge.
- **Emit-side rules per scope:**
  - `emit(scope=Local)` with Local client missing → **raise.** Local is
    mandatory; missing it is a misconfiguration that must fail loudly.
  - `emit(scope=Cluster)` with Cluster client missing → **silent drop**
    with a debug/trace log. The operator's choice to not configure
    Cluster IS the signal of disinterest.
  - `emit(scope=Public)` with Public client missing → same as Cluster:
    silent drop, debug/trace log.
  - This is NOT v1's broken silent-no-op pattern. v1 claimed CLUSTER was
    required and then silently dropped when Redis was absent. v2
    explicitly types Cluster and Public as optional, making silent drop
    on absent client the contract — not a contract violation.
- **One cluster bus Redis serves the `Local` and `Cluster` scopes.** Its endpoint
  is configured by `CLUSTER_REDIS_URL`, or by `REDIS_URL`. The `Public` scope has
  its own endpoint, configured by `PUBLIC_REDIS_URL`. An emit at `Local` or
  `Cluster` scope routes to the cluster bus; an emit at `Public` scope routes to
  the Public endpoint when `PUBLIC_REDIS_URL` is configured, and is dropped with a
  debug log otherwise.
- **A subscription delivers only the scopes it requests.** The bus decodes each
  envelope and delivers it when `envelope.scope` is in the subscription's scope
  set: `SubscriptionScopes::local()` delivers only `Local` envelopes, `cluster()`
  only `Cluster` envelopes, and `all()` delivers every scope. When the cluster bus
  and the Public endpoint both carry an envelope with the same `idempotency_key`,
  the subscription delivers it once.
- **In-coroutine completion signals are not events.** They use Tokio
  primitives (`oneshot`, `broadcast`, `mpsc`) and are named accordingly.
  They never use `event_bus.emit()`. This rule predates and is orthogonal
  to the three-scope model: scope is about WHICH Redis instance carries
  the event, not whether to use the bus at all.
- **The bus surface is one shape per scope.** `event_bus::emit(envelope)`
  and `event_bus::subscribe(channel, scopes)` have one contract: same
  envelope, same durability semantics per channel, same idempotency rules.
  The bus internally fans the work to the right client(s).
- **Idempotency by envelope key spans scopes.** Every event carries an
  `idempotency_key`. The bus records handler successes keyed by it. A
  multi-scope subscriber reading the same logical event from two or
  three clients (e.g., a Cluster event that's federated to Public) does
  not double-fire its handler.
- **Schema-versioned, tolerant readers as law.** Every cross-node
  envelope carries `schema_version`: the v2 `EventEnvelope` and the v1
  `cluster.*` `ClusterEnvelope`. Consumers ignore unknown fields and
  tolerate absent optionals; a consumer that rejects an envelope because
  of an unknown field is a defect. This implements
  `project/adr/0030-cross-node-envelope-schema-versioning`, the
  envelope-level realization of the fleet compatibility contract
  (`project/adr/0026-cross-version-fleet-compatibility`).
- **Cross-process delivery is the default within a scope.** Any event
  emitted at a given scope is visible to any process subscribed to that
  scope's channel via that scope's Redis. There is no per-process
  opt-out within a scope.
- **Redis pool sizing is operational, not architectural.** If any scope's
  Redis pool exhausts under load, tune the pool — don't invent a fourth
  transport or in-process fast-path to avoid it.

## Primary flows

### The three scopes (each its own Redis client)

| Scope       | Reach                                  | Required? | Typical deployment                                                                                                      |
| ----------- | -------------------------------------- | --------- | ----------------------------------------------------------------------------------------------------------------------- |
| **Local**   | Single host (this computer)            | YES       | Always present. Single-computer install runs Local-only.                                                                |
| **Cluster** | Single owner's mesh (multi-host fleet) | NO        | A user with multiple machines configures Cluster to coordinate across them.                                             |
| **Public**  | Cross-mesh federation hub              | NO        | Multiple owners' clusters meet via a cloud-hosted hub. Spoke (cluster) → hub (public) → spoke (other cluster) topology. |

Each scope is a separate Redis client instance. The bus is constructed
with all three:

```rust
let bus = EventBus::new(EventBusConfig {
    local:   RedisConfig { url: "redis://127.0.0.1:6379", .. },  // required
    cluster: Some(RedisConfig { url: "redis://mesh.example:6379", .. }),  // opt-in
    public:  Some(RedisConfig { url: "rediss://public-hub.example:6379", .. }),  // opt-in
}).await?;
```

Missing Local raises at construction. Missing Cluster or Public leaves
the corresponding internal client `None`; emits to those scopes silently
drop per the invariant above; subscriptions silently skip those scopes
in the merge.

### The two Redis surfaces (per scope)

Each scope's Redis offers two delivery mechanisms; both are part of the
bus and available on every scope:

| Surface                                   | Use                                                      | Durability | Replay |
| ----------------------------------------- | -------------------------------------------------------- | ---------- | ------ |
| **Redis Streams** (`XADD`/`XREADGROUP`)   | Domain events with consumer groups, retry, DLQ           | Durable    | Yes    |
| **Redis Pub/Sub** (`PUBLISH`/`SUBSCRIBE`) | Live notifications, cache invalidation, ephemeral fanout | Ephemeral  | No     |

A channel's contract picks the surface:

- `workflow.todo.*` — Streams. Domain events that must be processed
  reliably; consumer groups handle scale; retries on handler failure.
- `tui.snapshot.refresh` — Pub/Sub. Live notifications to subscribed TUIs;
  fine to drop if no subscriber is alive.

The bus crate exposes both via one consistent API across all three scopes.
Service authors specify the surface at channel definition time (or per-emit
if needed). The bus is one transport TYPE with two delivery modes and
three scope instances, all Redis-backed.

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

Every event is an envelope. `scope` is required:

```rust
pub enum EventScope { Local, Cluster, Public }

pub struct EventEnvelope {
    pub schema_version: u32,       // current envelope shape version
    pub channel: String,           // workflow.todo.created
    pub scope: EventScope,         // routing directive — required
    pub idempotency_key: String,   // unique per logical event
    pub emitted_at: DateTime<Utc>,
    pub principal: Option<Principal>,  // who triggered this
    pub payload: serde_json::Value,    // schema-validated against events.rs
}
```

The bus serializes/deserializes envelopes. Services pattern-match on
`channel` and deserialize `payload` to the expected type. The bus uses
`scope` to choose the Redis client for emit and to filter on subscribe.

The event catalog (`project/spec/domain/event-catalog`) defines the
**default scope** per channel via its `visibility` column. Emitters
typically inherit this default; they may override per-emit only when the
domain genuinely requires it.

### Emitting

```rust
event_bus.emit(EventEnvelope {
    channel: "workflow.todo.created".into(),
    scope: EventScope::Cluster,    // explicit; routes via Cluster Redis only
    idempotency_key: format!("todo-{}-created", todo.id),
    emitted_at: Utc::now(),
    principal: Some(ctx.principal.clone()),
    payload: serde_json::to_value(TodoCreatedPayload { /* ... */ })?,
}).await?;
```

The bus routes to the Redis client matching `scope`. If that scope's
client is configured, the event is written to the configured surface
(Streams or Pub/Sub). If the scope is optional (Cluster or Public) and
not configured, the bus drops silently with a debug/trace log. If the
scope is Local and Local is not configured (misconfiguration), the bus
raises.

Emitting at scope=Cluster does NOT also fire on Local. If an event has
relevance at multiple scopes, the emitter calls `emit` once per scope.
This is rare and intentional — most events have one true scope.

### Subscribing

```rust
let mut sub = event_bus.subscribe(
    "workflow.todo.*",
    SubscriptionScopes::all(),   // Local + Cluster + Public; bus skips unconfigured
).await?;
while let Some(envelope) = sub.next().await {
    if event_bus.already_handled(&envelope.idempotency_key) {
        continue;
    }
    handle_event(envelope).await?;
    event_bus.mark_handled(&envelope.idempotency_key).await?;
}
```

The bus merges streams from each configured scope in the requested set
under one subscription handle. The subscriber sees one logical stream
regardless of how many scopes contributed events. The bus tracks handler
successes by idempotency key to prevent redelivery — and to prevent
double-firing when the same logical event arrives via two scopes (e.g.,
a Cluster event federated to Public and consumed by a subscriber on
both scopes).

A subscriber that genuinely wants only local events declares
`SubscriptionScopes::local()`; one wanting cluster-only declares
`SubscriptionScopes::cluster()`; etc. `SubscriptionScopes::all()` is
the default and works on any deployment shape — the bus reads from
whatever clients are configured.

### Idempotency

Every envelope carries `idempotency_key`. The bus records handler successes
keyed by it. If Redis Streams redelivers (consumer group retry, restart-
recovery, etc.), the bus suppresses re-firing for any handler that already
succeeded.

This is the dedup primitive that makes "at-least-once delivery" (Streams'
contract) safe for handlers that want "at-most-once execution."

### Redis as failure mode (per scope)

The "Redis down = fail hard" rule applies **per scope, on emit**:

- **Local Redis down** → `emit(scope=Local)` raises. Local is mandatory;
  this is a real outage that must surface. Services emitting at Local
  scope fail their operation. The failure is the signal.
- **Cluster Redis down** with Cluster client configured → `emit(scope=Cluster)`
  raises. Same rationale: the operator opted in to Cluster, so an outage
  of configured infrastructure is a real failure.
- **Cluster client not configured at all** → `emit(scope=Cluster)` silent
  drops with debug/trace log. This is the opt-out path — not a failure.
- **Public Redis** — same shape as Cluster: configured-but-down raises;
  unconfigured drops.

There is no in-memory fallback queue. There is no local-file outbox for
events. There is no cross-scope fallback (no "if Cluster is down, fall
back to Local" — that would violate explicit scoping). The legitimate
outbox pattern for _external delivery_ lives in the integration service's
`outbox` schema — that's about reliable delivery to external systems
like Telegram, not about internal event bus durability.

Services that need to be resilient to brief Redis outages can retry; the bus
crate provides retry helpers per scope. Long Redis outages are operational
incidents, not application-handled failures.

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
  views (workflow._, agent_runtime.session._, etc.).
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

- **Reintroducing in-process fast-path "for performance."** Tempting when
  one channel feels expensive. The performance cost of going through
  Local-scope Redis (a local-host instance) is almost always negligible
  compared to the operations the event represents. Tune the Local pool,
  not the architecture. v1's in-process LOCAL was the bug-factory; do not
  bring it back under any name.
- **Cumulative scope emit.** "If I emit at Cluster, Local should also see
  it." No. Explicit scoping means one emit → one scope. If an event has
  multi-scope relevance, the emitter calls `emit` once per scope. This is
  rare in practice; most events belong to one scope.
- **Cross-scope fallback on outage.** "Cluster is down, fall back to Local
  so the event at least lands somewhere." No. Cluster down = the operator-
  configured infrastructure is failing; raise. Falling back silently
  hides the outage and breaks subscriber expectations.
- **Treating Cluster/Public as required.** Single-computer installs run
  Local-only. Code that assumes Cluster is always present is wrong. Use
  capability checks (`bus.has_scope(Public)`) when gating optional
  behavior, not assumptions.
- **Treating Cluster/Public's silent drop as v1's broken silent-no-op.**
  v1's silent drop hid a contract violation (CLUSTER was claimed required).
  v2's silent drop on unconfigured optional scopes IS the contract. The
  rule maps to operator intent: configure it = you care; don't configure
  it = you don't.
- **Naming Tokio channels as events.** `let (tx, rx) = oneshot::channel::<AgentReady>()`
  is a non-event. Don't call it `agent_ready_event`. Don't put it in
  `events.rs`. Don't tempt anyone to extract it to the bus later.
- **Misusing pub/sub for durable events.** Pub/sub drops messages if no
  subscriber is alive. Domain events that must be processed reliably go on
  Streams, not pub/sub. This applies per scope.
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
  handlers stay at-most-once. With multi-scope subscriptions, the same
  logical event arriving via two scopes is also deduped by the key.
- **Adding a fallback queue for Redis downtime.** Same anti-pattern as the
  hook outbox DB. Redis being down is an operational incident; the bus
  doesn't paper over it.

## See Also

- docs/project/design/architecture-v2/overview.md
- docs/project/design/architecture-v2/transport-rules.md
- docs/project/design/architecture-v2/services.md
- docs/project/design/architecture-v2/redesign-list.md
  is on the anti-pattern list.
- docs/project/design/architecture-v2/file-layout.md
  the infrastructure crate.
- docs/project/adr/0032-cluster-bus-redis-serves-local-and-cluster.md
- docs/project/adr/0026-cross-version-fleet-compatibility.md
- docs/project/adr/0013-unified-cluster-events.md
