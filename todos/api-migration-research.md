# API Migration Research: Python Daemon to Next.js API Routes

**Date:** 2026-02-16
**Status:** Research complete

---

## 1. Current API Surface Audit

### 1.1 Python Daemon Endpoints (api_server.py + sub-routers)

The daemon serves a FastAPI application on both a Unix socket (`/tmp/teleclaude-api.sock`) and TCP (`127.0.0.1:8420`). Four sub-routers are mounted into the same process.

#### Core API (api_server.py)

| Method | Path                           | Purpose                                | Dependencies                 |
| ------ | ------------------------------ | -------------------------------------- | ---------------------------- |
| GET    | `/health`                      | Health check                           | None                         |
| GET    | `/sessions`                    | List sessions (local + cached remote)  | DaemonCache, SQLite, Redis   |
| POST   | `/sessions`                    | Create session                         | CommandService, tmux, SQLite |
| DELETE | `/sessions/{id}`               | End session                            | CommandService, tmux         |
| POST   | `/sessions/{id}/message`       | Send message to session                | CommandService, tmux         |
| POST   | `/sessions/{id}/keys`          | Send key command to session            | CommandService, tmux         |
| POST   | `/sessions/{id}/voice`         | Send voice input to session            | CommandService, file I/O     |
| POST   | `/sessions/{id}/file`          | Send file to session                   | CommandService, file I/O     |
| POST   | `/sessions/{id}/agent-restart` | Restart agent in session               | CommandService, tmux, SQLite |
| POST   | `/sessions/{id}/revive`        | Revive closed session                  | CommandService, tmux, SQLite |
| GET    | `/sessions/{id}/messages`      | Get structured transcript messages     | SQLite, filesystem (JSONL)   |
| GET    | `/computers`                   | List computers (local + cached remote) | DaemonCache, Redis           |
| GET    | `/projects`                    | List projects (local + cached remote)  | DaemonCache, Redis           |
| GET    | `/agents/availability`         | Get agent availability                 | SQLite                       |
| GET    | `/api/people`                  | List people from config                | YAML config file             |
| GET    | `/settings`                    | Get runtime settings                   | RuntimeSettings              |
| PATCH  | `/settings`                    | Update runtime settings                | RuntimeSettings              |
| GET    | `/todos`                       | List todos (local + cached remote)     | DaemonCache, filesystem      |
| WS     | `/ws`                          | WebSocket for push updates             | DaemonCache, EventBus        |

#### Memory Router (`/api/memory/*` — teleclaude/memory/api_routes.py)

| Method | Path                   | Purpose                   | Dependencies           |
| ------ | ---------------------- | ------------------------- | ---------------------- |
| POST   | `/api/memory/save`     | Save observation          | SQLite (memory tables) |
| GET    | `/api/memory/search`   | Search observations (FTS) | SQLite (FTS)           |
| GET    | `/api/memory/timeline` | Timeline around anchor    | SQLite                 |
| POST   | `/api/memory/batch`    | Bulk fetch observations   | SQLite                 |
| DELETE | `/api/memory/{id}`     | Delete observation        | SQLite                 |
| GET    | `/api/memory/inject`   | Generate context markdown | SQLite                 |

#### Hooks Router (`/hooks/*` — teleclaude/hooks/api_routes.py)

| Method | Path                    | Purpose                  | Dependencies                          |
| ------ | ----------------------- | ------------------------ | ------------------------------------- |
| GET    | `/hooks/contracts`      | List webhook contracts   | ContractRegistry (in-memory + SQLite) |
| GET    | `/hooks/properties`     | List property vocabulary | ContractRegistry                      |
| POST   | `/hooks/contracts`      | Create webhook contract  | ContractRegistry                      |
| DELETE | `/hooks/contracts/{id}` | Deactivate contract      | ContractRegistry                      |

#### Channels Router (`/api/channels/*` — teleclaude/channels/api_routes.py)

