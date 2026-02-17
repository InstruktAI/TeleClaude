# Uvicorn Elimination Research: Solving the Socket Degradation Problem

**Date:** 2026-02-17
**Status:** Research complete (revision 3 — expanded scope)
**Core problem:** The uvicorn API server degrades over time with socket problems. 3 months of debugging hasn't found the root cause.
**Strategic goal:** Next.js must own the public HTTP surface (for future public API). Daemon should have no HTTP server.

---

## 1. The Problem: What We Know

### 1.1 Symptoms

The daemon's uvicorn server (FastAPI on Unix socket + TCP :8420) degrades over time. The codebase has extensive infrastructure built to cope with this:

- **API watch loop** (`api_server.py:1487`): Monitors event loop lag and in-flight request duration, dumps stack traces on detection
- **Auto-restart policy** (`lifecycle.py:251`): Max 5 restarts per 60s window with 1s backoff between attempts
- **Server exit handler** (`lifecycle.py:209`): Detects when uvicorn exits unexpectedly and schedules restart
- **FD monitoring** (`monitoring_service.py:30`): Tracks open file descriptors, warns at >200
- **Resource snapshots** (`monitoring_service.py:138`): Periodic logging of fds, RSS, asyncio tasks, threads, WAL size, WS client count, loop lag
- **Metrics loop** (`api_server.py:1714`): Logs fd_count, ws_count, task_count, server state every 60s

This is a lot of monitoring for a healthy server. The infrastructure itself tells the story: the server is unreliable.

### 1.2 Who actually consumes the HTTP API?

| Consumer                     | How it talks to daemon                                                | Uses HTTP API?          |
| ---------------------------- | --------------------------------------------------------------------- | ----------------------- |
| **TUI (telec CLI)**          | MCP socket (`/tmp/teleclaude.sock`)                                   | **No**                  |
| **AI agents (Claude, etc.)** | MCP socket (`/tmp/teleclaude.sock`)                                   | **No**                  |
| **MCP server**               | In-process Python calls (`command_handlers`, `get_command_service()`) | **No**                  |
| **Web frontend (Next.js)**   | Proxies via Unix socket (`/tmp/teleclaude-api.sock`) + TCP for WS     | **Yes — only consumer** |
| **Checkpoint hooks**         | Pattern-match evidence strings only                                   | **No**                  |

**The web frontend is the ONLY consumer of the HTTP API.** Eliminating uvicorn does NOT break TUI, MCP, or AI agent tooling.

### 1.3 Endpoint surface

**26 endpoints + 1 WebSocket.** Full audit preserved from v1:

- **Core API** (`api_server.py`): 18 endpoints + WS — sessions CRUD, computers, projects, todos, agents, people, settings
- **Memory router** (`memory/api_routes.py`): 6 endpoints — save, search, timeline, batch, delete, inject
- **Hooks router** (`hooks/api_routes.py`): 4 endpoints — contracts CRUD, properties
- **Channels router** (`channels/api_routes.py`): 2 endpoints — publish, list
- **Streaming router** (`api/streaming.py`): 1 endpoint — SSE chat stream

---

## 2. Option A: Replace uvicorn with another ASGI server

### What changes

Swap `uvicorn` for `hypercorn`, `granian`, or `daphne`. Keep FastAPI, keep all API code, just change the server process.

| Server        | Language                   | Protocol support            | Maturity                        |
| ------------- | -------------------------- | --------------------------- | ------------------------------- |
| **Hypercorn** | Python (asyncio/trio)      | HTTP/1.1, HTTP/2, WebSocket | Mature, ASGI reference-ish      |
| **Granian**   | Rust core, Python bindings | HTTP/1.1, HTTP/2, WebSocket | Newer, fast, less battle-tested |
| **Daphne**    | Python (Twisted)           | HTTP/1.1, WebSocket         | Django Channels default, mature |

### Changes required

- Replace `uvicorn.Config` / `uvicorn.Server` in `api_server.py:1525-1598` (~80 lines)
- Update `pyproject.toml` dependency
- Adjust server lifecycle methods (`start`, `stop`, `restart_server`)
- Hypercorn: `config = Config(); config.bind = ["unix:/tmp/teleclaude-api.sock"]; await serve(app, config)`
- Granian: Different API, uses `Granian("app", binding="unix:/tmp/teleclaude-api.sock")`

