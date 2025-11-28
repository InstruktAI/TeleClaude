# Redis Adapter Flows (Unified Architecture)

> **Created**: 2025-11-28
> **Status**: 📊 Architecture Diagram
> **Goal**: Visual representation of simplified Redis adapter patterns

## Overview

After the unified adapter architecture refactoring, Redis adapter has **two simple modes**:

1. **Client Mode** (MozBook): Pure transport - sends requests, reads responses
2. **Server Mode** (RasPi4): Handles requests, serves session data from files

**Key Simplification**: No streaming, no dual sessions, no special cases.

---

## AI-to-AI Session Flow (Complete)

```mermaid
sequenceDiagram
    participant MCP as MCP Client<br/>(MozBook)
    participant RedisC as Redis Adapter<br/>(Client - MozBook)
    participant Redis as Redis Streams
    participant RedisS as Redis Adapter<br/>(Server - RasPi4)
    participant DB as Database<br/>(RasPi4)
    participant Claude as Claude Code<br/>(RasPi4)
    participant TG as Telegram Adapter<br/>(Observer - RasPi4)

    Note over MCP,TG: 1. START SESSION (No local session created!)

    MCP->>RedisC: teleclaude__start_session(computer="RasPi4", project_dir="/app")
    RedisC->>Redis: XADD messages:RasPi4 /create_session
    Redis-->>RedisS: Poll messages stream
    RedisS->>DB: create_session(origin_adapter="redis")
    DB-->>RedisS: session_id
    RedisS->>Redis: XADD response:{request_id} {session_id}
    Redis-->>RedisC: XREAD response stream
    RedisC-->>MCP: {session_id: "abc123", status: "success"}

    Note over MCP,TG: ✓ Only ONE session exists (on RasPi4)<br/>✓ No local DB session on MozBook<br/>✓ No local session file on MozBook

    Note over MCP,TG: 2. SEND COMMAND

    MCP->>RedisC: teleclaude__send_message(session_id, "run tests")
    RedisC->>Redis: XADD messages:RasPi4 /send {message}
    Redis-->>RedisS: Poll messages stream
    RedisS->>Claude: Execute command in session
    Claude->>Claude: Store output in claude_session_file

    Note over MCP,TG: 3. POLLING COORDINATOR (on RasPi4)

    loop Output Polling
        Claude->>Claude: Tmux output changes
        Claude->>RedisS: send_output_update() broadcast
        RedisS-->>RedisS: (No implementation - does nothing)
        Claude->>TG: send_output_update()
        TG->>TG: Edit message using adapter_metadata["telegram"]["output_message_id"]
    end

    Note over TG: ✓ Telegram edits ONE message<br/>✓ Uses adapter_metadata for message tracking<br/>✓ No special AI session code path

    Note over MCP,TG: 4. GET SESSION DATA (Pull pattern)

    MCP->>RedisC: teleclaude__get_session_data(computer="RasPi4", session_id)
    RedisC->>Redis: XADD messages:RasPi4 /session_data {session_id}
    Redis-->>RedisS: Poll messages stream
    RedisS->>RedisS: get_session_data(session_id)
    RedisS->>Claude: Read claude_session_file
    Claude-->>RedisS: Session content (markdown)
    RedisS->>Redis: XADD response:{request_id} {session_data}
    Redis-->>RedisC: XREAD response stream
    RedisC-->>MCP: {status: "success", messages: "..."}

    Note over MCP,TG: ✓ No streaming - just request/response<br/>✓ Session file is source of truth<br/>✓ Pull data on demand
```

---

## Simplified Architecture Comparison

### Before (Complex - Two Code Paths)

