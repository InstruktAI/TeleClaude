---
id: architecture/api-server
description: Local HTTP and WebSocket API for session control and status updates.
type: architecture
scope: project
requires:
  - adapter-client.md
  - cache.md
  - event-model.md
---

# API Server

## Purpose
- Provide a local Unix-socket HTTP/WS API for TeleClaude control and status.

## Inputs/Outputs
- Inputs: REST calls for sessions/projects/todos, WebSocket subscriptions, create/send commands.
- Outputs: JSON responses, WebSocket events for session start/close/update.

## Invariants
- If cache is available, responses merge local DB sessions with cached remote sessions.
- WebSocket clients can subscribe to per-computer data types (sessions/projects/todos/computers).
- API server registers for session update events to keep cache in sync.

## Primary Flows
- Start: mount FastAPI routes and begin serving on Unix socket.
- REST: list sessions/projects/todos, create sessions, send messages via AdapterClient.
- WS: push debounced refresh events and session lifecycle updates.

## Failure Modes
- Cache unavailable → API serves local-only data.
- Unexpected exits are detected by lifecycle and trigger restart with backoff.