### Honest assessment

**If the bug is in uvicorn**: This fixes it. Possible uvicorn-specific issues: fd leaks in its connection pool, WebSocket ping/timeout handling, Unix socket listener edge cases, h11 HTTP parser bugs. Uvicorn has had real bugs with Unix sockets and WebSocket connection tracking.

**If the bug is in our code**: This changes nothing. The same FastAPI middleware, the same request tracking, the same WebSocket subscription management, the same asyncio task spawning — all stay. If `_broadcast_payload` leaks tasks, or `_handle_websocket` doesn't clean up, or the DaemonCache callback floods events, a different ASGI server won't help.

**If the bug is in the ASGI/HTTP protocol stack itself**: Swapping servers just trades one set of edge cases for another. The fundamental complexity of HTTP-over-Unix-socket plus WebSocket-over-TCP stays.

### Effort

- **2-3 days**: Swap server, test, validate
- **Risk**: 50/50 chance it doesn't fix the problem (if bug is in our code or the HTTP stack)

### Verdict

**Low-risk, low-confidence.** Worth trying first as a diagnostic step, but likely a bandaid. The amount of monitoring infrastructure suggests the team has already tried obvious fixes and the problem persists. If it were a simple uvicorn config issue, it would have been found in 3 months.

---

## 3. Option B: Drop HTTP from daemon, use Unix socket RPC

### What changes

Remove uvicorn/FastAPI entirely. Replace with a raw `asyncio.start_unix_server` speaking newline-delimited JSON-RPC. The daemon already has this exact pattern working in production for the MCP server (`mcp_server.py:651`).

### Architecture

```
┌─────────────────────────────────┐    ┌──────────────────────────────┐
│         Python Daemon           │    │       Next.js Server         │
│                                 │    │                              │
│  ┌──────────┐  ┌──────────┐   │    │  ┌────────────────────────┐ │
│  │ MCP Srv  │  │ IPC Srv  │◄──┼────┼──│ IPC Client             │ │
│  │ (socket) │  │ (socket) │   │    │  │ (JSON-RPC over UDS)    │ │
│  └──────────┘  └──────────┘   │    │  └────────────────────────┘ │
│       │              │         │    │  ┌────────────────────────┐ │
│       ▼              ▼         │    │  │ HTTP routes + WS + SSE │ │
│  ┌──────────────────────────┐ │    │  │ (public-facing)        │ │
│  │ CommandService/tmux      │ │    │  └────────────────────────┘ │
│  │ DaemonCache/EventBus    │ │    │  ┌────────────────────────┐ │
│  │ SQLite/Redis/Adapters   │ │    │  │ SQLite (read-only)     │ │
│  └──────────────────────────┘ │    │  └────────────────────────┘ │
└─────────────────────────────────┘    └──────────────────────────────┘
```

### Protocol

Newline-delimited JSON-RPC over Unix domain socket. Same pattern as MCP/LSP.

```json
// Request:  {"jsonrpc":"2.0","id":1,"method":"sessions.list","params":{"computer":"local"}}
// Response: {"jsonrpc":"2.0","id":1,"result":[...]}
// Push:     {"jsonrpc":"2.0","method":"event.session_updated","params":{"session":{...}}}
```

### What breaks

**Nothing in TUI/MCP/AI agents.** Only the Next.js proxy layer needs rewriting.

Changes needed:

1. **New Python IPC server** (~300 lines): `asyncio.start_unix_server` + JSON-RPC dispatcher mapping to existing handler functions
2. **New Next.js IPC client** (~300 lines): `node:net` connection to Unix socket, request/response correlation, reconnection
3. **Next.js WebSocket server**: Native WS in Next.js, fed by IPC push events from daemon
4. **Read-only SQLite in Next.js** (`better-sqlite3`): For pure data queries that don't need daemon state
5. **Remove** `api_server.py` (~1800 lines), sub-routers (~600 lines), uvicorn+FastAPI deps

### WebSocket subscription protocol

