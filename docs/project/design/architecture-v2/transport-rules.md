---
description: 'Load-bearing rule for v2: services are crates consumed as SDK. Transports exist only at well-defined boundaries.'
id: 'project/design/architecture-v2/transport-rules'
scope: 'project'
type: 'design'
visibility: 'public'
---

# Transport Rules — Design

## Required reads

- docs/project/design/architecture-v2/overview.md

## Purpose

Fix the single rule that determines how any two pieces of v2 code talk to each
other. Without this rule, every cross-call decision becomes an architectural
re-derivation and the platform drifts back into the multi-transport sprawl that
v1 accumulated.

## Inputs/Outputs

**Inputs:**

- the v2 target shape and bounded contexts
- the operational reality that all services run on the same machine, in the
  same language (Rust), in the same workspace
- the v1 failure mode of inventing transports (HTTP, daemon-relay, in-process
  event emitter) for what should have been direct calls

**Outputs:**

- the default mechanism for one piece of v2 code to call another
- the closed list of transports that legitimately exist in v2
- the architectural rule reviewers apply to any "X needs to call Y" proposal

## Invariants

- **Services are crates, not endpoints.** Every v2 service is a Rust library
  crate. Any binary that needs the service depends on the crate and calls its
  public API directly.
- **No transport between local same-language processes for what is fundamentally
  a function call.** If both ends are Rust binaries on the same machine, the
  call goes through a crate dependency, not HTTP, gRPC, Unix socket, or
  daemon-relay.
- **Transports exist only at well-defined boundaries.** Events, persistent
  state, external consumers, browser delivery — and nothing else.
- **The smell test.** If a proposal introduces a transport between local
  same-language code, the proposal is wrong. The transport is the smell.

## Primary flows

### Placement heuristic — library vs binary ownership

Two ownership questions, often conflated. They resolve differently and
must not be merged.

#### Library crate ownership = change-axis

**Question:** When does this code change? What triggers the change?

The owner is the service whose domain drives those changes.

- Code that parses Claude Code's hook payload changes when Claude Code
  changes its hook schema. Trigger: external system protocol change.
  Owner: **`integration`** (external-system protocols are its domain).
- Code that tracks session state and lifecycle phases changes when our
  session model changes. Trigger: domain decision. Owner:
  **`agent_runtime`** (session semantics are its domain).
- Code that writes a workflow event to Redis changes when the event bus
  contract changes. Trigger: infrastructure contract change. Owner:
  **`event_bus`** (bus contract is its domain) — though the EMIT call
  site lives in whatever service is emitting.

The library crate owns the logic by domain. "Same change axis" → same
crate. "Different change axes" → different crates, even if the code
superficially looks similar.

#### Binary crate ownership = deployment shape

**Question:** What kind of entry point is this? Which library crates does
it embed?

A binary is a packaging unit, not a domain. Binaries can:

- **Embed multiple library crates** when the entry point dispatches to
  several services (`telec-cli` embeds workflow + identity + knowledge +
  config because the CLI has commands for all of them).