| Method | Path                           | Purpose              | Dependencies |
| ------ | ------------------------------ | -------------------- | ------------ |
| POST   | `/api/channels/{name}/publish` | Publish to channel   | Redis        |
| GET    | `/api/channels/`               | List active channels | Redis        |

#### Streaming Router (`/api/chat/*` — teleclaude/api/streaming.py)

| Method | Path               | Purpose                               | Dependencies                            |
| ------ | ------------------ | ------------------------------------- | --------------------------------------- |
| POST   | `/api/chat/stream` | SSE chat stream (history + live tail) | SQLite, filesystem (JSONL), tmux_bridge |

**Total: 26 endpoints + 1 WebSocket**

### 1.2 Next.js Frontend API Routes (currently implemented)

| Next.js Route                      | Mode         | Upstream Daemon Path          | Notes                          |
| ---------------------------------- | ------------ | ----------------------------- | ------------------------------ |
| `GET /api/sessions`                | proxy        | `GET /sessions`               | Auth-gated, identity headers   |
| `POST /api/sessions`               | proxy        | `POST /sessions`              | Enriches with human_email/role |
| `POST /api/sessions/[id]/messages` | proxy        | `POST /sessions/{id}/message` | Auth-gated                     |
| `POST /api/chat`                   | stream-proxy | `POST /api/chat/stream`       | Streams SSE through            |
| `GET /api/people`                  | native       | N/A                           | Reads YAML config directly     |
| `GET,POST /api/auth/[...nextauth]` | native       | N/A                           | NextAuth v5 handlers           |

**Coverage: 5 of 26 daemon endpoints are proxied/implemented in Next.js.** The people route is already "native" (reads config directly without daemon).

### 1.3 Endpoints NOT Proxied (consumed directly or unused by web)

These daemon endpoints have no Next.js proxy and are consumed by TUI, MCP, or internal systems:

- `DELETE /sessions/{id}` — end session
- `POST /sessions/{id}/keys` — key commands
- `POST /sessions/{id}/voice` — voice input
- `POST /sessions/{id}/file` — file upload
- `POST /sessions/{id}/agent-restart` — agent restart
- `POST /sessions/{id}/revive` — session revival
- `GET /sessions/{id}/messages` — transcript messages
- `GET /computers` — computer list
- `GET /projects` — project list
- `GET /agents/availability` — agent status
- `GET,PATCH /settings` — runtime settings
- `GET /todos` — todo list
- `WS /ws` — WebSocket push updates
- All `/api/memory/*` endpoints (6)
- All `/hooks/*` endpoints (4)
- All `/api/channels/*` endpoints (2)
- `GET /health`

---

## 2. Migration Feasibility Assessment

### Category A: Can Migrate to Next.js (read-only, data-fetch endpoints)

These endpoints read from cache/DB and have no daemon process dependencies:

| Endpoint                      | Feasibility        | Notes                                                                                                                 |
| ----------------------------- | ------------------ | --------------------------------------------------------------------------------------------------------------------- |
| `GET /api/people`             | **Already native** | Reads YAML directly in Next.js                                                                                        |
| `GET /sessions`               | Medium             | Requires access to DaemonCache and SQLite. Could query daemon SQLite read-only, but cache merge logic is non-trivial. |
| `GET /sessions/{id}/messages` | Medium             | Reads JSONL transcript files from filesystem. Could work in Next.js if filesystem is shared.                          |
| `GET /computers`              | Medium             | Local info + cache merge. Local computer info needs system calls.                                                     |
| `GET /projects`               | Medium             | Cache merge + stale refresh triggers.                                                                                 |
| `GET /agents/availability`    | Easy               | Pure SQLite read.                                                                                                     |
| `GET /settings`               | Easy               | Reads RuntimeSettings state.                                                                                          |
| `GET /todos`                  | Medium             | Cache + filesystem reads.                                                                                             |
| `GET /health`                 | Easy               | Trivial.                                                                                                              |
| `GET /api/memory/search`      | Medium             | SQLite FTS query. Could query daemon DB read-only.                                                                    |
| `GET /api/memory/timeline`    | Medium             | SQLite query.                                                                                                         |
| `GET /api/memory/inject`      | Medium             | SQLite query + text generation.                                                                                       |
| `GET /hooks/contracts`        | Medium             | SQLite/registry query.                                                                                                |
| `GET /hooks/properties`       | Medium             | Registry query.                                                                                                       |
| `GET /api/channels/`          | Hard               | Requires active Redis connection.                                                                                     |