Currently the daemon manages WS subscriptions internally (`_client_subscriptions`, `_update_cache_interest`). Two approaches:

**Approach 1: Daemon manages subscriptions over IPC.** Next.js sends `subscribe`/`unsubscribe` JSON-RPC calls. Daemon maintains the same subscription state, pushes events on IPC. Next.js is just a relay to browser WS clients. ~Same complexity as current WS handler, different transport.

**Approach 2: Next.js manages subscriptions.** Daemon pushes ALL events on IPC. Next.js filters based on browser subscriptions. Simpler daemon, more Next.js logic, more traffic on IPC. Better separation of concerns.

Approach 2 is recommended — it moves UI-specific logic to the UI layer where it belongs.

### Why this solves the degradation

**The TCP listener disappears.** No more `:8420`. No more HTTP connection pooling, keep-alive management, ASGI middleware chain, h11 parser, WebSocket upgrade handshakes. The Unix socket uses a trivial protocol with no state machine.

The MCP server has been running on this exact pattern (`asyncio.start_unix_server`) without the socket degradation issues. If the degradation is anywhere in the HTTP/ASGI/uvicorn stack, this eliminates it by architecture.

### Honest risks

- **IPC protocol bugs**: Custom JSON-RPC implementation. Mitigated by: it's a well-defined standard, newline framing is trivial, MCP already does this.
- **Connection lifecycle**: Persistent socket drops on daemon restart. Mitigated by: exponential backoff reconnection (same pattern needed for any non-HTTP IPC).
- **SSE streaming**: The chat stream both reads files AND writes to tmux. Can be split: Next.js reads JSONL directly, writes via IPC `sessions.message`. Actually cleaner separation.
- **New failure mode**: IPC connection failure. But this replaces HTTP connection failure, which already fails. Net neutral on failure modes, simpler protocol.

### Effort

- **Phase 1** (IPC server, coexists with uvicorn): **1 week**
- **Phase 2** (Next.js IPC client + WS): **1 week**
- **Phase 3** (Native reads + streaming): **1 week**
- **Phase 4** (Remove uvicorn): **2-3 days**
- **Total: 3-4 weeks**, with each phase independently testable and non-breaking

### Verdict

**Best option for reliability + strategic alignment.** Eliminates the entire HTTP/ASGI stack from the daemon. Aligns with the public API requirement (Next.js owns HTTP). Proven pattern (MCP server). Non-breaking migration path (coexist, then switch, then remove).

---

## 4. Option C: Move API to Next.js with IPC to daemon

### What this is

All 26 endpoints become Next.js API routes. Endpoints needing daemon state call the daemon via IPC. Endpoints that are pure reads query SQLite directly.

### How it differs from Option B

Option B: Daemon has IPC server, Next.js calls it.
Option C: Same thing, but Next.js also reimplements some handler logic natively.

**These are essentially the same option** at different levels of ambition. Option B is "replace transport, keep daemon handlers." Option C is "replace transport AND move some handlers to Next.js."

The practical difference: in Option C, endpoints like `sessions.list` (which need DaemonCache merge) still call the daemon via IPC. The "moved to Next.js" endpoints are the same ones that are pure SQLite reads in Option B (agent availability, memory search, session messages).

### Honest assessment of IPC complexity

The hard parts:

- **DaemonCache merge**: `sessions.list`, `computers.list`, `projects.list`, `todos.list` all need the daemon's in-memory cache that merges local + remote data. These MUST go through IPC. There's no shortcut — the merge logic uses data only available in the daemon process.
- **EventBus events**: Session lifecycle, agent activity, errors — all originate in the daemon's in-process EventBus. Must be forwarded over IPC.
- **ContractRegistry**: Hooks CRUD operates on an in-memory registry initialized at daemon startup. Must go through IPC.
- **RuntimeSettings**: In-memory state, must go through IPC.
- **CommandService**: All session mutations route through this. Must go through IPC.

**You cannot avoid the IPC bridge for ~24 of the 26 endpoints.** The "move to Next.js" framing is misleading — most endpoints still call the daemon. The real migration is the transport layer.

### Effort

Same as Option B — they're the same architecture. 3-4 weeks.

### Verdict

