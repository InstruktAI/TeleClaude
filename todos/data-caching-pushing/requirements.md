# Data Caching & Push Architecture

## Problem Statement

The TUI is slow because REST endpoints query remote computers synchronously via Redis request-response. Each query has a 3s timeout and queries are sequential. With 2 remote computers, loading the Sessions view takes 18+ seconds.

## Goals

1. **Instant reads** - TUI reads from local cache, never waits for remote queries
2. **Event-driven updates** - Remote changes push to interested daemons
3. **Interest-based activation** - Cache only activates when TUI is connected
4. **Minimal traffic** - Only push data to daemons with interested clients

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              LOCAL DAEMON                               │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                         DaemonCache                              │   │
│  │                                                                  │   │
│  │   computers ──── from heartbeats ──────────────── TTL: 60s      │   │
│  │   projects ───── pull once on view access ─────── TTL: 5 min    │   │
│  │   sessions ───── pull once + event updates ────── TTL: infinite │   │
│  │   todos ──────── pull once on view access ─────── TTL: 5 min    │   │
│  │                                                                  │   │
│  │   on_change() ───────────────────────────────────────────────┐  │   │
│  └──────────────────────────────────────────────────────────────│──┘   │
│                                                                 │      │
│         ▲              ▲              ▲                         ▼      │
│    heartbeats     pull requests   event stream            WebSocket    │
│         │              │              │                    Server      │
│         └──────────────┴──────────────┴─────────┐              │       │
│                                                 │              │       │
│                        Redis Adapter ───────────┘              │       │
│                                                                │       │
└────────────────────────────────────────────────────────────────┼───────┘
                                                                 │
                                                                 ▼
                                                          ┌───────────┐
                                                          │    TUI    │
                                                          └───────────┘
```

### REST/MCP Separation

REST and MCP are **parallel adapters**, not nested:

```
┌─────────────────────────────────────────────────────────────┐
│                         DAEMON                              │
│                                                             │
│   ┌─────────────────────────────────────────────────────┐   │
│   │           SHARED INFRASTRUCTURE                     │   │
│   │   - AdapterClient (routes events)                   │   │
│   │   - Database (sessions, settings)                   │   │
│   │   - Command handlers (handle_list_projects, etc.)   │   │
│   └─────────────────────────────────────────────────────┘   │
│              ▲                           ▲                  │
│              │                           │                  │
│   ┌──────────┴──────────┐     ┌──────────┴──────────┐      │
│   │     REST Adapter    │     │     MCP Server      │      │
│   │   (for TUI only)    │     │  (for AI-to-AI)     │      │
│   └─────────────────────┘     └─────────────────────┘      │
│              ▲                           ▲                  │
└──────────────┼───────────────────────────┼──────────────────┘
               │                           │
          ┌────┴────┐                 ┌────┴────┐
          │   TUI   │                 │ Claude  │
          │ (telec) │                 │  Code   │
          └─────────┘                 └─────────┘
```

- REST API is for TUI only
- MCP Server is for AI-to-AI only
- Both call shared command handlers directly
- They never call each other

## Data Categories

| Data | Source | TTL | Population | Invalidation |
|------|--------|-----|------------|--------------|
| Computers | Heartbeats | 60s | Pushed by remotes | Auto-expire |
| Remote Projects | Pull once | 5 min | On view access | TTL or 'r' key |
| Remote Sessions | Pull once + events | ∞ | Initial pull, then events | Events |
| Session metadata | Events | ∞ | Events only | Events |
| Todos | Pull once | 5 min | On Preparation view | TTL or 'r' key |
| Local sessions | DB direct | 0 | Always fresh | N/A |
| Local projects | Filesystem | 0 | Always fresh | N/A |

## Interest-Based Activation

### Interest Flow

```
TUI                    Local Daemon                    Remote Daemon
 │                          │                                │
 │── WS connect ───────────>│                                │
 │                          │                                │
 │── subscribe:sessions ───>│                                │
 │                          │                                │
 │                          │── heartbeat ──────────────────>│
 │                          │   {interested_in: [sessions]}  │
 │                          │                                │
 │                          │   (remote sees interest,       │
 │                          │    starts pushing events)      │
 │                          │                                │
 │                          │<───── session_created ─────────│
 │                          │                                │
 │<── WS: session_created ──│                                │
