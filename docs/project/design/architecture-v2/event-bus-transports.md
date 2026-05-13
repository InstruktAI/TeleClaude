---
description: 'Three-scope event bus contract for the v2 platform — LOCAL, STREAM, CLUSTER — and the transitional design that lands in the v1 monolith.'
id: 'project/design/architecture-v2/event-bus-transports'
scope: 'project'
type: 'design'
---

# Event Bus Transports — Design

## Required reads

- @docs/project/design/architecture-v2/overview.md
- @docs/project/design/architecture-v2/bounded-contexts.md
- @docs/project/design/architecture/layer-ownership.md

## Purpose

Define the event bus contract for the v2 platform: how events are scoped, which
transport carries them, and how same-process and cross-process subscribers are
served by one uniform API.

The contract is introduced now, while the platform is still a monolith, so that
the v1 daemon's broken Redis-pool-exhausted state can be repaired without a hack
and the eventual extraction of services into their own processes becomes a
deployment change rather than a code rewrite.

This snippet specifies the vocabulary and the rules. It commits to a three-scope
model. It fully designs the transitional implementation that lands in v1
(LOCAL + CLUSTER). It sketches but does not yet design the STREAM transport,
which carries high-volume in-process fanout and the co-located WebSocket
endpoint pattern; STREAM is a follow-up increment with its own design pass.

## Inputs/Outputs

**Inputs:**

- the v2 bounded-context decomposition (Identity, Session Runtime, Workflow,
  Session Ledger, Context & Knowledge, Integration & Events, Presentation,
  Configuration, Agent Artifacts).
- the v1 outage that surfaced the contract gap: every internal event currently
  goes through Redis Streams XADD regardless of scope, the daemon's Redis
  connection pool exhausts under sustained load, and same-process listeners pay
  full network cost.
- the existing `EventVisibility` enum (`LOCAL`, `CLUSTER`, `PUBLIC`) in
  `teleclaude/events/envelope.py`, already partially honored by event schemas
  but ignored by the internal `EventBus`.

**Outputs:**

- the three-scope vocabulary and what each scope means semantically.
- the transport-selection rules driven by visibility.
- the tagging rules a developer applies when emitting a new event.
- the increment plan that distinguishes what lands now (LOCAL + CLUSTER) from
  what is deferred (STREAM).
- the discipline that prevents in-process convenience from rebuilding the
  monolith inside the contract.

## Invariants

- **Visibility is logical scope, not deployment topology.** A `session_updated`
  event carries the same visibility regardless of whether Presentation is
  co-located with Session Runtime today or a separate process tomorrow.
- **Direct cross-context calls are forbidden, even within one process.** If
  emitter and subscriber belong to different bounded contexts, communication
  goes through the event bus. Same-process speed is a property of the transport,
  never of an out-of-band shortcut.
- **LOCAL never touches Redis.** A LOCAL event is dispatched in-process,
  synchronously, to the registered handler set. There is no cross-host visibility
  by design.
- **CLUSTER reaches every subscriber.** Same-process subscribers receive a
  CLUSTER event through the local dispatch path; off-process subscribers receive
  it through Redis Streams. Same envelope, single emit, two delivery legs. No
  self-redelivery loop: handlers that already fired locally are not re-fired
  when Redis redelivers the envelope to the originating process.
- **Idempotency is the dedup primitive.** Every envelope carries an
  `idempotency_key`. The bus records successful handler executions against this
  key so that local-then-Redis redelivery and consumer-group retries converge to
  at-most-once handler firing.
- **Cross-host failure does not break in-process delivery.** When Redis is
  unavailable, LOCAL events continue to dispatch and CLUSTER events still reach
  same-process subscribers. Off-process CLUSTER delivery degrades but does not
  poison the daemon's liveness.
- **The bus surface is stable across transports.** `event_bus.emit`,
  `event_bus.subscribe`, and `event_bus.unsubscribe` have the same shape and the
  same semantics regardless of the scope of the event. Callers do not branch on
  transport.

## Primary flows

### The three scopes

| Scope     | Transport(s)                                     | Durability | Cross-process? | Cross-host? | Example events                                                                                |
| --------- | ------------------------------------------------ | ---------- | -------------- | ----------- | --------------------------------------------------------------------------------------------- |
| `LOCAL`   | InProcess dispatch only                          | none       | no             | no          | `AGENT_READY`, internal readiness gates, same-coroutine completion signals                    |
| `STREAM`  | InProcess dispatch + co-located WebSocket bridge | none       | no\*           | no\*        | `agent_activity`, `tool_use`, `user_prompt_submit`, session lifecycle live-streaming (future) |
| `CLUSTER` | InProcess dispatch + Redis Streams               | durable    | yes            | yes         | `operation.todo_*.completed`, workflow handoff, integrator coordination, system events        |

\* STREAM is in-process for the data plane. Remote clients reach a STREAM event
by connecting via WebSocket to the process that owns the entity (e.g., the
Session Runtime hosting a given session). The control plane that tells the
client *which* process to connect to is a Presentation-context concern and uses
the API, not the event bus.

### Transport selection rule

