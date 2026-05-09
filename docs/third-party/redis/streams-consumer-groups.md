---
id: third-party/redis/streams-consumer-groups
type: third-party
scope: project
description: Redis Streams consumer-group semantics used for durable delivery and logical subscriber fan-out.
---
# Redis Streams Consumer Groups

## Validated Facts

- A Redis stream is an append-only event log that supports multiple consumption strategies, including consumer groups. Redis documents streams as suitable for recording and syndicating events.
- `XADD` appends entries to a stream. `XREADGROUP` reads new or historical stream entries for a named consumer inside a named consumer group.
- `XACK` acknowledges successfully processed entries for a consumer group. Until an entry is acknowledged, Redis tracks it in the group's pending entries list.
- A stream may have multiple consumer groups. Each group has its own delivery and acknowledgment state, which is the basis for independent logical subscribers each observing the same stream entry.
- Consumers inside the same consumer group coordinate work for that group; they are not independent broadcast subscribers. Use separate consumer groups for independent logical subscribers that must each receive every stream entry.
- `XCLAIM` and `XAUTOCLAIM` transfer ownership of stale pending entries to another consumer in the same group. Claiming can increment delivery-attempt metadata, which supports retry and dead-letter decisions.
- Redis acknowledges that duplicate processing remains possible in general, so handlers using consumer-group redelivery must be idempotent.

## TeleClaude Usage

For internal EventBus fan-out, one Redis stream can carry all internal event envelopes. Each logical subscriber that must independently observe every event needs its own consumer group on that stream. Multiple process instances for the same logical subscriber may share that subscriber's group to coordinate failover and work claiming.

This differs from a single consumer group containing all subscribers: a single group distributes entries among its consumers, so it behaves like a work queue for that group and does not preserve broadcast fan-out across independent subscribers.

## Sources

- https://redis.io/docs/latest/develop/data-types/streams/
- https://redis.io/docs/latest/commands/xreadgroup/
- https://redis.io/docs/latest/commands/xclaim/