- **Exist solely as one library crate's entry point** when the deployment
  shape is specific (`telec-hook` exists solely as integration's
  subprocess entry point — Claude Code's config references it directly).
- **Embed and supervise multiple library crates plus their own logic**
  (`telec-daemon` embeds agent_runtime + integration + spawns workers).

The binary's identity is "what's the entry point shape" — subprocess,
long-running daemon, HTTP server, CLI dispatcher. Not "which service does
this belong to."

#### The split applied to hooks

- **Hook payload parsing/normalization/emission** → library crate
  `integration` (change-axis: external CLI protocols change).
- **`telec-hook` binary** → its own binary crate, depends on `integration`,
  exists as a fast subprocess entry point that Claude Code invokes by name.
- **Reaction to hook events** (updating session state, tracking liveness)
  → library crate `agent_runtime` (change-axis: session model changes).
  Subscribes to integration's emitted events.

The binary `telec-hook` is "owned" by integration in the sense that it's
integration's subprocess entry point, but the binary itself is just a
deployment crate. Don't conflate "the binary's logic lives in integration"
with "the binary IS integration."

### Cross-version Redis bridge (v1 ↔ v2 during migration)

During the migration window, v1 (Python) and v2 (Rust) coexist. They
communicate through one mechanism: **Redis events**. Never through
storage, never through cross-language function calls, never through
HTTP between local processes.

The pattern per service:

1. **Pre-cutover phase.** v1 owns the service's data (SQLite). v2's
   service crate is built and tested but operates against an empty
   Postgres schema. v1 publishes its mutations to Redis using the v2
   event naming convention so v2 subscribers see them. v2 may publish
   too (for any new work performed via v2 surfaces), and v1 subscribes
   to keep its caches/views fresh.
2. **Cutover.** One-shot data migration script reads v1's SQLite for
   that service, writes to Postgres. Same PR: v1 code paths for that
   service are deleted, v2 becomes authoritative.
3. **Post-cutover.** v2 owns the data forever. No v1 paths for that
   service remain. v1 continues to run for services that haven't cut
   over yet.

Invariants during migration:

- **No dual-write.** A service's data has one authoritative writer at
  any moment. Before cutover: v1. After cutover: v2.
- **No shared storage across versions.** v1 reads/writes SQLite; v2
  reads/writes Postgres. Neither reaches into the other's storage.
- **No cross-language function calls.** v1 Python doesn't call v2 Rust
  (no HTTP, no FFI, no IPC). v2 Rust doesn't call v1 Python. They share
  only Redis events.
- **Event names agreed in advance.** Both versions emit and subscribe
  using the canonical `{service}.{aggregate}.{verb_past}` channels. v1
  publishing v1-only event names defeats the bridge.
- **Cutover is atomic per service.** Data migration + code switch + v1
  deletion all in one PR. No "transitional dual-mode" beyond the brief
  PR review window.

This pattern is what makes side-by-side migration possible without
hybrid hell. Each service migrates independently; v1 keeps shipping
features (in still-v1 services) while v2 services build out; the cutover
moments are small and well-defined.

### Anti-pattern: domain ownership by transport similarity

Two pieces of code looking architecturally similar (both ingest inbound
payloads) does not mean they share a domain. Look at the change axis, not
the surface pattern.

- Hooks and webhooks both have inbound-payload mechanics. Same code
  pattern, different domains? No — both are "external inbound to be
  normalized and emitted." Both are `integration`'s domain (per the
  change-axis: both change when external protocols change).
- Authentication and authorization both verify tokens. Same code pattern,
  different domains? Yes — authentication is identity's; authorization is
  the relevant service's (workflow decides who can read workflow data,
  not identity).

Pattern similarity is a hint to look for shared infrastructure, not proof
of shared ownership. Always come back to: "when this code changes, what
triggered the change?"

### The default: services as SDK

Every service in v2 is a library crate under `crates/`. The crate's public
interface (the `pub` items in `src/lib.rs`) is the service's contract. There is
no separate "API server" wrapping the service for local consumers.

```
crates/workflow/                 (library crate)
├── src/lib.rs                   (pub fn list_todos, pub fn create_todo, ...)
├── src/_state.rs                (internal)
└── src/models.rs                (pub Todo, RoadmapEntry, ...)

crates/telec/Cargo.toml          (binary crate — the CLI)
[dependencies]
workflow = { path = "../workflow" }

crates/telec/src/main.rs
use workflow::list_todos;
// ...
let todos = workflow::list_todos(&ctx, project_id).await?;
```

Calling another service is a direct function call across a crate boundary. No
serialization, no socket, no protocol layer. The compiler enforces types across
the boundary.

### The four legitimate transports

| Transport | Purpose | Crossed by |
|---|---|---|
| **Crate dependency (SDK)** | Local service-to-service in-process calls | Default for everything local |
| **Redis** | Events, pub/sub, queues, leases, ephemeral cache | Any code that needs to react to state changes |
| **Postgres** | Service-owned persistent state | Each service via its own crate; never queried by other services |
| **HTTP API** | External cross-process callers in different languages or on different machines | Browser, remote machines, third-party integrations |
| **WebSocket** | Browser real-time push | Browser only; bridges to Redis at the server side |

The first row is the default. The others exist only at the boundaries they
exist for.

### Decision rule for any "X needs to call Y" question

