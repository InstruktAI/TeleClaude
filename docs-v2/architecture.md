# Architecture

## System Blueprint

```mermaid
flowchart LR
    subgraph Clients
        TelecCLI["Telec CLI (TUI)"]
        MCPClient["MCP Client"]
        TGUser["Telegram User"]
    end

    subgraph ServiceInterfaces["Service Interfaces"]
        RESTServer["REST Server"]
        MCPServer["MCP Server"]
        TGAdapter["Telegram Adapter"]
    end

    subgraph Core["Core (Command Pipeline)"]
        Ingress["Command Ingress"]
        Queue["Command Queue (SQLite)"]
        Worker["Command Worker"]
        Sessions["Session Manager"]
        Poller["Output Poller"]
        Hooks["Hook Receiver"]
        Events["Domain Events"]
        Cache["Read Cache (Snapshots)"]
        RedisIngress["Redis Transport Listener"]
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

## Boundaries

### Clients
- Issue requests and receive responses

### Service Interfaces
- REST is a public facade (REST‑native endpoints mapped to internal commands)
- MCP is a service boundary for AI orchestration
- Telegram is a UI adapter boundary
- All inputs normalize into command ingress

### Core
- Executes commands from queue
- Manages tmux lifecycle
- Emits domain events
- Event-driven cache updates (snapshots)

### Infrastructure
- Storage, transport, runtime

## Non-Goals

- No adapter-specific semantics inside core
- No transport metadata used as domain intent
