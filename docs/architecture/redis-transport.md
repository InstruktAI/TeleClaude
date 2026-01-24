---
description:
  Redis Streams transport for cross-computer request/response and peer
  discovery.
id: teleclaude/architecture/redis-transport
scope: project
type: architecture
---

## Required reads

- @teleclaude/architecture/adapter-client
- @teleclaude/architecture/cache
- @teleclaude/reference/event-types

## Purpose

- Provide reliable cross-computer messaging and responses between TeleClaude daemons.

## Inputs/Outputs

- Inputs: remote commands on per-computer message streams, registry heartbeats.
- Outputs: responses on output:{message_id} streams and cached snapshots via daemon cache updates.

## Primary flows

- Each computer polls a Redis stream named for its computer identity.
- Requests are answered on output:{message_id} streams for one-shot responses.
- Heartbeats maintain a registry of online computers with TTL-based expiry.
- Project and todo digests trigger cache refresh on peers.

## Invariants

- Transport adapter implements RemoteExecutionProtocol for request/response.
- Transport adapter never performs UI messaging.
- Redis is optional; Telegram multi-computer operation does not require it.

## Failure modes

- Redis connectivity loss disables cross-computer operations but leaves local sessions intact.
