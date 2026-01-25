---
description: Transport adapters handle cross-computer request/response and peer discovery.
id: teleclaude/architecture/transport-adapter
scope: project
type: architecture
---

# Transport Adapter — Architecture

## Purpose

- @docs/concept/adapter-types

Responsibilities

- Deliver remote requests to target computers.
- Support one-shot responses for remote requests.
- Maintain peer discovery and heartbeat data.
- Preserve request/response correlation across the transport boundary.

Boundaries

- No human-facing message rendering or UX cleanup.
- No domain decisions; transport is purely delivery.

Invariants

- Transport only moves structured commands and results.
- Failures must be reported explicitly to the caller.

- TBD.

- TBD.

- TBD.

- TBD.

## Inputs/Outputs

- TBD.

## Invariants

- TBD.

## Primary flows

- TBD.

## Failure modes

- TBD.