```mermaid
flowchart TD
    E[event_bus.emit event, ctx] --> R{visibility on envelope}
    R -->|LOCAL| L[InProcess dispatch only]
    R -->|STREAM| S[InProcess dispatch + WS bridge handler]
    R -->|CLUSTER| C1[InProcess dispatch for local subscribers]
    C1 --> C2[Redis Streams XADD for off-process subscribers]
    L --> D[handlers run in this process]
    S --> D
    C2 --> P[other processes consumer-group XREADGROUP]
    P --> D2[handlers run in those processes]
```

### Tagging rule — how to decide a new event's scope

Apply the questions in order. The first one that fits decides the scope.

1. **Is the emitter waiting for a same-coroutine completion signal, with a
   single waiter and no fanout?** → `LOCAL`. Examples: readiness gates,
   in-process completion futures.
2. **Does the event cross a v2 bounded-context boundary?** That is: at least one
   subscriber lives in a different bounded context from the emitter, *in the v2
   target topology*. Today's process layout is irrelevant. → `CLUSTER`. Examples:
   `operation.*.completed` (Workflow → Integration & Events), integrator handoff
   (Workflow → Workflow on another host).
3. **Is the event a high-volume in-context broadcast whose subscribers include
   live-streaming endpoints?** → `STREAM`. Examples: agent activity feeds,
   session lifecycle live-streaming. STREAM is in-process; remote consumers
   reach it through a WebSocket bridge co-located with the emitter.

The default when uncertain is **not** LOCAL. Defaulting to LOCAL for convenience
is the failure mode that quietly rebuilds the monolith. Defaulting to CLUSTER
preserves correctness — a CLUSTER event still dispatches locally for
same-process subscribers, so the only cost of a false CLUSTER is a Redis XADD
that nobody consumes off-process. A false LOCAL silently drops cross-context
delivery and that lie is invisible until production breaks.

### Where per-event scope is declared

The doc never enumerates events. The visibility of any given event is declared
in exactly one place — the code — and that declaration is the single source of
truth. A prose registry duplicated here would go stale the moment a new event
is added, and an out-of-date doc on a load-bearing contract is worse than no
doc.

Two declaration sites are valid:

- **`EventCatalog.default_visibility`** for events with a registered schema in
  `teleclaude/events/schemas/`. The schema declares the event's correct scope
  once; producers and the bus honor it.
- **Explicit `event_bus.emit(event, ctx, visibility=…)`** at the call site for
  internal events that do not have a schema entry. This is the path most
  current daemon-internal events take.

No event remains at the bus's hardcoded default after Increment 1. Reviewers
reject PRs that add or modify an `event_bus.emit` call without an explicit
visibility, and PRs that register a new schema without a `default_visibility`.

### Worked examples — the rule in action

**Example 1: `AGENT_READY`** — emitted by Session Runtime's coordinator when
an agent's `session_start` hook fires; awaited by the launcher coroutine in
the same process. Apply the rule:

- Question 1: same-coroutine completion signal with a single waiter? **Yes.**
  → `LOCAL`.

The launcher's `event_bus.subscribe(AGENT_READY, …)` and the coordinator's
`event_bus.emit(AGENT_READY, ctx, visibility=EventVisibility.LOCAL)` traverse
the InProcess transport only. No Redis hop.

**Example 2: `operation.todo_integrate.completed`** — emitted by a Workflow
worker when an integration operation succeeds; consumed by the orchestrator
session (also Workflow) and by Integration & Events bookkeeping. Apply the
rule:

- Question 1: same-coroutine completion signal with a single waiter? No (the
  orchestrator and the worker live in different sessions, possibly on
  different computers).
- Question 2: crosses a v2 bounded-context boundary? **Yes** — Workflow worker
  → Workflow orchestrator (which may run on another host) and → Integration &
  Events.
  → `CLUSTER`.

`event_bus.emit(operation.todo_integrate.completed, ctx,
visibility=EventVisibility.CLUSTER)` dispatches locally to any same-process
subscriber and additionally publishes via Redis Streams for cross-host
consumers.

### Increment plan

**Increment 1 — visibility-aware dispatch over two transports.**

Lands the LOCAL and CLUSTER transports plus the contract above.

- `EventBus._publish` stops hardcoding `visibility=CLUSTER`. The visibility
  comes from an explicit `emit(event, ctx, visibility=…)` parameter; the
  envelope carries it.
- `EventBus.emit` performs synchronous in-process dispatch first by iterating
  `self._handlers[event]` and scheduling each handler in the current loop. The
  existing `_successful_handlers` cache records handler success keyed by
  `idempotency_key`.
- For `CLUSTER` envelopes, `emit` additionally schedules a background `xadd`
  publish task — current behavior, but now opt-in by visibility rather than
  default.
- For `LOCAL` envelopes, the `xadd` step is skipped entirely.
- The consumer-group side (`deliver` in `EventBus`) keeps its current dedup
  check; same-process redelivery of a locally-already-fired envelope is a
  no-op per handler.
