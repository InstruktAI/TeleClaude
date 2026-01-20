---
id: teleclaude/architecture/redis-transport
type: architecture
scope: project
description: Redis Streams transport for cross-computer requests, responses, and output streaming.
requires:
  - ../architecture/adapter-client.md
  - ../architecture/cache.md
  - ../reference/event-types.md
---

Purpose
- Provide reliable cross-computer messaging and streaming between TeleClaude daemons.

Inputs/Outputs
- Inputs: remote commands on per-computer message streams, registry heartbeats.
- Outputs: responses on output streams and cached snapshots via daemon cache updates.

Primary flows
- Each computer polls a Redis stream named for its computer identity.
- Session output is published to output:{session_id} streams for remote consumers.
- Heartbeats maintain a registry of online computers with TTL-based expiry.
- Project and todo digests trigger cache refresh on peers.

Invariants
- Transport adapter implements RemoteExecutionProtocol for request/response and streaming.
- Transport adapter never performs UI messaging.

Failure modes
- Redis connectivity loss disables cross-computer operations but leaves local sessions intact.
