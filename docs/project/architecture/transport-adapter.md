---
description: Transport adapters handle cross-computer request/response and peer discovery.
id: teleclaude/architecture/transport-adapter
scope: project
type: architecture
---

# Transport Adapter — Architecture

## Required reads

- @docs/project/concept/adapter-types.md

## Purpose

Responsibilities

- Deliver remote requests to target computers.
- Support one-shot responses for remote requests.
- Maintain peer discovery and heartbeat data.
- Preserve request/response correlation across the transport boundary.

Boundaries

- No human-facing message rendering or UX cleanup.
- No domain decisions; transport is purely delivery.

Invariants

- Transport only moves structured commands and results.
- Failures must be reported explicitly to the caller.

## Inputs/Outputs

**Inputs:**

- Remote command requests via Redis streams (messages:{computer})
- Response payloads from remote computers (output:{message_id})
- Heartbeat data from peer computers (computer:{name} keys with TTL)
- Digest updates (projects_digest, todos_digest)
- Session event notifications (session start, stop, update)

**Outputs:**

- Command messages sent to target computer's stream
- Response payloads sent to origin computer's output stream
- Heartbeat keys published with computer metadata and digests
- Cache refresh triggers when peer digests change
- Session event propagation to remote initiators

## Invariants

- **No UX Rendering**: Transport never sends UI messages; only structured commands and responses.
- **Correlation Preservation**: Request-response correlation via request_id; responses routed to correct caller.
- **Explicit Failure Reporting**: Errors always returned as {status: "error", error: "..."} envelopes; no silent failures.
- **Stream FIFO Order**: Messages processed in order sent (XREAD guarantees ordering within stream).
- **TTL-Based Discovery**: Computer registry uses Redis key expiration; dead computers auto-removed after heartbeat_ttl.

## Primary flows

### 1. Transport Architecture

```mermaid
flowchart TD
    Comp1[Computer 1]
    Comp2[Computer 2]
    Comp3[Computer 3]
    Redis["Redis"]
    Stream1[messages:comp1]
    Stream2[messages:comp2]
    Stream3[messages:comp3]
    HeartbeatKeys[computer:* keys with TTL]

    Comp1 -->|XADD messages:comp2| Redis
    Comp2 -->|XADD messages:comp1| Redis
    Comp3 -->|XADD messages:comp1| Redis
    Redis -->|XREAD| Stream1
    Redis -->|XREAD| Stream2
    Redis -->|XREAD| Stream3
    Comp1 -->|SET computer:comp1 TTL=60s| HeartbeatKeys
    Comp2 -->|SET computer:comp2 TTL=60s| HeartbeatKeys
    Comp3 -->|SET computer:comp3 TTL=60s| HeartbeatKeys
```

### 2. Remote Command Execution

```mermaid
sequenceDiagram
    participant MasterAI
    participant Comp1 as Computer 1 (origin)
    participant Redis
    participant Comp2 as Computer 2 (target)
    participant WorkerAI

    MasterAI->>Comp1: teleclaude__start_session(computer="comp2", ...)
    Comp1->>Comp1: Generate request_id
    Comp1->>Redis: XADD messages:comp2 {type:"command", command:"new_session", payload:{...}, origin:"comp1", request_id:"abc123"}
    Redis->>Comp2: XREAD messages:comp2 (polling loop)
    Comp2->>Comp2: Parse message → CreateSessionCommand
    Comp2->>Comp2: Execute via CommandService
    Comp2->>WorkerAI: Start AI session
    Comp2->>Redis: XADD output:abc123 {status:"success", data:{session_id:"..."}}
    Redis->>Comp1: XREAD output:abc123 (awaiting response)
    Comp1->>Comp1: Parse response envelope
    Comp1->>MasterAI: Return session_id
```

### 3. Heartbeat & Discovery

```mermaid
sequenceDiagram
    participant Comp1
    participant Redis
    participant Comp2

    loop Every 30s
        Comp1->>Comp1: Collect metadata (projects_digest, todos_digest)
        Comp1->>Redis: SET computer:comp1 '{"status":"online","projects_digest":"abc","todos_digest":"def"}' EX 60
    end

    loop Every 5s
        Comp2->>Redis: KEYS computer:*
        Redis->>Comp2: [computer:comp1, computer:comp3, ...]
        Comp2->>Redis: GET computer:comp1
        Redis->>Comp2: {"status":"online","projects_digest":"abc",...}
        Comp2->>Comp2: Compare projects_digest with last-seen
        alt Digest changed
            Comp2->>Comp2: Trigger cache refresh for comp1 projects
        end
    end
```