Apply in order. The first one that fits decides.

1. **Same process, same language (Rust)?** → import Y as a crate. SDK call. Done.
2. **Different process, same language (Rust)?** → each process embeds the crate
   independently. They coordinate via Redis events or shared Postgres state.
   Direct request/response between them is rare and almost always indicates one
   of them should embed the other's crate instead.
3. **Different language (Rust ↔ Node.js, e.g. backend ↔ Next.js)?** → HTTP API.
   The HTTP API server is a thin Rust binary that itself embeds the service
   crate and exposes a subset over HTTP.
4. **Different machine (cross-host)?** → HTTP API. Same shape as case 3.

If a proposal involves a transport for a case-1 call, it is wrong. The
transport is the smell.

### What this rules out, explicitly

- **No HTTP between local Rust binaries.** The CLI does not POST to the
  daemon. The TUI does not GET from the daemon. They each embed the service
  crates they need.
- **No "auth service running on port 8080."** Auth is a crate. Every binary
  that needs auth embeds the identity crate.
- **No daemon-as-relay for events.** The daemon is one Redis subscriber among
  many. It is not a fan-out hub for other Rust processes.
- **No "local-only optimization" for the event bus.** The event bus has one
  transport (Redis). In-coroutine completion signals use Tokio channels
  (`oneshot`, `broadcast`) — those are not events and must not be called
  events.
- **No callers reaching past a service into its storage.** The workflow crate
  owns the `workflow` Postgres schema. No other crate queries that schema. If
  another crate needs workflow data, it calls workflow.

### What this enables

- **No mock services, no fake endpoints, no test-only HTTP layers** for local
  tests. Tests construct services directly and pass them where they're needed.
- **Compile-time type safety across service boundaries.** The compiler verifies
  every call. A breaking change in workflow's API breaks every dependent crate
  at build time, not at runtime.
- **One binary per concern.** CLI is one binary. TUI is one binary. Daemon is
  one binary. Each contains exactly the service code it needs. No runtime
  coupling between binaries beyond Redis events and Postgres state.
- **Refactoring is a `cargo build` away.** Renaming a service function updates
  every caller deterministically.

### Where transports look right but aren't

These are common shapes that look like they need a transport but don't:

- **"The CLI needs to ask the daemon for the current session list."** No — the
  CLI embeds agent_runtime crate, queries Postgres directly via the crate's
  read function. The daemon isn't the keeper of session state; Postgres is.
- **"The TUI needs to know when a todo changes."** No HTTP needed. TUI
  subscribes to Redis pub/sub channel `workflow.todo.*`. Service emits when
  state changes.
- **"The hook receiver needs to tell the daemon something happened."** No HTTP
  or socket. Hook receiver publishes a Redis event. Whoever cares (daemon,
  workers, other services) subscribes.
- **"The API server needs workflow's data to render JSON."** API server is a
  Rust binary that embeds the workflow crate. It calls workflow functions
  directly, then serializes the result for HTTP. No internal HTTP hop.

### Emit failure handling (commit-then-emit and three postures)

State mutations and event publishing cannot be atomic — Postgres and
Redis are separate systems. Every event-driven mutation must pick how to
handle the partial-failure case (DB committed but emit failed, or vice
versa). Two universal rules and three postures by boundary.

**Universal rule 1: commit-then-emit ordering.**

- Emit-then-commit can produce orphan events (emit succeeded, commit
  failed → event refers to nonexistent state). Never do this.
- Commit-then-emit can produce missed events (commit succeeded, emit
  failed → state changed but no one was told). Recoverable per the
  posture below.

**Universal rule 2: callers must be idempotent.**

Retry-safe operations are required regardless of emit posture. Callers
that aren't idempotent will produce double-writes on any retry.

**Three postures, by boundary:**

#### 1. Internal events (within v2 services) — loud-fail

Service mutations that emit events for other v2 services or the v1
bridge use **commit-then-emit with loud failure**.

```
Tx: write state
COMMIT
try: publish event to Redis
  success → return Ok(())
  fail    → return Err(EmitFailed { state_committed: true })
```