```mermaid
graph TB
    subgraph "MozBook (Client)"
        MCP1[MCP Client]
        LocalDB1[(Local DB<br/>Session)]
        LocalFile1[Local Session File]
        RedisC1[Redis Adapter<br/>Client Mode]
    end

    subgraph "Redis Infrastructure"
        Messages[messages:RasPi4<br/>Command Stream]
        Output[output:session_id<br/>**OUTPUT STREAM**]
    end

    subgraph "RasPi4 (Server)"
        RedisS1[Redis Adapter<br/>Server Mode]
        RemoteDB[(Remote DB<br/>Session)]
        Claude1[Claude Code]
        TG1[Telegram]
    end

    MCP1 -->|Creates LOCAL session| LocalDB1
    MCP1 -->|Creates LOCAL file| LocalFile1
    MCP1 --> RedisC1
    RedisC1 -->|Commands| Messages
    Messages --> RedisS1
    RedisS1 -->|Creates REMOTE session| RemoteDB
    RedisS1 --> Claude1
    Claude1 -->|**STREAMS chunks**| Output
    Output -->|Poll & stream| RedisC1
    RedisC1 -->|Stream to MCP| MCP1
    Claude1 -->|**Sends chunks**| TG1

    style Output fill:#f99,stroke:#f00
    style LocalDB1 fill:#f99,stroke:#f00
    style LocalFile1 fill:#f99,stroke:#f00
```

**Problems**:
- ❌ Dual sessions (local + remote)
- ❌ Output streaming via Redis streams
- ❌ Special AI session code paths
- ❌ Chunked output prevents message editing
- ❌ Complex state management

---

### After (Simple - One Code Path)

```mermaid
graph TB
    subgraph "MozBook (Client)"
        MCP2[MCP Client]
        RedisC2[Redis Adapter<br/>**Pure Transport**]
    end

    subgraph "Redis Infrastructure"
        Messages2[messages:RasPi4<br/>Command Stream]
        Response[response:request_id<br/>Response Stream]
    end

    subgraph "RasPi4 (Server)"
        RedisS2[Redis Adapter]
        RemoteDB2[(Remote DB<br/>**Only Session**)]
        SessionFile[claude_session_file<br/>**Source of Truth**]
        Coordinator[Polling Coordinator<br/>**ONE CODE PATH**]
        TG2[Telegram Adapter]
    end

    MCP2 -->|Request/Response| RedisC2
    RedisC2 -->|Commands| Messages2
    Messages2 --> RedisS2
    RedisS2 -->|Creates session| RemoteDB2
    RedisS2 -->|Reads on demand| SessionFile
    RedisS2 -->|Response| Response
    Response --> RedisC2
    RedisC2 -->|Data| MCP2

    Coordinator -->|send_output_update<br/>broadcast| RedisS2
    Coordinator -->|send_output_update<br/>broadcast| TG2
    RedisS2 -.->|Does nothing| SessionFile
    TG2 -->|Edits ONE message| TG2

    style SessionFile fill:#9f9,stroke:#0f0
    style Coordinator fill:#9f9,stroke:#0f0
    style RedisC2 fill:#9cf,stroke:#09f
```

**Benefits**:
- ✅ Single session (remote only)
- ✅ Request/response pattern (no streaming)
- ✅ Unified coordinator (no branching)
- ✅ Message editing works (send_output_update)
- ✅ Simple state management

---

## Request/Response Pattern Detail

```mermaid
sequenceDiagram
    participant Client as Redis Adapter<br/>(Client)
    participant Streams as Redis Streams
    participant Server as Redis Adapter<br/>(Server)
    participant File as claude_session_file

    Note over Client,File: Pattern: Send request → Read response

    Client->>Streams: XADD messages:computer /session_data {metadata}
    Note right of Client: Request ID:<br/>session-data-1234567890

    Streams->>Server: XREAD (poll messages stream)
    Server->>Server: Handle /session_data command
    Server->>File: Read session file
    File-->>Server: Session content
    Server->>Streams: XADD response:request_id {data}

    Streams->>Client: XREAD (poll response stream)
    Client-->>Client: Parse JSON response

    Note over Client,File: ✓ Simple request/response<br/>✓ No streaming complexity<br/>✓ File is source of truth
```

