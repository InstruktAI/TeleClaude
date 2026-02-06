---
description: 'Daemon orchestration responsibilities, boundaries, and background services.'
id: 'project/design/daemon'
scope: 'project'
type: 'design'
---

# Daemon — Design

## Required reads

- @docs/project/design/system-overview.md

## Purpose

- Coordinate adapters, command handling, tmux execution, and background tasks.
- Adapter interactions flow through `AdapterClient`.
- State is persisted in SQLite and surfaced via the cache.

```mermaid
stateDiagram-v2
    [*] --> Starting
    Starting --> WarmingCache: Config loaded
    WarmingCache --> StartingAdapters: Cache ready
    StartingAdapters --> Ready: All adapters online
    StartingAdapters --> DegradedMode: Some adapters failed
    Ready --> Running: Begin operations
    DegradedMode --> Running: Continue with available adapters
    Running --> Stopping: SIGTERM received
    Stopping --> Stopped: Cleanup complete
    Stopped --> [*]
```

## Inputs/Outputs

**Inputs:**

- Configuration file (`config.yml`, `teleclaude.yml`)
- Adapter events and inbound command objects
- SIGTERM/SIGINT for graceful shutdown
- Redis transport messages (if enabled)
- Adapter-specific inputs (Telegram bot API, MCP stdio, API HTTP requests)
- Filesystem artifacts (session transcripts, project registries)

**Outputs:**

- Adapter initialization and registration
- Command execution, tmux orchestration, and cache updates
- Command execution via CommandService
- Tmux session orchestration
- Cache population and updates
- Background task execution (hook processing, polling, digest updates)
- Graceful shutdown signals to all subsystems

## Invariants

- **Single Instance**: Only one daemon process runs per repository root (enforced by SQLite exclusive lock).
- **Adapter Independence**: Adapter failures are isolated; one adapter crash doesn't terminate daemon.
- **Cache Before Adapters**: Cache must be fully warmed before adapters start serving requests.
- **Graceful Degradation**: Daemon runs even if non-critical adapters fail (e.g., Telegram offline, Redis unavailable).
- **Outbox Recovery**: On restart, daemon processes undelivered hooks and pending commands from outbox tables.
- **Clean Shutdown**: SIGTERM triggers graceful adapter shutdown, command completion, and resource cleanup.

## Primary flows

### 1. Daemon Startup

```mermaid
sequenceDiagram
    participant SystemD
    participant Daemon
    participant Config
    participant DB
    participant Cache
    participant Adapters
    participant Workers

    SystemD->>Daemon: Start process
    Daemon->>Config: Load config.yml
    Daemon->>DB: Acquire exclusive lock
    Daemon->>DB: Run migrations
    Daemon->>Cache: Warmup snapshots
    Cache->>DB: Load sessions, projects, etc
    Daemon->>Adapters: Initialize (Telegram, API, MCP)
    Adapters->>Daemon: Register via AdapterClient
    Daemon->>Workers: Start background tasks
    Workers->>Workers: Hook outbox processing
    Workers->>Workers: Output polling
    Workers->>Workers: Redis heartbeat (if enabled)
    Daemon->>SystemD: Ready signal
```

### 2. Command Execution Cycle

```mermaid
sequenceDiagram
    participant Adapter
    participant CommandService
    participant Queue
    participant Worker
    participant Handler
    participant DB

    Adapter->>CommandService: Submit command
    CommandService->>Queue: Enqueue to SQLite
    Queue->>Worker: Dequeue next command
    Worker->>Handler: Dispatch to handler
    Handler->>DB: Execute and persist
    Handler->>Worker: Return result
    Worker->>CommandService: Command complete
    CommandService->>Adapter: Response
```

### 3. Background Workers

| Worker             | Interval | Purpose                             |
| ------------------ | -------- | ----------------------------------- |
| Hook Outbox        | 1s       | Process agent lifecycle hooks       |
| Output Poller      | 200ms    | Stream tmux output to adapters      |
| Redis Heartbeat    | 30s      | Publish computer status and digests |
| Digest Checker     | 60s      | Check remote project/todo changes   |
| Session Cleanup    | On start | Detect and recover orphaned tmux    |
| MCP Socket Watcher | 5s       | Monitor MCP server health           |

### 4. MCP Server Auto-Restart

```mermaid
sequenceDiagram
    participant Daemon
    participant MCPServer
    participant Watcher

    loop Every 5s
        Watcher->>MCPServer: Check socket health
        alt Socket dead
            Watcher->>MCPServer: Restart server
            MCPServer->>Daemon: New socket created
        end
    end
```

### 5. Graceful Shutdown

```mermaid
sequenceDiagram
    participant SystemD
    participant Daemon
    participant Adapters
    participant Workers
    participant Sessions
    participant DB

    SystemD->>Daemon: SIGTERM
    Daemon->>Adapters: Stop accepting requests
    Daemon->>Workers: Cancel background tasks
    Workers->>Workers: Complete in-flight work
    Daemon->>Sessions: Mark active sessions (no kill)
    Daemon->>DB: Flush pending writes
    Daemon->>Adapters: Shutdown hooks
    Daemon->>DB: Release lock
    Daemon->>SystemD: Exit 0
```

## Failure modes

- **Config Parse Error**: Daemon exits immediately with error. Systemd restarts with exponential backoff.
- **SQLite Lock Failure**: Another daemon instance is running. Refuses to start. Indicates configuration or deployment issue.
- **Migration Failure**: Database schema incompatible. Manual intervention required. No automatic rollback.
- **Critical Adapter Failure (API/MCP)**: Daemon continues without that interface. Clients see connection refused.
- **Redis Unavailable**: Multi-computer features disabled. Local operations continue. Redis transport retries via a single reconnect loop; tasks wait on readiness.
- **Cache Warmup Timeout**: Daemon fails to start. Indicates database corruption or resource exhaustion.
- **Unclean Shutdown (SIGKILL)**: Hooks and commands may be partially processed. Next startup recovers from outbox.
- **Worker Task Crash**: Background worker stops. Dependent features stall (e.g., no output polling = frozen sessions). Daemon logs error but continues.
- **MCP Restart Storm**: MCP crashes repeatedly. Rate-limited to prevent infinite loop. Clients see connection errors.
- **Shutdown Timeout**: Cleanup takes too long; systemd may SIGKILL and leak resources.
