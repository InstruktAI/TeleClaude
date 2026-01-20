---
id: architecture/cache
description: DaemonCache for remote computers, sessions, projects, and todos with TTL and subscriptions.
type: architecture
scope: project
requires: []
---

# Daemon Cache

## Purpose
- Provide a TTL-based cache for remote data and a notification channel for updates.

## Inputs/Outputs
- Inputs: cache updates from transports or API server; interest subscriptions.
- Outputs: cached session/project/todo/computer data; subscriber callbacks.

## Invariants
- Computers expire after ~60s; projects and todos after ~5 minutes; sessions are non-expiring.
- Cache keys include computer names to support cross-computer filtering.
- Subscribers are notified on cache updates (used by API server and transports).

## Primary Flows
- Update cache from remote heartbeats and data fetches.
- Serve API requests from cache with optional stale filtering.
- Track interest per data type to throttle remote refreshes.

## Failure Modes
- Stale entries are silently dropped on access; missing entries trigger refresh upstream.