**This IS Option B** with a different name. The endpoint audit shows that the vast majority of endpoints need daemon state. "Moving the API to Next.js" mostly means "Next.js is the HTTP frontend that calls the daemon via IPC" — which is exactly what Option B proposes.

---

## 5. Option D: Full rewrite of daemon in Node.js

### What would need to be ported

| Component          | Python implementation                   | Node.js equivalent                      | Difficulty |
| ------------------ | --------------------------------------- | --------------------------------------- | ---------- |
| tmux management    | `subprocess.run(["tmux", ...])`         | `child_process.execFile("tmux", [...])` | Easy       |
| SQLite             | aiosqlite + SQLModel                    | better-sqlite3 or drizzle-orm           | Medium     |
| Redis              | redis-py async                          | ioredis                                 | Easy       |
| EventBus           | Custom async pub/sub (55 lines)         | EventEmitter (built-in)                 | Easy       |
| DaemonCache        | Custom in-memory cache (~250 lines)     | Plain objects + Map                     | Easy       |
| CommandService     | Command routing + handlers (~400 lines) | Functions + routing                     | Medium     |
| MCP server         | mcp-python SDK over Unix socket         | @modelcontextprotocol/sdk               | Medium     |
| Adapter system     | Telegram, Discord, UI, Redis adapters   | Would need full rewrite                 | Hard       |
| Memory system      | SQLite FTS, observation store           | Port to Node SQLite                     | Medium     |
| Hooks/webhooks     | ContractRegistry, dispatching           | Full rewrite                            | Medium     |
| Transcript parsing | JSONL parsers for Claude/Gemini/Codex   | Full rewrite                            | Medium     |
| Session lifecycle  | Complex state machine with tmux         | Full rewrite                            | Hard       |
| File watchers      | asyncio-based directory monitoring      | fs.watch/chokidar                       | Easy       |
| Voice handling     | File processing + transcription         | Full rewrite                            | Medium     |
| Config system      | YAML + Pydantic models                  | yaml + zod/type validation              | Medium     |
| Deployment         | Git operations, rsync                   | Similar subprocess calls                | Easy       |

### Honest assessment

**Total Python in `teleclaude/`:**

```
$ find teleclaude -name "*.py" | xargs wc -l | tail -1
  ~25,000 lines
```

This is a full-featured daemon with adapters (Telegram, Discord), transport (Redis), orchestration (tmux lifecycle, agent management, cross-computer communication), monitoring, memory, hooks, and more. A full rewrite is 3-6 months of work minimum, with regression risk on every feature.

**What you gain:**

- Single runtime (Node.js everywhere)
- No IPC — daemon logic runs in the Next.js process
- Simpler deployment

**What you lose:**

- 3-6 months of velocity
- Battle-tested daemon behavior
- Python ecosystem (MCP SDK, some libraries)
- Risk of introducing new bugs in every ported component
- The MCP server would need to be rewritten using the TypeScript MCP SDK

### Does it solve the socket problem?

**Maybe.** If the degradation is caused by Python-specific behavior (asyncio edge cases, uvicorn bugs, Python GIL contention), then yes. If it's caused by architectural patterns that would be replicated in Node.js (fd leaks from WebSocket management, connection tracking issues), then no.

### Effort

- **3-6 months** full-time, with high regression risk
- Would need parallel running of old and new daemon during migration

### Verdict

**Nuclear option. Not justified.** The socket degradation can be solved by removing the HTTP layer (Option B) in 3-4 weeks. A full rewrite only makes sense if the daemon has fundamental architectural problems beyond the HTTP server — and the evidence points specifically at the HTTP/WebSocket stack, not the core orchestration.

---

## 6. Option E: Diagnose the actual root cause

### What's been tried (evidence from codebase)

The monitoring infrastructure reveals what's been attempted:

