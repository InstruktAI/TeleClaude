---
description: 'High-level architectural blueprint of TeleClaude components and data flow.'
id: 'project/design/architecture/system-overview'
scope: 'global'
type: 'design'
---

# System Overview — Design

## Purpose

TeleClaude acts as a "dumb pipe" terminal bridge between UI adapters (Telegram, TUI, MCP) and tmux execution environments.

```mermaid
flowchart LR
    subgraph Clients
        TelecCLI["Telec CLI (TUI)"]
        MCPClient["MCP Client"]
        TGUser["Telegram User"]
    end

    subgraph ServiceInterfaces["Service Interfaces"]
        RESTServer["API Server"]
        MCPServer["MCP Server"]
        TGAdapter["Telegram Adapter"]
    end

    subgraph Core["Core (Command Pipeline)"]
        Ingress["Command Ingress"]
        Queue["Command Queue (SQLite)"]
        Worker["Command Worker"]
        Sessions["Session Manager"]
        Poller["Output Poller"]
        Hooks["Hook Receiver + Agent Coordinator"]
        Events["Domain Events"]
        Cache["Read Cache (Snapshots)"]
        RedisIngress["Redis Transport Listener"]
        NextMachine["Next Machine (Orchestrator)"]
    end

    subgraph Infrastructure
        SQLite["SQLite DB"]
        Redis["Redis Transport"]
        TMUX["tmux"]
        FS["Filesystem / Artifacts"]
    end

    TelecCLI --> RESTServer
    MCPClient --> MCPServer
    TGUser --> TGAdapter

    RESTServer --> Ingress
    MCPServer --> Ingress
    TGAdapter --> Ingress
    RedisIngress --> Ingress

    Ingress --> Queue
    Queue --> Worker

    Worker --> Sessions
    Worker --> TMUX
    Worker --> Poller
    Worker --> FS

    Poller --> Events
    Hooks --> Events
    Sessions --> Events
    Events --> Cache

    Sessions --> SQLite
    Queue --> SQLite
    Hooks --> SQLite
    Cache --> SQLite

    RedisIngress --> Redis
    Redis --> RedisIngress
```

1. **Service Interfaces**:
   - **Telegram Adapter**: Normalizes chat interactions.
   - **MCP Server**: Stdio-based interface for AI agents.
   - **API Server**: Resource-first REST/WS interface for TUIs.
2. **Core Pipeline**:
   - **Command Ingress**: Normalizes all inputs into Command objects.
   - **Command Queue**: SQLite-backed durable execution.
   - **Session Manager**: Manages tmux lifecycles and process mapping.
3. **Execution Layer**:
   - **tmux**: The runtime for all terminal sessions.
   - **Output Poller**: Streams real-time updates from tmux to domain events.
4. **Orchestration**:
   - **Next Machine**: Stateless state machine for complex project-based workflows.
   - **Agent Coordinator**: Single source of truth for routing agent lifecycle hooks.

## Inputs/Outputs

**Inputs:**

- User commands from UI adapters (Telegram, TUI, MCP)
- Redis transport messages from remote computers
- Agent lifecycle hooks via hook receiver
- Tmux output streams
- File system artifacts (requirements, plans, transcripts)

**Outputs:**

- Tmux session creation and input delivery
- Adapter feedback (Telegram messages, API responses, MCP tool results)
- Domain events (session_started, session_closed, output_update)
- Cached snapshots (sessions, projects, todos, computers)
- Persistent database records (sessions, commands, hooks)

## Invariants

- **Single Database**: One SQLite database per repository root; no file duplication or sharding.
- **Command Idempotency**: Commands can be replayed safely; duplicate execution is prevented via queue tracking.
- **Event-Driven Updates**: All cache and adapter updates are triggered by domain events, never by polling state.
- **Session Ownership**: Each session has exactly one owning adapter that created it; other adapters can observe but not modify.
- **Decoupled Adapters**: Core logic never imports adapter-specific code; all communication via Protocols.
- **Durable Execution**: Commands and hook events persist to SQLite queue/outbox tables before processing; restarts recover pending work.

## Primary flows

### 1. New Session Creation

```mermaid
sequenceDiagram
    participant User
    participant Adapter
    participant CommandService
    participant SessionLauncher
    participant Tmux
    participant DB
    participant EventBus

    User->>Adapter: /new-session
    Adapter->>CommandService: CreateSessionCommand
    CommandService->>DB: Persist command
    CommandService->>SessionLauncher: Launch session
    SessionLauncher->>Tmux: Start tmux session
    SessionLauncher->>DB: Save session metadata
    SessionLauncher->>EventBus: Emit SESSION_STARTED
    EventBus->>Adapter: Notify via AdapterClient
    Adapter->>User: Session created (topic/pane)
```

### 2. Message to Session

```mermaid
sequenceDiagram
    participant User
    participant Adapter
    participant CommandService
    participant TmuxBridge
    participant OutputPoller
    participant EventBus

    User->>Adapter: Send message
    Adapter->>CommandService: SendMessageCommand
    CommandService->>TmuxBridge: Write to tmux pane
    TmuxBridge->>OutputPoller: Trigger immediate poll
    loop Until complete
        OutputPoller->>EventBus: OUTPUT_UPDATE events
        EventBus->>Adapter: Stream to user
    end
```

### 3. AI-to-AI Delegation (MCP)

```mermaid
sequenceDiagram
    participant MasterAI
    participant MCPServer
    participant Redis
    participant RemoteComputer
    participant WorkerAI

    MasterAI->>MCPServer: teleclaude__start_session
    MCPServer->>Redis: Publish command
    Redis->>RemoteComputer: Transport event
    RemoteComputer->>WorkerAI: Launch agent
    WorkerAI->>RemoteComputer: Emits hooks
    RemoteComputer->>Redis: Publish notification
    Redis->>MCPServer: Deliver notification
    MCPServer->>MasterAI: Worker completed
```

### 4. Cache Refresh & WS Push

```mermaid
sequenceDiagram
    participant EventBus
    participant DaemonCache
    participant APIServer
    participant WSClient

    EventBus->>DaemonCache: SESSION_UPDATED
    DaemonCache->>DaemonCache: Update snapshot
    DaemonCache->>APIServer: Cache updated
    APIServer->>WSClient: Push update
```

## Failure modes

- **Interface Startup Failure**: Required interface startup failures (adapter/API/MCP) fail daemon startup rather than silently running in partial mode.
- **Tmux Process Death**: If tmux dies unexpectedly, OutputPoller detects exit and marks session as failed. Cleanup may be incomplete.
- **Redis Unavailable**: Remote execution fails gracefully. Local operations continue. Heartbeat detection resumes when Redis recovers.
- **SQLite Lock Contention**: Rare under normal load. Commands queue and retry. Long locks indicate resource exhaustion.
- **Hook Delivery Failure**: Hooks persist to outbox. Daemon restart processes undelivered hooks. Late delivery can cause stale notifications.
- **Cache Staleness**: Clients receive stale data until TTL expires or digest changes. Background refresh updates cache asynchronously.
- **Outbox Accumulation**: If command execution stalls, outbox grows indefinitely. Manual intervention required to clear stuck commands.
