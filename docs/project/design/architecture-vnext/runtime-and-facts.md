---
visibility: internal
description: vNext privilege-broker topology, typed fact law, durable delivery, session execution, and daemon boundaries.
---

# vNext Runtime and Facts — Design

## Required reads

@docs/project/design/architecture-vnext/overview.md
@docs/project/design/architecture-vnext/authorization.md

## Purpose

Define how commands execute without giving agents database or secret access,
how durable facts replace behavioral inference, and how long-running loops
mount without turning the daemon into a business-logic owner.

## Inputs/Outputs

**Inputs:** authenticated UDS commands, typed domain verbs, domain state,
session capabilities, external adapter results, and durable consumer cursors.

**Outputs:** committed domain state, immutable facts, queryable obligations,
adapter side effects, liveness, and reconstructable delivery progress.

## Invariants

- Only `telec-daemon` holds database credentials and encryption-root access.
  `telec` and `telec-hook` are unprivileged UDS protocol clients.
- `telec-daemon` runs under a dedicated OS service identity. Per-user
  `telec-executor` processes launch agent runtimes and hold no database,
  bootstrap, or encryption-root authority.
- The UDS boundary authenticates every request. Localhost or filesystem
  proximity alone never establishes trust.
- The daemon is a privilege broker and composition root. It owns no business
  state, cache, inferred bookkeeping, or hidden source of truth.
- A domain mutation writes state and its immutable fact row in one Postgres
  transaction with a stable natural idempotency key.
- Facts are authority. Events are post-commit notifications or projections.
  Signals are ephemeral in-process or database wakes.
- Postgres `LISTEN/NOTIFY` carries wakeups only. Consumers requery facts using
  durable per-consumer cursors.
- Redis never holds local truth. It is an optional fleet bridge for committed
  facts and uses stable keys with durable inbound ingestion.
- No event or required operation is silently dropped because a transport is
  absent.
- Cross-domain writes never share a transaction. Applications order verbs and
  repair partial progress using durable facts.
- Pane rendering and transcript observation support display and liveness only.
  They never prove completion, review, or domain state.
- The effective agent sandbox profile is service-owned, digest-verified before
  every spawn, and cannot be widened by repository or same-user agent input.

## Primary flows

### Cut-1 topology

```mermaid
flowchart LR
    H[Human] --> TC[telec CLI and TUI]
    TC -->|authenticated UDS| D
    D -->|peer-authenticated spawn, signal, reap| EX[telec-executor]
    EX -->|fixed sandbox profile and brief| A[Codex agent process]
    A --> AC[telec verb client]
    A --> HK[telec-hook]
    AC -->|session capability over UDS| D
    HK -->|session capability over UDS| D
    EX -->|attenuated launch, liveness, exit reports| D
    subgraph D[telec-daemon]
        U[UDS boundary] --> AU[authenticate and authorize]
        AU --> J[application journey]
        J --> V[domain verb]
    end
    V -->|state and fact transaction| PG["Postgres"]
```

The daemon starts in cut 1 because it is the security boundary separating
agent processes from privileged storage and credentials. Local-first means no
network dependency; it does not mean no local process dependency. The daemon
must restart quickly because all durable state remains in Postgres.

### Executor boundary

The daemon alone commands an executor. The executor authenticates the daemon
by service UID and protocol credential, accepts no authority-bearing request
from a same-user process, and never mints or requests a session brief. Its
Machine credential permits only spawn-result, liveness, and exit reporting.
Those reports cannot complete a work item, approve a review, or discharge an
obligation; an unproven exit produces `lost`, never `completed`.

The Codex permission profile lives in a service-owned read-only location. The
daemon supplies its expected digest and the executor verifies the effective
profile before every spawn. The profile confines writes to the registered
worktree and session directory, denies direct network access, protects host and
sibling-session credentials, and permits the assigned daemon UDS path. The
single daemon socket remains protected by per-session capability
authentication; socket allowlisting is an additional process boundary, not an
authorization substitute.

On macOS the executor is a LaunchAgent and therefore becomes available after
the human login context exists. On Linux it is a `systemd --user` unit with
lingering enabled. The daemon is independently supervised as a LaunchDaemon or
system unit.

### Fact lifecycle

```mermaid
sequenceDiagram
    participant A as Application
    participant P as Context Postgres
    participant N as NOTIFY
    participant C as Durable consumer
    participant R as Redis bridge
    A->>P: verb command plus natural idempotency key
    P->>P: transaction writes aggregate state and fact
    P-->>A: committed result
    P->>N: wake after commit
    N-->>C: wake only
    C->>P: read facts after owned cursor
    C->>P: advance cursor after successful handling
    C->>R: publish cluster-scoped committed fact
```

Each context defines its fact payloads in core and stores them in its schema.
Foundation provides envelope, correlation, causation, lineage, and cursor
contracts. Payload versions use explicit supported-version decoders. Relational
state changes through forward migrations; generic lazy upcasting is not a
platform mechanism.

### Typed obligations

The verb performing an operation records its resulting facts and obligations.
`obligation list` is a query over durable state. Discharge is a typed verb tied
to evidence. Checkpoint behavior is therefore a thin reminder surface, not an
engine that infers whether shell commands or transcript phrases satisfied a
requirement.

### Cross-domain ordering

An application journey composes domain transactions in a declared order. A
dispatch that needs new authority first issues the Access brief, then records
the Sessions dispatch. If the second step fails, reconciliation revokes the
orphan brief. The general rule is grant before use and revoke on orphan.

No application passes transaction handles across contexts. Facts make partial
progress visible and retryable without dual writes.

### Runtime growth

Later cuts mount sanctioned loops on an explicit supervisor seam:

- fact dispatcher and cockpit refresh;
- webhook ingress and communications delivery;
- Redis fleet bridge and remote fact ingestion;
- scheduling and reconciliation.

Each loop invokes application journeys, owns a durable cursor where relevant,
and can restart independently. A loop does not move its state into the daemon.

## Failure modes

- Hooks or CLI clients connect directly to Postgres and bypass authorization.
- The daemon accumulates cache, lifecycle state, business rules, or inference
  bookkeeping and becomes the system's authority.
- A consumer acknowledges before side effects complete or advances another
  consumer's cursor.
- Random idempotency keys make retries indistinguishable from new operations.
- Redis publication is mistaken for durable consumption.
- `NOTIFY` payloads become a second event contract.
- A missing hook fact is repaired by pane parsing instead of fixing capability,
  hook delivery, or timeout semantics.
- Two contexts are updated in one database transaction or through direct schema
  access.
- An executor accepts same-user commands, holds a workflow-capable credential,
  or launches after its sandbox-profile digest changes.
- The daemon launches an agent runtime directly and gains access to the human's
  provider credentials or worktree authority.

## See Also

- docs/project/adr/0068-vnext-replaces-v1-through-authoritative-cuts.md
- docs/project/design/architecture-vnext/code-organization.md
- docs/project/design/architecture-vnext/cutover-program.md