- **FD tracking** (`_get_fd_count`, `_FD_WARN=200`): Watching for fd leaks
- **Loop lag detection** (`_watch_loop`, `API_WATCH_LAG_THRESHOLD_MS=250`): Detecting event loop stalls
- **In-flight request tracking** (`_inflight_requests`, `API_WATCH_INFLIGHT_THRESHOLD_S=1`): Detecting stuck requests
- **Stack dump on detection** (`_dump_stacks`): Full thread dump via `faulthandler`
- **WS send timeout** (`asyncio.wait_for(..., timeout=2.0)`): Detecting stuck WebSocket sends
- **WS ping/timeout** (`API_WS_PING_INTERVAL_S=20, API_WS_PING_TIMEOUT_S=20`): Server-side WS health checks
- **Auto-restart** with backoff and rate limiting: Recovery mechanism
- **Resource snapshots** every N seconds: RSS, fds, threads, asyncio tasks, WAL size, loop lag

### What hasn't been tried (possible next steps)

1. **strace/dtrace on the daemon process**: Trace all socket syscalls. See exactly which syscall blocks or returns an error.

   ```bash
   # macOS:
   sudo dtruss -p <daemon_pid> -t socket,connect,accept,bind,listen,read,write,close 2>&1 | tee /tmp/dtrace.log
   ```

2. **lsof snapshot on degradation**: Capture all open file descriptors when degradation is detected.

   ```bash
   lsof -p <daemon_pid> > /tmp/lsof-$(date +%s).txt
   ```

3. **Correlate degradation with specific events**: Does it happen after:
   - WS client disconnect without clean close?
   - Many rapid WS reconnects (browser refresh)?
   - Daemon restart (socket file cleanup race)?
   - Redis transport disconnect/reconnect?
   - High asyncio task count?

4. **Isolated reproduction**: Run uvicorn with a minimal FastAPI app on Unix socket + TCP with WebSocket. Simulate the subscription pattern. See if degradation reproduces WITHOUT the daemon logic.

5. **Async task leak audit**: The code uses `asyncio.create_task()` and `self.task_registry.spawn()` extensively in broadcast paths. If tasks aren't cleaned up, they could accumulate. Specifically:
   - `_broadcast_payload` creates a task per WS client per event
   - `_schedule_refresh_broadcast` creates debounce tasks
   - Event handlers fire-and-forget via `loop.create_task(handler(event, context))` in `EventBus.emit`

6. **WebSocket connection leak**: The `_ws_clients` set could grow if `finally` blocks in `_handle_websocket` fail to execute (e.g., task cancellation during shutdown).

### Honest assessment

**3 months of failed debugging is a strong signal.** Either:

- The root cause is genuinely hard to find (intermittent, timing-dependent, requires specific client behavior)
- The root cause is in uvicorn/ASGI internals where application-level debugging can't reach
- The monitoring is looking at the wrong things (monitoring fd_count but the issue is socket state)

More debugging COULD succeed, but the opportunity cost is high. Every week spent debugging is a week not spent on the strategic goal (Next.js owning the public API).

### Effort

- **1-2 weeks** for a focused debugging sprint with strace/dtrace
- **Uncertain outcome**: May or may not find the root cause
- **Does not advance the strategic goal** (public API via Next.js)

### Verdict

**Worth 3-5 days as a parallel diagnostic** while Option B is being built. If the root cause is found, great — it informs whether Option A (ASGI swap) would have worked. But don't block the migration on it.

---

## 7. IPC Mechanism Comparison

Since Options B and C converge on "Next.js calls daemon via IPC," the key question is: **what IPC mechanism is most reliable?**

### Requirements

1. **Reliability over months of uptime** — #1 criterion
2. **Bidirectional** — daemon must push events to Next.js (for WS forwarding)
3. **Low latency** — <5ms for request/response
4. **No TCP** — TCP socket degradation is the problem we're solving
5. **Streaming support** — for chat SSE

### Comparison

| Mechanism                         | Reliability                                          | Bidirectional               | Latency | Complexity                      | TCP-free    |
| --------------------------------- | ---------------------------------------------------- | --------------------------- | ------- | ------------------------------- | ----------- |
| **Unix domain socket (JSON-RPC)** | High — kernel-managed, no network stack              | Yes — persistent connection | ~0.1ms  | Low — 300 lines each side       | Yes         |
| **Redis pub/sub**                 | Medium — adds Redis as hard dep, Redis can restart   | Yes — pub/sub is native     | ~1ms    | Low — existing Redis client     | Yes (local) |
| **Named pipes (FIFO)**            | Medium — unidirectional, need two pipes              | Awkward — need 2 pipes      | ~0.1ms  | Medium                          | Yes         |
| **child_process stdin/stdout**    | Low — daemon is long-running, not spawned by Next.js | Yes — but fragile           | ~0.1ms  | High — process management       | Yes         |
| **gRPC over Unix socket**         | High — well-tested, built for this                   | Yes — streaming support     | ~0.5ms  | High — protobuf schema, codegen | Yes         |
| **HTTP over Unix socket**         | Medium — this is what we're replacing                | Yes (with SSE/WS)           | ~2-5ms  | Low — already exists            | Yes         |

