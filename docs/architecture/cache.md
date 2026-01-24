---
description:
  DaemonCache snapshot layer for computers, projects, todos, sessions,
  and agent availability.
id: teleclaude/architecture/cache
scope: project
type: architecture
---

## Required reads

- @teleclaude/concept/resource-models
- @teleclaude/standard/cache-refresh-strategy

## Purpose

- Provide instant, cached reads for API and remote data views.

## Inputs/Outputs

- Inputs: cache updates from adapters and daemon events.
- Outputs: snapshot reads plus update notifications to subscribers.

## Primary flows

- Serve cached data immediately; schedule refresh when TTL expires.
- Use per-computer digest/version fields to trigger refresh for projects and todos.
- Sessions are updated by events rather than TTL polling.

## Invariants

- Cache is read-only and not the source of truth.
- Stale data can be served to keep APIs responsive.

## Failure modes

- Missing cache entries return empty lists until refresh completes.
