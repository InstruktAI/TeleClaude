---
description: The boundary among authoritative source owners, daemon cache materialization, and UI state projection.
---

# Cache System — Design

## Required reads

@docs/local/adr/0013-unified-cluster-events.md

## Purpose

Separate source truth, daemon read state, and UI presentation. Cache ownership
is `local/projects/teleclaude/design/architecture/cache`; connection projection
is `local/projects/teleclaude/design/architecture/api-server`; TUI session-view
behavior is `local/projects/teleclaude/spec/feature/tui/session-visibility`.

## Inputs/Outputs

Authoritative owners supply records and changes to the daemon. The cache
materializes those records; the API projects eligible snapshots and changes;
clients render the delivered state and submit explicit commands for mutations.

## Invariants

Each boundary retains its owner's responsibility. UI rendering does not become
peer discovery, cache population does not become authorization, and immediate
cached reads do not become authoritative writes.

## Primary flows

Local source changes and remote cluster changes converge in the daemon cache.
HTTP readers query that view. UI connections receive state through the API's
projection contract. A UI reconnect establishes a current projection from the
available daemon state; it does not recover a daemon's missed cluster events.

## Failure modes

A missing source record, an incomplete cache, and a client missing an available
record are different boundaries. Establish which boundary diverges before
changing discovery, materialization, or UI delivery. Recovery remains with the
owner at that boundary.

## See Also

- docs/local/design/architecture/cache.md
- docs/local/design/architecture/api-server.md
- docs/local/spec/feature/tui/session-visibility.md
