---
description:
  Redis Streams transport for cross-computer request/response and peer
  discovery.
id: teleclaude/architecture/redis-transport
scope: project
type: architecture
---

# Redis Transport — Architecture

## Purpose

- @docs/architecture/adapter-client
- @docs/architecture/cache
- @docs/reference/event-types

- Provide reliable cross-computer messaging and responses between TeleClaude daemons.

- Inputs: remote commands on per-computer message streams, registry heartbeats.
- Outputs: responses on output:{message_id} streams and cached snapshots via daemon cache updates.

- Each computer polls a Redis stream named for its computer identity.
- Requests are answered on output:{message_id} streams for one-shot responses.
- Heartbeats maintain a registry of online computers with TTL-based expiry.
- Project and todo digests trigger cache refresh on peers.

- Transport adapter implements RemoteExecutionProtocol for request/response.
- Transport adapter never performs UI messaging.
- Redis is optional; Telegram multi-computer operation does not require it.

- Redis connectivity loss disables cross-computer operations but leaves local sessions intact.

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
