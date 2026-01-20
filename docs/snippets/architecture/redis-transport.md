---
id: teleclaude/architecture/redis-transport
type: architecture
scope: project
description: Redis Streams transport for cross-computer request/response and peer discovery.
requires:
  - ../architecture/adapter-client.md
  - ../architecture/cache.md
  - ../reference/event-types.md
---

Purpose
- Provide reliable cross-computer messaging and responses between TeleClaude daemons.

Inputs/Outputs
- Inputs: remote commands on per-computer message streams, registry heartbeats.
- Outputs: responses on output:{message_id} streams and cached snapshots via daemon cache updates.

Primary flows
- Each computer polls a Redis stream named for its computer identity.
- Requests are answered on output:{message_id} streams for one-shot responses.
- Heartbeats maintain a registry of online computers with TTL-based expiry.
- Project and todo digests trigger cache refresh on peers.

Invariants
- Transport adapter implements RemoteExecutionProtocol for request/response.
- Transport adapter never performs UI messaging.
- Redis is optional; Telegram multi-computer operation does not require it.

Failure modes
- Redis connectivity loss disables cross-computer operations but leaves local sessions intact.