### Category B: Cannot Migrate — Must Stay in Python Daemon

These endpoints require direct daemon process access:

| Endpoint                            | Reason                                                                                                |
| ----------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `POST /sessions`                    | Creates tmux sessions via CommandService. Daemon owns tmux lifecycle.                                 |
| `DELETE /sessions/{id}`             | Kills tmux sessions.                                                                                  |
| `POST /sessions/{id}/message`       | Writes to tmux pane via CommandService/tmux_bridge.                                                   |
| `POST /sessions/{id}/keys`          | Sends keystrokes to tmux.                                                                             |
| `POST /sessions/{id}/voice`         | Processes voice input, writes to tmux.                                                                |
| `POST /sessions/{id}/file`          | Processes file, writes to tmux.                                                                       |
| `POST /sessions/{id}/agent-restart` | Restarts agent process in tmux.                                                                       |
| `POST /sessions/{id}/revive`        | Restarts agent with session recovery.                                                                 |
| `POST /api/chat/stream`             | Reads live JSONL transcript AND writes to tmux. Needs daemon DB + filesystem + tmux_bridge.           |
| `PATCH /settings`                   | Mutates daemon RuntimeSettings (affects daemon behavior).                                             |
| `POST /api/memory/save`             | Writes to daemon's SQLite (shared with daemon process).                                               |
| `DELETE /api/memory/{id}`           | Deletes from daemon's SQLite.                                                                         |
| `POST /api/memory/batch`            | Could be read-only but shares DB write path.                                                          |
| `POST /hooks/contracts`             | Registers in-memory contract in daemon process.                                                       |
| `DELETE /hooks/contracts/{id}`      | Modifies in-memory contract registry.                                                                 |
| `POST /api/channels/{name}/publish` | Requires daemon's Redis connection.                                                                   |
| `WS /ws`                            | Subscribes to DaemonCache change events, EventBus events. Fundamentally tied to daemon process state. |

### Summary

- **~6 read-only endpoints** could feasibly move to Next.js (agent availability, settings read, health, people, some memory reads)
- **~20 endpoints** require daemon process access and cannot meaningfully migrate
- The WebSocket is the most complex — it's the real-time nerve center connecting cache, EventBus, and all subscription management

---

## 3. Architecture Options

### Option A: Full Migration — Next.js owns all HTTP, Python becomes library/worker

**How it would work:**

- All HTTP/WS endpoints move to Next.js API routes
- Python daemon becomes a background worker (no HTTP server)
- Next.js calls Python via: subprocess, IPC pipe, or message queue
- All tmux operations, cache, SQLite remain in Python

**Pros:**

- Single HTTP surface for all clients (TUI, web, MCP)
- Auth in one place
- Modern TypeScript ecosystem

**Cons:**

- **Massive scope**: 26 endpoints to rewrite + WebSocket
- **IPC latency**: Every write operation needs to cross process boundary (Node -> Python)
- **Dual-runtime complexity**: Two processes must coordinate state
- **DaemonCache/EventBus**: These in-memory systems drive the WebSocket. Replicating event-driven push in Next.js means either:
  - Polling the daemon (defeats purpose)
  - Building a Node-side event bus that mirrors daemon events
  - Running a persistent WebSocket from Next.js to daemon (basically a proxy with extra steps)
- **TUI regression risk**: TUI currently uses Unix socket directly. Would need repointing.
- **MCP server**: Also uses daemon's API. Would need migration.
- **SQLite contention**: Two processes (Next.js + Python) accessing same SQLite DB introduces WAL contention
- **Timeline**: Months of work with high risk of breaking existing TUI/MCP clients

