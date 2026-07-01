---
description: 'Redis Streams transport for cross-computer request/response and peer discovery.'
visibility: 'public'
---

# Redis Transport — Design

## Purpose

- Provide reliable cross-computer messaging and responses between TeleClaude daemons.

- Each computer polls a Redis stream named for its computer identity.
- Requests are answered on `output:{computer}:{message_id}` streams for one-shot responses.
- Heartbeats maintain a registry of online computers with TTL-based expiry.
- Project and todo digests trigger cache refresh on peers.

- Redis transport implements RemoteExecutionProtocol for request/response.
- Redis transport never performs UI messaging.
- Redis is optional; Telegram multi-computer operation does not require it.

```mermaid
flowchart LR
    CompA["Computer A<br/>(macbook)"]
    CompB["Computer B<br/>(raspi)"]
    Redis["Redis Streams"]

    CompA -->|messages:raspi| Redis
    Redis -->|output:macbook:msg_123| CompA
    CompB -->|poll:macbook| Redis
    CompB -->|heartbeat| Redis
```

## Inputs/Outputs

**Inputs:**

- Commands on `messages:{computer_name}` streams from remote peers
- Heartbeat messages with computer status, projects digest, todos digest
- Response streams `output:{computer_name}:{message_id}` for request/reply pattern

**Outputs:**

- Command responses published to caller's response stream
- Heartbeat broadcasts every 30s with system stats and digest fingerprints
- Cache invalidation triggers when digests change

## Invariants

- **Optional Dependency**: Redis is never required for local operations or Telegram multi-computer operation.
- **Stream Per Computer**: Each computer polls exactly one command stream named after its computer identity.
- **One-Shot Responses**: Response streams are created per-message and auto-expire after TTL.
- **Heartbeat TTL**: Computer registry entries expire after 60s without heartbeat; marks computer offline.
- **Digest-Driven Refresh**: Projects/todos cache refreshes only when heartbeat digest changes, not on every beat.
- **Single Connection Lifecycle**: Redis connection is managed by one reconnect loop; all tasks wait on readiness.

- **Bounded Backpressure**: The shared Redis client draws connections from a single bounded pool that blocks a caller for a bounded time when every connection is in use, rather than failing immediately. A momentary saturation waits for a connection to be released instead of surfacing a connection error to every subsystem at once; only a saturation that outlasts the bound raises.

## Primary flows

### 1. Cross-Computer Command Execution

```mermaid
sequenceDiagram
    participant MasterAI
    participant RedisA as Redis (Computer A)
    participant RedisB as Redis (Computer B)
    participant WorkerAI

    MasterAI->>RedisA: Publish to messages:computerB
    RedisB->>RedisB: Poll stream
    RedisB->>WorkerAI: Execute command
    WorkerAI->>RedisB: Return result
    RedisB->>RedisA: Publish to output:computerA:msg_123
    RedisA->>MasterAI: Deliver response
```

### 2. Heartbeat and Discovery

```mermaid
sequenceDiagram
    participant CompA as Computer A
    participant Redis
    participant CompB as Computer B
    participant Cache

    loop Every 30s
        CompA->>Redis: Publish heartbeat (status, digests)
        CompB->>Redis: Publish heartbeat (status, digests)
    end

    Redis->>CompA: Read all heartbeats
    CompA->>Cache: Update computer registry
    CompA->>Cache: Check projects digest
    alt Digest changed
        CompA->>Redis: Request full projects from CompB
        Redis->>CompB: Fetch projects
        CompB->>Redis: Return list
        Redis->>CompA: Update cache
    else Unchanged
        CompA->>CompA: Keep existing cache
    end
```

### 3. Digest-Based Cache Invalidation

| Component | Heartbeat Field      | Cache Action                    |
| --------- | -------------------- | ------------------------------- |
| Projects  | `projects_digest`    | Refresh if changed              |
| Todos     | `todos_digest`       | Refresh if changed              |
| Sessions  | N/A                  | Event-driven only (no digest)   |
| Stats     | `cpu`, `mem`, `disk` | Update immediately on heartbeat |

### 4. Stream Cleanup

- Command streams: Trimmed to max 10,000 messages (MAXLEN ~10000 APPROXIMATE)
- Response streams: Auto-expire after 1 hour (TTL)
- Heartbeat entries: Redis key expiry after 60s

The transport layer reads each command's `response_mode` to determine caller wait
behavior: `IMMEDIATE` awaits the handler result, `FIRE_AND_FORGET` returns a 202
with `completion_event`, and `RECEIPT` delegates to `OperationsService`. The handler
table and the response_mode layer are orthogonal — any handler can operate under any
mode. See command-classification for the full dispatch model.

<!-- planned:commands-carry-target-computer -->

### 5. Command as wire payload

The unit crossing the transport is the **serialized command** — the same `InternalCommand`
the origin's API boundary built — carried on the `messages:{computer}` stream with its
`session_id` and identity metadata, and answered on `output:{computer}:{message_id}`. The
owning computer deserializes the payload back into the identical command type and dispatches
it through the same handler table and `response_mode` layer it uses for locally-originated
commands, keyed on `command_type`.

There is no second command vocabulary: the transport does not translate a command into a
string that the peer re-parses, and there are no per-command remote wrappers. Command
serialization is the single crossing contract; adding a command makes it forwardable with no
transport change. The routing decision is the command's `computer` field — foreign computer
forwards, local computer (or unset) executes in place. See command-classification for the
dispatch model.
<!-- /planned:commands-carry-target-computer -->

## Failure modes

- **Redis Unavailable**: Daemon starts without Redis transport. Cross-computer commands fail. Local and Telegram operations unaffected.
- **Network Partition**: Computer heartbeats stop arriving. Registry marks computer offline after TTL. Commands to partitioned computer timeout.
- **Stream Accumulation**: If consumer lags, streams grow beyond MAXLEN. Oldest messages trimmed. Commands may be lost if not processed in time.
- **Response Stream Collision**: Extremely rare. Two messages with same ID overwrite response stream. Mitigated by UUID message IDs.
- **Digest False Positive**: Digest unchanged but content actually changed. Next TTL-based refresh corrects it (max 5min delay).
- **Heartbeat Storm**: Many computers restart simultaneously and publish heartbeats. Redis handles gracefully; cache refresh tasks may queue.
- **Reconnect Storm Prevention**: Redis reconnects are serialized; tasks wait on readiness to avoid connection floods.
- **Stale Registry**: Computer dies without sending offline heartbeat. Registry shows online until TTL expires (max 60s stale window).