### Detailed analysis of top contenders

#### Unix Domain Socket with JSON-RPC (Recommended)

**Reliability:** Unix domain sockets are kernel-managed IPC. No network stack, no TCP state machine, no connection pooling. The kernel handles backpressure, flow control, and cleanup. When one side crashes, the other gets an immediate error (EPIPE/ECONNRESET). No "half-open" connections that degrade silently.

The MCP server has been running on this exact pattern without the socket degradation issues. This is strong evidence.

**Implementation:**

- Python: `asyncio.start_unix_server` + `StreamReader`/`StreamWriter` — identical to MCP server
- Node.js: `net.createConnection({path: "..."})` + line buffering
- Framing: newline-delimited JSON (trivial to implement, no ambiguity)
- Reconnection: `net.connect` with exponential backoff

**Bidirectional:** Single persistent connection carries requests, responses, AND push events. The JSON-RPC `id` field distinguishes requests (has id) from push events (no id).

**Streaming:** Chunked responses with `partial: true` flag, or a dedicated stream connection.

#### Redis Pub/Sub (Viable alternative for events only)

**Reliability:** Redis pub/sub is reliable when Redis is up, but adds a dependency. If Redis restarts, subscriptions are lost. Redis is currently optional for single-computer setups — making it required is a significant change.

**Where Redis fits:** If the daemon already publishes events to Redis for cross-computer use, Next.js could subscribe directly for push events. But request/response still needs a socket.

**Verdict:** Good for events IF Redis is already required. Not suitable as the sole IPC mechanism (no request/response pattern).

#### gRPC over Unix Socket (Over-engineered)

**Reliability:** Excellent. gRPC is designed for exactly this kind of service-to-service communication. Streaming, deadlines, health checks built in.

**Why not:** The overhead isn't justified. Protobuf schema management, code generation pipeline, gRPC dependency in both Python and Node.js. The API surface is 26 methods — JSON-RPC handles this trivially. gRPC's strengths (binary protocol, schema evolution, polyglot) aren't needed for a local IPC between two processes.

### Recommendation

**Unix domain socket with JSON-RPC.** Simple, proven (MCP already uses it), reliable (kernel-managed), bidirectional on a single connection. No new dependencies.

---

## 8. Endpoint Migration Categories

### Category 1: Move to Next.js directly (pure data reads)

| Endpoint                      | Access method               | Notes                  |
| ----------------------------- | --------------------------- | ---------------------- |
| `GET /health`                 | Next.js native              | Trivial                |
| `GET /api/people`             | YAML config                 | Already native         |
| `GET /agents/availability`    | SQLite read-only            | Simple query           |
| `GET /api/memory/search`      | SQLite FTS read-only        | Pure query             |
| `GET /api/memory/timeline`    | SQLite read-only            | Pure query             |
| `GET /api/memory/inject`      | SQLite read-only + text gen | Pure query             |
| `POST /api/memory/batch`      | SQLite read-only            | Pure query             |
| `GET /sessions/{id}/messages` | SQLite + filesystem (JSONL) | File paths from SQLite |

**SQLite access:** Use `better-sqlite3` in read-only mode. SQLite WAL guarantees zero contention with the daemon's writer. Production-proven pattern (Datasette, Litestream).

### Category 2: IPC bridge required (daemon process state)

All remaining 18 endpoints + push events. These call the daemon's `command_handlers`, `CommandService`, `DaemonCache`, `EventBus`, `ContractRegistry`, `RuntimeSettings`, or `Redis`.

### Category 3: WebSocket (Next.js owns, daemon feeds)