- Every existing `event_bus.emit` call site is visited and given an explicit
  `visibility` via the tagging rule. Every schema in
  `teleclaude/events/schemas/` is verified to carry a correct
  `default_visibility`. No event remains at the bus's hardcoded default. The
  implementation PR's review checklist enumerates the emit sites touched, and
  the reviewer rejects on any missing site.
- `config.yml:redis.max_connections` is raised from 30 to 100 as transitional
  monolith-era sizing. The change is documented as transitional and is
  expected to shrink once services split.

Result: daemon restart loads the fix, AGENT_READY (and any other LOCAL events)
stop touching Redis, the pool no longer exhausts under sustained operation,
and the v2 contract is in place for every emit site.

**Increment 2 — STREAM transport and co-located WebSocket bridge.**

Requires a separate design pass. The decisions to settle:

- Does the daemon's current WebSocket endpoint move into Session Runtime's
  process explicitly, or does it stay where it is and subscribe via the
  STREAM bus?
- How does a remote TUI / web client discover which process hosts a given
  session? (Presentation API; the existing computers/sessions catalog likely
  suffices.)
- What is the back-pressure contract for the WS bridge when a subscriber is
  slow?
- Does STREAM carry an `idempotency_key` and per-handler dedup, given there
  is no durability guarantee?

Once that design lands, events identified as STREAM-eligible during the
Increment 2 audit move from CLUSTER to STREAM at their declaration site
(schema or emit kwarg), and Redis traffic drops to the CLUSTER-only steady
state.

**Increment 3+ — service extraction per the v2 reconstruction order.**

By this point the event bus contract is correct. Extracting a bounded context
(for example, moving the API server out of the daemon) is a deployment
change: same emit, same subscribe, the CLUSTER leg of every cross-context
event now carries traffic that previously delivered in-process. No code in
the bus needs to change for an extraction.

### Operational properties

- **Pool sizing.** The monolith-era `max_connections: 100` covers the
  transitional window where CLUSTER plus to-be-STREAM events all run through
  Redis. Once Increment 2 lands and STREAM events bypass Redis, the steady-state
  pool requirement drops back toward the original 30. Services that emerge
  through extraction each carry their own pool budget.
- **Redis outage behavior.** LOCAL traffic is unaffected. CLUSTER traffic
  continues to dispatch to same-process subscribers. Off-process CLUSTER
  delivery fails fast at XADD time; per the contract documented on
  `EventBus`'s module docstring, workflow truth lives in SQLite-owned stores
  and clients fall back to polling canonical state. The bus does not buffer
  beyond Redis's own retry semantics in Increment 1; bounded local buffering on
  outage is a deferred enhancement and is not blocking for the v1 recovery.
- **Observability.** Increment 1 adds two counters: `event_bus.local_dispatch`
  and `event_bus.cluster_publish`. Their ratio is the operational read on how
  much steady-state Redis traffic remains attributable to in-context fanout —
  the signal that STREAM is needed and that the Increment 2 audit is paying
  off.

## Failure modes

**Tagging by deployment, not scope.** A developer sees that two services live
in the same daemon today and tags an event LOCAL "because it's faster." The
extraction breaks because LOCAL events do not cross processes. The discipline:
tag for v2 topology, not v1 topology.

**Defaulting to LOCAL for convenience.** LOCAL is fast; CLUSTER costs a Redis
hop. Under pressure to make something "lightweight," a developer reaches for
LOCAL when the event genuinely crosses contexts. The lie is invisible until a
remote subscriber goes silent. The discipline: when uncertain, choose CLUSTER.
A spurious XADD is recoverable; a missing one isn't.

**Direct cross-context calls within one process.** "We're both in the daemon
anyway; just `await presentation.notify_session_updated(...)`." This rebuilds
the monolith inside the bus contract. The next extraction discovers the call
the hard way. The discipline: cross-context coordination always goes through
the bus, even when both contexts are co-located.

**Treating the WS bridge as an exception.** The Presentation context owns the
WebSocket *API surface* (auth, framing, discovery), but the *data plane* of a
STREAM event flows from the entity-owning process via a co-located bridge.
Trying to route STREAM events through Redis to satisfy a notion of "all events
must be cluster-visible" reintroduces the pool pressure the contract is
designed to eliminate. The discipline: STREAM is in-process by design and
remote visibility is provided by where the WebSocket terminates, not by the
broker.

**Re-firing locally-delivered handlers when Redis redelivers.** The
`_successful_handlers` cache exists to prevent this. Removing or bypassing it
under the assumption "it's a fresh consumer-group read so it must be new"
silently double-fires handlers for CLUSTER events emitted in the same process
as a same-process subscriber. The discipline: the idempotency key is the
identity of an envelope across delivery legs; trust it.

## See Also

- docs/project/design/architecture-v2/bounded-contexts.md — the contexts that define what counts as crossing a boundary.
- docs/project/design/architecture-v2/reconstruction-order.md — the order in which contexts move from monolith to standalone services.
- docs/project/design/architecture/layer-ownership.md — why downstream layers receive fully resolved inputs and never reach sideways.
- docs/project/spec/event-vocabulary.md — the authoritative list of event types.
