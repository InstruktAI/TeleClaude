---
description: 'Daemon orchestration responsibilities, boundaries, and background services.'
id: 'project/design/architecture/daemon'
scope: 'project'
type: 'design'
---

# Daemon — Design

## Required reads

- @docs/project/design/architecture/system-overview.md

## Purpose

- Coordinate adapters, command handling, tmux execution, and background tasks.
- Adapter interactions flow through `AdapterClient`.
- State is persisted in SQLite and surfaced via the cache.

```mermaid
stateDiagram-v2
    [*] --> Starting
    Starting --> WarmingCache: Config loaded
    WarmingCache --> StartingInterfaces: Cache ready
    StartingInterfaces --> Running: Interfaces online
    StartingInterfaces --> StartupFailed: Required interface failed
    Running --> Stopping: SIGTERM received
    Stopping --> Stopped: Cleanup complete
    StartupFailed --> [*]
    Stopped --> [*]
```

## Inputs/Outputs

**Inputs:**

- Configuration file (`config.yml`, `teleclaude.yml`)
- Adapter events and inbound command objects
- SIGTERM/SIGINT for graceful shutdown
- Redis transport messages (if enabled)
- Adapter-specific inputs (Telegram bot API, API HTTP requests)
- Filesystem artifacts (session transcripts, project registries)

**Outputs:**

- Adapter initialization and registration
- Command execution via CommandService
- Tmux session orchestration
- Cache population and updates
- Background task execution (hook processing, poller-watch, monitoring, WAL maintenance)
- Graceful shutdown signals to all subsystems

## Invariants

- **Single Instance**: Only one daemon process runs per repository root (enforced by SQLite exclusive lock).
- **Cache Before Adapters**: Cache must be fully warmed before adapters start serving requests.
- **Fail-Fast Startup**: Required interface startup failures abort daemon startup instead of degrading silently.
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
    Daemon->>Adapters: Initialize (Telegram, API)
    Adapters->>Daemon: Register via AdapterClient
    Daemon->>Workers: Start background tasks
    Workers->>Workers: Hook outbox processing
    Workers->>Workers: Poller watch
    Workers->>Workers: Resource monitor + WAL checkpoint
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

| Worker                | Interval (default) | Purpose                                                            |
| --------------------- | ------------------ | ------------------------------------------------------------------ |
| Hook Outbox           | 1s                 | Process agent lifecycle hooks                                      |
| Poller Watch          | 5s                 | Keep per-session output pollers aligned with tmux                  |
| Resource Monitor      | 60s                | Emit runtime resource snapshots                                    |
| WAL Checkpoint        | 300s               | Prevent unbounded SQLite WAL growth                                |
| Launchd Watch         | 300s (optional)    | Log launchd state transitions on macOS                             |
| Session Cleanup       | 1h                 | Periodic stale-session cleanup via maintenance loop                |
| Closed Session Replay | 1h                 | Re-emit `session_closed` for recently closed sessions (12h window) |

An operator can force the same behavior on demand with:

```bash
uv run scripts/cleanup_closed_session_channels.py [--hours 12] [--dry-run]
```

The helper queries local closed sessions within the window and replays their
`session_closed` handling through the running daemon API.

### 4. Graceful Shutdown

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
- **Interface Startup Failure (API/Adapter)**: Daemon fails startup (fail-fast) rather than running in partial mode.
- **Redis Unavailable**: Multi-computer features disabled. Local operations continue. Redis transport retries via a single reconnect loop; tasks wait on readiness.
- **Cache Warmup Timeout**: Daemon fails to start. Indicates database corruption or resource exhaustion.
- **Unclean Shutdown (SIGKILL)**: Hooks and commands may be partially processed. Next startup recovers from outbox.
- **Worker Task Crash**: Background worker stops. Dependent features stall (for example, no output polling means frozen sessions). Daemon logs error but continues.
- **Shutdown Timeout**: Cleanup takes too long; systemd may SIGKILL and leak resources.