Next.js runs the browser-facing WebSocket server. Daemon pushes events over IPC. Next.js relays to subscribed browsers.

---

## 9. Migration Plan

### Phase 0: Diagnostic sprint (parallel with Phase 1)

- Run strace/dtrace during degradation
- Capture lsof snapshots
- Audit asyncio task lifecycle in broadcast paths
- **Duration:** 3-5 days, non-blocking

### Phase 1: Build IPC server alongside uvicorn

1. Implement `IPCServer` class: `asyncio.start_unix_server` on `/tmp/teleclaude-ipc.sock`
2. JSON-RPC dispatcher mapping methods → existing handler functions
3. Wire into `DaemonLifecycle.startup()` alongside `APIServer`
4. Event push: subscribe to EventBus + DaemonCache (same wiring as current WS)
5. Both servers coexist — HTTP API continues working

**Scope:** ~300 lines Python. **Duration:** 1 week.

### Phase 2: Build Next.js IPC client

1. `daemon-ipc-client.ts`: persistent connection, JSON-RPC, request/response correlation, reconnection
2. Replace `daemon-client.ts` (HTTP) with IPC calls in existing Next.js routes
3. Next.js WebSocket route bridging IPC events to browsers
4. Test: all existing web UI functionality works through IPC

**Scope:** ~300 lines TypeScript. **Duration:** 1 week.

### Phase 3: Native reads + streaming

1. Add `better-sqlite3` for read-only access to `teleclaude.db`
2. Native routes: agent availability, memory search, session messages
3. Port JSONL transcript reader to TypeScript (for native SSE streaming)
4. Chat stream: Next.js reads files directly, sends user messages via IPC

**Scope:** ~400 lines TypeScript. **Duration:** 1 week.

### Phase 4: Remove uvicorn

1. Remove `APIServer` class + `api_server.py` (~1800 lines)
2. Remove sub-router files (~600 lines)
3. Remove `uvicorn`, `fastapi` from `pyproject.toml`
4. Remove TCP listener on :8420
5. Update `DaemonLifecycle` to start MCP + IPC only
6. Update checkpoint evidence patterns referencing `/tmp/teleclaude-api.sock`

**Scope:** ~2400 lines removed, ~500 added. **Duration:** 2-3 days.

### Phase 5: Cleanup + public API prep

1. Remove FastAPI-specific API models (keep shared DTOs/Pydantic)
2. Update architecture documentation
3. Define public API route structure in Next.js

**Duration:** 2-3 days.

### Parallelism

```
Phase 0 (Debug sprint)  ─────►
Phase 1 (IPC server)    ────────────────────►
Phase 2 (IPC client)           ├── after P1 ──►
Phase 3 (Native reads)  ────────────────────► (independent of P1/P2)
Phase 4 (Remove uvicorn)              ├── after P1+P2 ──►
Phase 5 (Cleanup)                                   ├── after P4 ──►
```

**Total: 3-4 weeks** with each phase independently testable and non-breaking.

---

## 10. What Gets Eliminated

| Component                               | Lines | Status after migration                          |
| --------------------------------------- | ----- | ----------------------------------------------- |
| `teleclaude/api_server.py`              | ~1800 | **Removed**                                     |
| `teleclaude/api/streaming.py`           | ~274  | **Removed** (reads move to Next.js)             |
| `teleclaude/memory/api_routes.py`       | ~118  | **Removed** (reads in Next.js, writes via IPC)  |
| `teleclaude/hooks/api_routes.py`        | ~137  | **Removed** (absorbed into IPC dispatcher)      |
| `teleclaude/channels/api_routes.py`     | ~64   | **Removed** (absorbed into IPC dispatcher)      |
| `uvicorn` dependency + transitive deps  | —     | **Removed**                                     |
| `fastapi` dependency                    | —     | **Removed** (keep Pydantic)                     |
| TCP listener `:8420`                    | —     | **Removed**                                     |
| Unix socket HTTP server                 | —     | **Replaced** by IPC socket                      |
| All monitoring/watchdog for HTTP server | ~200  | **Removed** (simpler IPC needs less monitoring) |

**Net:** ~2600 lines removed. ~800 lines added (IPC server + client + native routes).