### 4. Digest-Based Cache Invalidation

```mermaid
flowchart TD
    HeartbeatLoop[Heartbeat loop: every 30s]
    ReadDigest[Read peer heartbeat]
    CompareDigest{Digest changed?}
    CheckCooldown{Within cooldown?}
    ScheduleRefresh[Schedule cache refresh]
    SkipRefresh[Skip refresh]
    UpdateLastSeen[Update peer_digests cache]
    Done[Continue]

    HeartbeatLoop --> ReadDigest
    ReadDigest --> CompareDigest
    CompareDigest -->|Yes| CheckCooldown
    CompareDigest -->|No| UpdateLastSeen
    CheckCooldown -->|No| ScheduleRefresh
    CheckCooldown -->|Yes| SkipRefresh
    ScheduleRefresh --> UpdateLastSeen
    SkipRefresh --> UpdateLastSeen
    UpdateLastSeen --> Done
```

### 5. Request-Response Correlation

| Component    | Field         | Value                          | Purpose                        |
| ------------ | ------------- | ------------------------------ | ------------------------------ |
| Origin       | request_id    | Generated UUID                 | Correlation key                |
| Origin       | origin        | "comp1"                        | Return address                 |
| Redis Stream | message_id    | "1234567890-0"                 | Redis-assigned stream entry ID |
| Target       | request_id    | From message (preserved)       | Response routing               |
| Target       | output stream | output:{request_id}            | Dedicated response channel     |
| Origin       | XREAD         | output:{request_id} BLOCK 5000 | Awaits response with timeout   |

### 6. Command Translation

```mermaid
sequenceDiagram
    participant Redis
    participant Transport
    participant CommandMapper
    participant CommandService

    Redis->>Transport: XREAD messages:comp2 entry
    Transport->>Transport: Parse RedisInboundMessage
    Transport->>CommandMapper: Map command field to typed command
    CommandMapper->>Transport: CreateSessionCommand object
    Transport->>CommandService: Execute command
    CommandService->>Transport: Result
    Transport->>Transport: Build response envelope
    Transport->>Redis: XADD output:{request_id} envelope
```

### 7. Session Event Propagation

| Event              | Local Action                     | Remote Action                            |
| ------------------ | -------------------------------- | ---------------------------------------- |
| SESSION_STARTED    | Emit to local adapters           | Send to origin computer if remote        |
| SESSION_CLOSED     | Emit to local adapters           | Send to origin computer if remote        |
| SESSION_UPDATED    | Emit to local adapters           | Send to origin if title/status changed   |
| AGENT_NOTIFICATION | Inject to listener tmux sessions | Send to caller computer if remote caller |

### 8. Stream Cleanup

```mermaid
sequenceDiagram
    participant Transport
    participant Redis

    loop Every 60s
        Transport->>Redis: SCAN for output:* streams
        Redis->>Transport: List of output streams
        loop For each stream
            Transport->>Redis: XINFO STREAM output:{id}
            Redis->>Transport: last-entry timestamp
            alt Age > output_stream_ttl
                Transport->>Redis: DEL output:{id}
            end
        end
    end
```

## Failure modes

- **Redis Connection Lost**: Transport reconnects with exponential backoff. Pending requests timeout after 60s. Heartbeat stops; peer computers mark as offline after TTL expires.
- **Message Stream Full**: XADD with MAXLEN drops oldest messages. Logged; messages lost if not processed in time.
- **Response Timeout**: Origin computer waits 60s for response on output:{request_id}. Returns error to caller if timeout.
- **Target Computer Offline**: Message appended to messages:{target} but never consumed. No acknowledgment; caller timeout after 60s.
- **Corrupted Message Payload**: Parse error on XREAD. Logged and skipped; message remains in stream (not ACKed).
- **Duplicate Request ID**: Origin generates UUID collision (extremely rare). Response may route to wrong caller.
- **Output Stream Leak**: Response stream not cleaned up due to crash. Cleanup worker prunes after TTL (default 300s).
- **Digest Collision**: Two states hash to same value. Cache refresh skipped until next TTL. Rare; eventual consistency via TTL.
- **Heartbeat Storm**: Many computers send heartbeats simultaneously. Redis handles writes serially; no corruption but increased latency.
- **XREAD Blocking Timeout**: BLOCK expires with no messages. Normal operation; loop retries immediately.