Caller sees the error. The error explicitly indicates that state IS
durable (`state_committed: true`) but the event was lost. Caller may
retry the operation; idempotency means the retry detects the existing
state and only re-attempts the emit.

**Why:** single-machine setup, Redis-on-localhost is treated as
critical infrastructure. Redis-down is an operational outage that
should surface loudly, not be swallowed. Consumers can always refresh
from DB if they missed an event.

**Used by:** workflow, identity, agent_runtime, knowledge,
session_ledger, config — every service that emits internal events.

**Future:** per-service upgrade to outbox (below) when multi-machine
or business-critical event-loss tolerance demands it. Don't default
to outbox; add it when a specific service needs it.

#### 2. Inbound external events (hooks, webhooks) — inbox pattern

External systems (Claude Code subprocess hooks, Telegram webhooks,
etc.) fire events ONCE and don't retry on failure. Loud-failing
would lose the event entirely. Inbox pattern guarantees capture.

```
Receiving binary (telec-hook or telec-api) calls integration::ingest_*

[integration service]
Tx: INSERT INTO integration.inbox
    (received_at, source, payload, status='received') RETURNING id
COMMIT  ← durable capture done
try: publish 'integration.inbox.<type>_received' to Redis
  success → UPDATE integration.inbox SET status='published'
  fail    → log loudly, leave status='received'
            (dispatcher worker retries when Redis is back)
return Ok(()) to receiving binary

Receiving binary returns success to external system regardless.
```

The external system always gets a success response because we
durably captured what they sent. Internal fanout happens when Redis
is healthy; recovers when Redis returns.

**Owned by:** `integration` service. The only service that handles
inbound external events.

#### 3. Outbound external delivery — outbox pattern

Services that send to external systems (Telegram messages, Discord
posts, email) need at-least-once delivery semantics. Loud-failing
would mean "the message just didn't go" which is unacceptable.

```
[some service operation]
Tx: write state change AND INSERT INTO integration.outbox
    (target, payload, status='pending') in same transaction
COMMIT  ← state + delivery commitment atomic
return Ok(())

[integration outbox dispatcher worker]
loop:
  SELECT FROM integration.outbox WHERE status='pending'
  for each row: deliver to external target
    success → UPDATE outbox SET status='delivered'
    transient fail → leave status='pending', exponential backoff
    permanent fail → UPDATE outbox SET status='dead_letter'
```

**Owned by:** `integration` service. The legitimate home of the
outbox pattern (see redesign-list #13 on why the hook outbox was
NOT a legitimate use of this pattern).

### Summary of emit-posture decisions

| Boundary | Pattern | Service |
|---|---|---|
| Internal service → internal subscriber | Commit-then-emit, loud-fail | Every service except integration |
| External system → us (inbound) | Inbox + dispatcher retry | integration |
| Us → external system (outbound) | Outbox + dispatcher delivery | integration |

## Failure modes

- **Inventing transports for local calls.** Adding HTTP, gRPC, or Unix
  sockets between Rust binaries that could share a crate. Reintroduces v1's
  coupling under a different protocol. Rejected at review.
- **Defaulting to "the daemon owns everything."** Making the daemon the
  in-process owner of state that another binary needs, forcing transports to
  reach it. The fix is to embed the relevant crate in the binary that needs
  it; the daemon is one binary among many, not the gravity well.
- **Multi-transport event bus.** Adding LOCAL/in-process variants alongside
  Redis "for performance." Different contracts at the same `emit()` signature
  is the bug factory v2 explicitly avoids. One transport for events.
- **Service-as-process.** Treating each service as a long-running process with
  its own port. Services are crates. The binaries that need them embed them.
  Multiple binaries can embed the same service — that's fine, they don't share
  state because state lives in Postgres.
- **Sharing storage across service boundaries.** One service querying another
  service's Postgres schema directly. Same coupling, different transport.
  Each service owns its schema; cross-service queries go through the owning
  service's crate.

## See Also

- docs/project/design/architecture-v2/file-layout.md
  implements this rule.
- docs/project/design/architecture-v2/services.md
  crates.
- docs/project/design/architecture-v2/event-bus-transports.md
  transport Redis event bus.
- docs/project/design/architecture-v2/redesign-list.md
  anti-patterns that v2 must not port.