---

## 11. Risks

### Risk 1: IPC implementation bugs

**Severity: Medium.** Custom JSON-RPC.
**Mitigation:** Standard protocol, trivial framing, extensive test suite. MCP server is proof the pattern works.

### Risk 2: Connection lifecycle

**Severity: Medium.** Persistent socket drops on daemon restart.
**Mitigation:** Exponential backoff reconnection. Next.js queues requests during reconnection. Same pattern as any WS reconnection.

### Risk 3: SQLite concurrent access from Node.js

**Severity: Low.** WAL mode guarantees safe concurrent reads.
**Mitigation:** `better-sqlite3` with `{readonly: true}`. Production-proven.

### Risk 4: SSE streaming split

**Severity: Medium.** Chat stream currently reads files AND writes to tmux in one endpoint.
**Mitigation:** Clean split — Next.js reads files, writes via IPC. Better separation of concerns.

### Risk 5: Event ordering

**Severity: Low.** IPC push events must arrive in order.
**Mitigation:** Single TCP connection guarantees FIFO. Unix domain sockets are stream-oriented.

### Risk 6: The problem follows the IPC server

**Severity: Low but worth considering.** If the socket degradation is caused by something in the daemon's event handling (not the HTTP stack), the IPC server could degrade too.
**Mitigation:** Phase 0 diagnostic sprint runs in parallel. The IPC protocol is much simpler (no HTTP state machine, no WebSocket upgrade, no ASGI middleware). If degradation still occurs, it conclusively points to daemon-internal issues, not the transport.

---

## 12. Decision Matrix

| Criterion                       | A: ASGI swap | B: Unix socket RPC | C: Move to Next.js | D: Full rewrite            | E: Debug root cause   |
| ------------------------------- | ------------ | ------------------ | ------------------ | -------------------------- | --------------------- |
| **Solves degradation**          | Maybe (50%)  | Very likely (90%)  | Very likely (90%)  | Maybe (70%)                | Maybe (50%)           |
| **Effort**                      | 2-3 days     | 3-4 weeks          | 3-4 weeks (=B)     | 3-6 months                 | 1-2 weeks (uncertain) |
| **Aligns with public API goal** | No           | Yes                | Yes (=B)           | Yes                        | No                    |
| **Risk of new bugs**            | Low          | Medium             | Medium             | Very High                  | None                  |
| **Eliminates HTTP from daemon** | No           | Yes                | Yes                | Yes                        | No                    |
| **Non-breaking migration**      | Yes          | Yes (phased)       | Yes (phased)       | No                         | N/A                   |
| **Strategic value**             | None         | High               | High (=B)          | Highest (but at what cost) | Diagnostic only       |

---

## 13. Recommendation

### Primary: Option B (Unix socket JSON-RPC)

Replace the uvicorn/FastAPI HTTP server with a raw Unix socket JSON-RPC server. Next.js owns all HTTP/WS/SSE. Daemon becomes a headless process orchestrator with a thin IPC interface.

**Why:**

1. **90% likely to solve the degradation** by eliminating the entire HTTP/ASGI stack
2. **Aligns with the public API goal** — Next.js is already the right owner of the HTTP surface
3. **Proven pattern** — the MCP server runs on this exact architecture without degradation
4. **Non-breaking migration** — phases coexist, each independently testable
5. **Net code reduction** — removes more code than it adds
6. **3-4 weeks** — reasonable investment for a strategic architectural improvement

### Fallback: Option A first (ASGI swap)

If timeline pressure requires a quick fix, swap uvicorn for hypercorn in 2-3 days. This is a diagnostic step: if degradation stops, the bug was uvicorn-specific. If it continues, proceed with Option B.

### Parallel: Phase 0 debug sprint

Run strace/dtrace and audit asyncio task lifecycle during the first week of Phase 1. Findings inform whether the problem is in the HTTP stack (confirms Option B solves it) or in daemon internals (means Option B also needs daemon-side fixes).

### Not recommended: Options D and E as primary

Full rewrite (D) is disproportionate — 3-6 months for a problem solvable in 3-4 weeks. Pure debugging (E) doesn't advance the strategic goal and has uncertain outcome after 3 months of attempts.