```

### Interest Expiry

- When TUI disconnects, daemon removes interest from heartbeat
- Remote daemons see interest flag disappear, stop pushing events
- No explicit unsubscribe needed; implicit via heartbeat

## Event Types

### Existing Events to Reuse

| Event | Constant | Value | Use Case |
|-------|----------|-------|----------|
| `TeleClaudeEvents.NEW_SESSION` | `NEW_SESSION` | `"new_session"` | Session created |
| `TeleClaudeEvents.SESSION_TERMINATED` | `SESSION_TERMINATED` | `"session_terminated"` | Session ended |
| `TeleClaudeEvents.SESSION_UPDATED` | `SESSION_UPDATED` | `"session_updated"` | Session fields changed |
| `TeleClaudeEvents.AGENT_EVENT` | `AGENT_EVENT` | `"agent_event"` | Agent stop (with summary) |

### New Event Required

| Event | Constant | Value | Purpose |
|-------|----------|-------|---------|
| `TeleClaudeEvents.INPUT_RECEIVED` | `INPUT_RECEIVED` | `"input_received"` | User sent input to session |

### Event Payload Format

```python
{
    "event": "session_updated",  # TeleClaudeEvents value
    "computer": "RasPi",         # Source computer
    "data": {
        "session_id": "...",
        "title": "...",
        "status": "...",
        "last_input": "...",
        "last_output": "...",
        # ... full session object
    }
}
```

## Components

### 1. DaemonCache

Central cache with TTL management and change notifications.

**Location:** `teleclaude/core/cache.py`

**Responsibilities:**
- Store cached data with TTL tracking
- Provide instant reads for REST endpoints
- Emit change events when data updates
- Track what data is stale

### 2. WebSocket Server

Push interface for TUI clients.

**Location:** Extend `teleclaude/adapters/rest_adapter.py`

**Responsibilities:**
- Accept TUI connections on same Unix socket as REST
- Track client subscriptions (sessions view, preparation view)
- Push cache updates to subscribed clients

### 3. Event Emitter

Push session events to interested peers.

**Location:** Extend `teleclaude/adapters/redis_adapter.py`

**Responsibilities:**
- Hook into existing event handlers
- Check which peers have expressed interest (via heartbeat flags)
- Push events via Redis stream to interested peers

### 4. Event Receiver

Receive and process events from remotes.

**Location:** Extend `teleclaude/adapters/redis_adapter.py`

**Responsibilities:**
- Subscribe to `session_events:{self}` stream
- Parse incoming events
- Update DaemonCache
- Trigger WebSocket push to TUI

### 5. Interest Manager

Track and advertise client interest.

**Location:** `teleclaude/core/cache.py`

**Responsibilities:**
- Track which views TUI has subscribed to
- Include `interested_in` flags in heartbeat
- Activate/deactivate event subscriptions based on interest

## Redis Streams

### Existing (No Changes)

- `messages:{computer}` - Command stream for each computer
- `output:{session_id}` - Session output stream
- `computer:*:heartbeat` - Heartbeat keys with TTL

### New Stream

- `session_events:{computer}` - Session events pushed to interested subscribers

```
XADD session_events:MBP * \
  event "session_updated" \
  source "RasPi" \
  data '{"session_id": "...", ...}'
```

## Success Criteria

1. **Sessions view loads instantly** - No waiting for remote queries
2. **Session changes appear in <1s** - Event-driven, not polled
3. **No traffic when TUI closed** - Interest-based activation
4. **Preparation view loads in <500ms** - Cached projects + parallel todo fetch
5. **Manual refresh works** - 'r' key invalidates cache and re-fetches

## Design Decisions

1. **Redis streams over pub/sub** - Streams persist events, allowing replay of missed events on reconnect
2. **Full state push on subscribe** - Simpler than delta tracking; TUI always gets complete current state
3. **WebSocket in REST adapter** - Same Unix socket simplifies deployment; single connection point for TUI
4. **Interest via heartbeat** - Reuses existing heartbeat mechanism; no new Redis channels needed