**Verdict: Not recommended.** The Python daemon is fundamentally a process orchestrator (tmux, Redis, SQLite, EventBus). Moving its HTTP surface to Node.js doesn't eliminate the daemon; it just adds an IPC layer.

### Option B: Partial Migration — Next.js owns public/web API, Python retains internal/daemon APIs

**How it would work:**

- Next.js routes serve browser clients exclusively
- Read-only data endpoints migrate to Next.js (reading daemon's SQLite, filesystem)
- Write/mutation endpoints stay as proxies to daemon
- WebSocket stays in daemon; Next.js connects as a WS client and re-broadcasts to browser

**Pros:**

- Auth consolidation for web tier
- Some endpoints become "native" (faster, no Unix socket hop)
- Gradual migration possible

**Cons:**

- **SQLite dual-access**: Next.js reading daemon's SQLite while daemon writes creates contention. WAL helps but isn't zero-cost.
- **Cache coherence**: DaemonCache is in-memory in Python. Next.js would see stale DB data unless it also subscribes to change events.
- **Two WebSocket layers**: Browser <-> Next.js WS <-> Daemon WS. Added latency and failure modes.
- **Split logic**: "Am I reading from daemon or locally?" becomes a per-route decision that drifts over time.
- **Maintenance cost**: Two HTTP stacks serving partially overlapping data, each with their own bug surface.

**Verdict: Possible but high ongoing cost.** Gains are marginal unless there's a strong reason to move specific queries off the daemon.

### Option C: Thin Proxy (Current Pattern) — Next.js routes are auth-enriched proxies to daemon

**How it would work (already in place):**

- Next.js API routes are the public contract for browser clients
- Each route validates auth (NextAuth), builds identity headers, proxies to daemon via Unix socket
- Daemon handles all business logic, cache, tmux, SQLite
- One exception already exists: `/api/people` is native (reads YAML directly)

**Pros:**

- **Already working**: 5 routes implemented, pattern proven
- **Clear separation**: Next.js = auth + web contract. Daemon = business logic.
- **No SQLite contention**: Only one process writes/reads the daemon DB
- **No duplicate caching**: DaemonCache is single source of truth
- **Incremental**: New routes added as needed without architectural risk
- **Reversible**: Any route can later be moved to native if needed
- **Aligns with web-api-facade doc**: This is literally the documented architecture

**Cons:**

- Every web request adds ~2-5ms Unix socket hop
- Daemon must stay running for web to function
- WebSocket proxy not yet implemented (biggest gap)

**Verdict: Recommended.** This is the right architecture for where the system is today.

---

## 4. Recommended Approach

### **Stay on Option C (Thin Proxy) with targeted expansions**

The codebase already has a documented architecture for this: `project/design/architecture/web-api-facade`. The current pattern works. The daemon owns too many process-level concerns (tmux, EventBus, in-memory cache, Redis transport) for a migration to make sense.

### Immediate priorities (complete the proxy surface):

1. **WebSocket proxy**: This is the biggest gap. Browser currently has no WS path. Next.js needs a route that:
   - Accepts browser WebSocket connections (with auth)
   - Connects to daemon's `ws://localhost:8420/ws` as a client
   - Bridges messages bidirectionally
   - Handles reconnection when daemon restarts

2. **Additional REST proxies** for endpoints the web UI needs:
   - `GET /api/computers` → proxy to `GET /computers`
   - `GET /api/projects` → proxy to `GET /projects`
   - `DELETE /api/sessions/[id]` → proxy to `DELETE /sessions/{id}`
   - `GET /api/sessions/[id]/messages` → proxy to `GET /sessions/{id}/messages`
   - `POST /api/sessions/[id]/agent-restart` → proxy to `POST /sessions/{id}/agent-restart`
   - `POST /api/sessions/[id]/revive` → proxy to `POST /sessions/{id}/revive`
   - `GET /api/todos` → proxy to `GET /todos`
   - `GET /api/agents/availability` → proxy to `GET /agents/availability`

3. **Settings proxy** (if web UI needs runtime settings):
   - `GET /api/settings` → proxy to `GET /settings`
   - `PATCH /api/settings` → proxy to `PATCH /settings`

### Routes that can stay native in Next.js:

- `GET /api/people` — already native, reads YAML config. No reason to proxy.
- `GET /api/auth/*` — NextAuth handlers. These are inherently Next.js.

### Routes unlikely needed by web UI:

- `/sessions/{id}/keys`, `/sessions/{id}/voice`, `/sessions/{id}/file` — TUI/Telegram-specific input methods
- `/api/memory/*` — MCP tool surface, consumed by AI agents
- `/hooks/*` — webhook management, consumed by CLI/daemon
- `/api/channels/*` — internal Redis channel management
- `/health` — daemon health, not exposed to browsers

### Future consideration: when to move a route to "native"

A route graduates from `proxy` to `native` when:

1. It serves only web clients (no TUI/MCP dependency)
2. Its data source is accessible from Next.js without contention (e.g., read-only file, separate DB)
3. The latency saving justifies the maintenance cost
4. The daemon endpoint can be deprecated

Today, only `/api/people` meets these criteria.

---

## 5. Parallel Work Streams

If this were a todo executed by a team, the following streams are independent:

### Stream 1: WebSocket Bridge (Critical Path)

- Implement Next.js WebSocket route handler
- Build daemon WS client (connect to `ws://localhost:8420/ws`)
- Implement auth validation on WS upgrade
- Add bidirectional message bridging
- Handle daemon restart reconnection
- **Blocked by**: Nothing. Can start immediately.
- **Blocks**: Any web UI feature needing real-time updates

### Stream 2: REST Proxy Expansion

- Add proxy routes for: computers, projects, todos, agents/availability, session messages, session delete, agent-restart, revive
- All follow the same pattern as existing routes (auth + daemonRequest)
- **Blocked by**: Nothing. Can start immediately.
- **Independent of**: Stream 1 (WS bridge)

### Stream 3: Identity & Authorization Enrichment

- Daemon currently receives identity headers but does minimal enforcement
- Define RBAC rules: who can create/end sessions, view which computers, etc.
- Implement middleware in Next.js for role-based access
- Add daemon-side validation of identity headers
- **Blocked by**: Nothing, but should align with business requirements
- **Independent of**: Streams 1 and 2

### Stream 4: Frontend WebSocket Client

- Build React hook/context for WebSocket connection to Next.js
- Handle subscription management (sessions, projects, todos per computer)
- Implement reconnection logic
- Replace any polling patterns with WS-driven updates
- **Blocked by**: Stream 1 (WS bridge must exist)

### Stream 5: Frontend State Management

- Wire REST proxy responses into frontend state (React Query, SWR, or context)
- Integrate WebSocket push updates with cache invalidation
- **Blocked by**: Streams 2 and 4

### Parallelism Matrix

```
Stream 1 (WS Bridge)  ──────────────────────────────────►
Stream 2 (REST Proxy)  ──────────────────────────────────►
Stream 3 (Auth/RBAC)   ──────────────────────────────────►
Stream 4 (FE WS Client)        ├── after Stream 1 ──────►
Stream 5 (FE State)                     ├── after 2+4 ──►
```

Streams 1, 2, and 3 can run fully in parallel. Streams 4 and 5 have dependencies.

---

## 6. Risks and Blockers

### Risk 1: WebSocket Bridging Complexity

**Severity: High**
The daemon WS is stateful (subscription-based, with interest tracking that drives cache refresh). The Next.js bridge must faithfully relay subscription/unsubscription messages and handle daemon restarts without losing client state.

**Mitigation**: Start with a simple message pass-through. The daemon already handles subscription logic — the bridge just needs to be a transparent pipe with auth.

### Risk 2: Daemon Unavailability During Restarts

**Severity: Medium**
The daemon restarts for upgrades, config changes, or crashes. During restart, all proxied routes return 503. The current proxy already handles this with try/catch + "Service unavailable" responses.

**Mitigation**: Frontend should show "reconnecting" state. WebSocket bridge needs exponential backoff reconnection. Consider a health-check polling endpoint in Next.js that reports daemon status.

### Risk 3: Unix Socket Performance Under Load

**Severity: Low**
Each proxied request adds a Unix socket round-trip (~2-5ms). For most operations this is negligible. The SSE streaming endpoint is the exception — it maintains a long-lived connection.

**Mitigation**: The chat stream proxy already works. For bulk operations (list sessions, list projects), the latency is acceptable. If it ever becomes an issue, specific read-only endpoints can be moved to native.

### Risk 4: Two SQLite Databases

**Severity: Low (already the case)**
The frontend already has its own SQLite (`teleclaude-web.db`) for NextAuth sessions, separate from the daemon's `teleclaude.db`. This is correct — they serve different purposes. No additional risk here.

### Risk 5: Auth Token Leakage

**Severity: Medium**
Identity headers (`X-Web-User-Email`, `X-Web-User-Name`, `X-Web-User-Role`) are injected by Next.js server code. If daemon TCP port (8420) is exposed beyond localhost, these headers could be spoofed.

**Mitigation**: Daemon TCP server already binds to `127.0.0.1`. Add daemon-side validation: reject requests with identity headers unless they come from the Unix socket or a trusted source.

### Risk 6: SSE Stream Proxy Reliability

**Severity: Medium**
The chat stream is a long-lived SSE connection: browser → Next.js → daemon. If either hop drops, the client loses the stream. The current implementation handles upstream errors but doesn't auto-reconnect the SSE stream.

**Mitigation**: Frontend should implement SSE reconnection with `since_timestamp` to resume from last received event. The daemon streaming endpoint already supports `since_timestamp`.

### Risk 7: Feature Drift Between TUI and Web

**Severity: Low**
TUI talks to daemon directly; web talks through Next.js proxy. New daemon endpoints might not get corresponding Next.js routes, leaving the web UI behind.

**Mitigation**: The web-api-facade doc's route map tracks this. Add a CI check that compares daemon endpoints with Next.js routes and flags unmapped ones.

---

## 7. Key Dependencies

| Dependency                               | Current State                   | Risk                                                                     |
| ---------------------------------------- | ------------------------------- | ------------------------------------------------------------------------ |
| Python daemon process                    | Running, stable                 | Must stay up for web to function                                         |
| Unix socket (`/tmp/teleclaude-api.sock`) | Active                          | Next.js server must have filesystem access                               |
| TCP listener (`127.0.0.1:8420`)          | Active                          | WebSocket bridge needs TCP (WS over Unix socket is not standard in Node) |
| NextAuth v5                              | Configured with Drizzle adapter | Stable                                                                   |
| Daemon SQLite (`teleclaude.db`)          | Daemon-exclusive access         | Do not share; proxy all writes                                           |
| Web SQLite (`teleclaude-web.db`)         | Next.js-exclusive access        | Auth sessions only                                                       |
| Redis                                    | Optional for daemon             | Channels/cross-computer features require it                              |
| DaemonCache (in-memory)                  | Python process only             | Not accessible from Node; must proxy                                     |
| EventBus (in-memory)                     | Python process only             | Drives WS push; not accessible from Node                                 |

---

## 8. Conclusion

The Python daemon is not an HTTP API that happens to manage processes — it's a process orchestrator that happens to expose an HTTP API. The HTTP surface exists to give TUI/MCP/web clients a way to invoke daemon operations. Moving that HTTP surface to Next.js would not eliminate the daemon; it would just add an IPC layer between the web server and the daemon.

**The thin proxy pattern (Option C) is the correct architecture.** It's already documented, partially implemented, and aligns with the system's actual boundaries. The work ahead is:

1. Complete the proxy surface (WebSocket bridge + remaining REST routes)
2. Build the frontend clients that consume them
3. Strengthen identity/auth enforcement

This is a routing and plumbing exercise, not an architectural migration.