---

## Observer Pattern Detail (Unchanged Conceptually)

```mermaid
sequenceDiagram
    participant Coordinator as Polling Coordinator<br/>(RasPi4)
    participant AdapterClient as Adapter Client
    participant Redis as Redis Adapter
    participant Telegram as Telegram Adapter
    participant Metadata as adapter_metadata

    Note over Coordinator,Metadata: Output changed event

    Coordinator->>AdapterClient: send_output_update(session_id, output, ...)

    AdapterClient->>AdapterClient: Broadcast to ALL adapters

    par Broadcast to Redis
        AdapterClient->>Redis: send_output_update()
        Redis-->>Redis: ✗ Not implemented<br/>(does nothing)
    and Broadcast to Telegram
        AdapterClient->>Telegram: send_output_update()
        Telegram->>Metadata: Get adapter_metadata["telegram"]
        Metadata-->>Telegram: {output_message_id: "123"}
        Telegram->>Telegram: Edit message 123
        Telegram->>Metadata: Update adapter_metadata["telegram"]
    end

    Note over Coordinator,Metadata: ✓ Unified pattern for all adapters<br/>✓ Telegram edits ONE message<br/>✓ Redis does nothing (no streaming)
```

---

## Command Routing Architecture

```mermaid
graph LR
    subgraph "BaseAdapter (All adapters inherit)"
        Commands[COMMANDS List]
        Dispatcher[handle_command]
        SessionData[_handle_session_data]
        ListSessions[_handle_list_sessions]
    end

    subgraph "TelegramAdapter"
        TG_Commands[+ telegram commands]
        TG_Handlers[+ telegram handlers]
    end

    subgraph "RedisAdapter"
        Redis_Poll[Poll messages stream]
        Redis_Route[Route to handle_command]
    end

    Redis_Poll -->|/session_data| Redis_Route
    Redis_Route --> Dispatcher
    Dispatcher --> SessionData
    SessionData -->|Read| SessionFile[(claude_session_file)]

    TG_Commands -.->|Inherits| Commands
    TG_Handlers -.->|Inherits| SessionData

    style SessionData fill:#9f9,stroke:#0f0
    style SessionFile fill:#9cf,stroke:#09f
```

**Key Insight**: `/session_data` command is handled by BaseAdapter, so ALL adapters (Telegram, Redis, future Slack/WhatsApp) automatically support it.

---

## Removed Components

### ❌ Deleted from Architecture

1. **`teleclaude__observe_session` MCP Tool**
   - Not needed - observation happens automatically via adapter_metadata
   - Remote MCP client doesn't observe, it pulls data via `teleclaude__get_session_data`

2. **`_send_output_chunks_ai_mode()` Function**
   - Replaced by unified `send_output_update()` for all sessions

3. **`_is_ai_to_ai_session()` Function**
   - No more branching by session type

4. **Redis Output Streams**
   - Replaced by request/response pattern reading session files

5. **Local Session Creation (Client Mode)**
   - Client no longer creates local DB sessions or session files

6. **Output Stream Listeners**
   - `_output_stream_listeners` dict and all polling logic removed

---

## Summary

### Unified Adapter Pattern Achieved

**One principle**: All adapters work the same way
- **Telegram**: Edits messages using adapter_metadata
- **Redis**: Serves session data from files via request/response
- **Future adapters**: Follow same patterns

**One coordinator path**: No special cases for AI sessions
```python
# Before: if is_ai_session: ... else: ...
# After: (unified for all sessions)
await adapter_client.send_output_update(session_id, output, ...)
```

**One source of truth**: Session files
- Claude Code already stores everything
- All adapters read from same source
- No duplicate storage or streaming

**Result**: 30% code reduction, zero special cases, easier to maintain.
