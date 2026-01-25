---
description:
  DaemonCache snapshot layer for computers, projects, todos, sessions,
  and agent availability.
id: teleclaude/architecture/cache
scope: project
type: architecture
---

# Cache — Architecture

## Purpose

- @docs/concept/resource-models
- @docs/standard/cache-refresh-strategy

- Provide instant, cached reads for API and remote data views.

- Inputs: cache updates from adapters and daemon events.
- Outputs: snapshot reads plus update notifications to subscribers.

- Serve cached data immediately; schedule refresh when TTL expires.
- Use per-computer digest/version fields to trigger refresh for projects and todos.
- Sessions are updated by events rather than TTL polling.

- Cache is read-only and not the source of truth.
- Stale data can be served to keep APIs responsive.

- Missing cache entries return empty lists until refresh completes.

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
