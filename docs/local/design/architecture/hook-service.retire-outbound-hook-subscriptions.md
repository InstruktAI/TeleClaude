---
description: 'Contract-based routing of relayed external events and the deployment fan-out to the in-process handlers the daemon registers.'
visibility: 'public'
---

# Hook Service — Design

## Required reads

- @docs/local/design/architecture/outbox.md
- @docs/local/design/architecture/daemon.md

## Purpose

Route the external events every computer receives to the in-process handlers
that react to them:

1. Relayed GitHub, WhatsApp and native events, which the ingress publishes on
   the platform event stream, are rebuilt on every computer and dispatched
   locally. The ingress endpoints themselves are owned by
   `local/projects/teleclaude/spec/feature/integration/inbound-webhook-endpoint-framework`.
2. Deployment `version_available` signals arriving on the cross-host fan-out
   stream are dispatched the same way
   (`local/projects/teleclaude/spec/feature/integration/deployment-version-fanout`).

The hook service is a **monolith subsystem** inside the TeleClaude daemon. Its
routing table is built in memory at startup from contracts the daemon registers
itself; it keeps no table of its own and sends nothing out of the computer.

### Two hook systems in TeleClaude

| System                      | Storage       | Purpose                                       | Producer                                    | Consumer                    |
| --------------------------- | ------------- | --------------------------------------------- | ------------------------------------------- | --------------------------- |
| **Hook outbox** (agent CLI) | `hook_outbox` | Durable ingest of raw agent CLI hook events   | Agent hook receiver (`bin/hook-receiver`)   | Daemon outbox worker        |
| **Hook service** (this doc) | in memory     | Route external events to in-process reactions | Relay delivery, deployment fan-out consumer | `HookDispatcher` → handlers |

The hook outbox is the ingestion layer for agent CLI events
(`local/projects/teleclaude/design/architecture/outbox`). The hook service never
sees those events: internal daemon events reach their consumers through the
event bus and the platform event stream, not through this dispatcher.

## Inputs/Outputs

**Inputs:**

- Relayed inbound events read from the platform event stream by each computer's
  relay delivery
- Deployment fan-out events read from the cross-host fan-out stream
- The built-in contracts the daemon registers at startup

**Outputs:**

- Internal handler invocations (async callables called in-process)

## Invariants

- **Contract-first routing.** An event reaches a handler only through a
  matching contract. No contract = no delivery.
- **The daemon is the only contract author.** Every contract is registered
  programmatically at startup and names a handler the daemon registered in the
  same process. Nothing outside the daemon's own code declares, creates, or
  removes a contract.
- **Every contract names a handler.** A contract without a handler cannot be
  constructed, so every match has a destination.
- **Canonical event format.** Every event is normalized to
  `HookEvent(source, type, timestamp, properties, payload)` before it enters
  the dispatch pipeline.
- **Handlers see their contract.** An internal handler receives the matched
  contract alongside the event, so a handler shared by several contracts knows
  which one matched.
- **One delivery per computer.** A relayed inbound event is dispatched once on
  each computer, by that computer's relay delivery.

## Primary flows

### 1. Relayed inbound event → dispatch

The ingress verifies an external request, translates it, and publishes it on
the platform event stream at cluster scope
(`local/projects/teleclaude/spec/feature/integration/single-ingress-webhook-termination`).
Every computer, the ingress included, reads the stream through its own relay
delivery, which turns each relayed GitHub, WhatsApp or native event back into
the normalized `HookEvent` the ingress produced and dispatches it locally.

```
Ingress endpoint        Platform event stream        Relay delivery (each computer)     HookDispatcher
  │                            │                              │                               │
  ├─ verify + translate        │                              │                               │
  ├─ publish <domain>.<name> ─►│                              │                               │
  │                            ├─ per-computer read ─────────►│                               │
  │                            │                              ├─ rebuild HookEvent            │
  │                            │                              ├─ dispatch(event) ────────────►│
  │                            │                              │                               ├─ match contracts
  │                            │                              │                               └─ call each handler
```

**Normalizer contract:** A normalizer turns one provider's payload into
canonical `HookEvent` instances at the ingress. The GitHub and WhatsApp
normalizers are built in; a native request needs none, because the producer
already speaks the platform's event shape. A relayed event whose subject is a
company carries that company as its `company` property. A native event matches
no built-in contract; platform consumers read native events from the platform
event stream.

### 2. Deployment fan-out → dispatch

The deployment handler publishes a `version_available` event on the cross-host
fan-out stream. Each other computer's fan-out consumer reads it, skips the
events its own computer published, and dispatches the rest through the same
dispatcher (`local/projects/teleclaude/spec/feature/integration/deployment-version-fanout`).

### 3. Built-in contracts

The daemon's startup wiring of the hook service owns the built-in contracts:
which events each selects and which handler it names. Every reaction the hook
service performs — WhatsApp conversation handling and the deployment update —
receives its events through a built-in contract. A contract holds its identity,
the criteria an event must meet, and the handler it names; the contract model
in the hook package owns that shape.

**Matching:** The matcher evaluates an event against a contract's criteria using
AND logic — all criteria must pass. A criterion matches a value exactly or
against one of several values, matches a wildcard pattern, requires only that
the value is present, or, when not required, declares interest without
filtering.

### 4. Daemon initialization wiring

At startup the daemon creates the handler registry and the contract registry,
registers each built-in handler and its contract, creates the dispatcher over
both registries, starts the deployment fan-out consumer, and starts the
per-computer relay delivery that feeds the dispatcher. The hook package
(`teleclaude/hooks/`) holds the event and contract model, the registries, the
matcher, the dispatcher, relay delivery and the ingress endpoints.

## Failure modes

- **Internal handler exception.** Caught per handler. Other matching contracts
  still receive the event. No retry — internal handlers are expected to be
  idempotent and fast.
- **Handler key not registered.** The dispatcher logs that the handler was not
  found and continues with the next matching contract. The daemon registers
  every built-in handler before its contract, so this marks a defect in the
  startup wiring.
- **Event matching no contract.** Dispatched and dropped without a trace. A
  relayed native event always takes this path on the dispatcher.
- **Daemon restart.** The routing table is rebuilt from the daemon's own
  registrations. Handler invocations that were in flight are lost; they were
  in-process, not persisted. A relayed event the relay delivery had not yet
  acknowledged is handed to the dispatcher again under the platform event
  stream's redelivery.
