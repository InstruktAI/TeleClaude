# Implementation Plan: web-api-proxy-completion

## Overview

Complete the Next.js thin proxy layer by adding a WebSocket bridge, 10 REST proxy routes, authorization enforcement, and frontend state integration. Five parallel work streams identified; Streams 1-3 can run concurrently, Streams 4-5 depend on earlier streams.

Architecture decision: **thin proxy (Option C)** per research findings. No daemon API migration. Next.js owns auth + web contract; daemon owns business logic.

## Stream 1: WebSocket Bridge (Critical Path)

### Task 1.1: Add `ws` package dependency

**File(s):** `frontend/package.json`

- [ ] `pnpm add ws` and `pnpm add -D @types/ws`
- [ ] Verify `pnpm build` succeeds

### Task 1.2: Implement WebSocket route handler

**File(s):** `frontend/app/api/ws/route.ts`

- [ ] Create Next.js route handler that upgrades HTTP to WebSocket
- [ ] Validate auth on upgrade via NextAuth `auth()` -- reject with 401 if unauthenticated
- [ ] On successful auth, connect to daemon WS at `ws://127.0.0.1:8420/ws`
- [ ] Bridge messages bidirectionally: browser -> daemon, daemon -> browser
- [ ] Inject identity context (`X-Web-User-*` headers) into initial connection or subscription messages
- [ ] Handle daemon disconnect: close browser connection with appropriate close code
- [ ] Handle browser disconnect: close daemon connection, clean up

### Task 1.3: Add daemon-side reconnection logic

**File(s):** `frontend/app/api/ws/route.ts` (or `frontend/lib/proxy/ws-bridge.ts`)

- [ ] Detect daemon WS disconnect (close event, error event)
- [ ] Implement exponential backoff reconnection (1s, 2s, 4s, max 30s)
- [ ] On reconnect: replay active subscriptions to daemon
- [ ] Track subscription state per browser client for replay
- [ ] Send reconnection status to browser client (custom message type)

### Task 1.4: Test WebSocket bridge

**File(s):** `frontend/__tests__/ws-bridge.test.ts` (or equivalent)

- [ ] Unit test: auth rejection on unauthenticated upgrade
- [ ] Unit test: message bridging (browser -> daemon, daemon -> browser)
- [ ] Unit test: daemon disconnect triggers browser close
- [ ] Unit test: reconnection with subscription replay

**Verification:** Browser can connect to `/api/ws`, subscribe to session events, and receive real-time updates.

---

## Stream 2: REST Proxy Expansion

### Task 2.1: Session action routes

**File(s):**

- `frontend/app/api/sessions/[id]/route.ts` -- add DELETE handler
- `frontend/app/api/sessions/[id]/messages/route.ts` -- new
- `frontend/app/api/sessions/[id]/agent-restart/route.ts` -- new
- `frontend/app/api/sessions/[id]/revive/route.ts` -- new

- [ ] `DELETE /api/sessions/[id]` -> `DELETE /sessions/{id}` (auth + ownership check)
- [ ] `GET /api/sessions/[id]/messages` -> `GET /sessions/{id}/messages` (auth)
- [ ] `POST /api/sessions/[id]/agent-restart` -> `POST /sessions/{id}/agent-restart` (admin-only)
- [ ] `POST /api/sessions/[id]/revive` -> `POST /sessions/{id}/revive` (auth + ownership check)
- [ ] All routes: auth check, identity headers, `daemonRequest()`, error passthrough

### Task 2.2: Resource list routes

**File(s):**

- `frontend/app/api/computers/route.ts` -- new
- `frontend/app/api/projects/route.ts` -- new
- `frontend/app/api/todos/route.ts` -- new
- `frontend/app/api/agents/availability/route.ts` -- new

- [ ] `GET /api/computers` -> `GET /computers` (auth)
- [ ] `GET /api/projects` -> `GET /projects` (auth)
- [ ] `GET /api/todos` -> `GET /todos` (auth)
- [ ] `GET /api/agents/availability` -> `GET /agents/availability` (auth)
- [ ] All routes: auth check, identity headers, `daemonRequest()`, error passthrough

### Task 2.3: Settings routes

**File(s):** `frontend/app/api/settings/route.ts` -- new

- [ ] `GET /api/settings` -> `GET /settings` (auth)
- [ ] `PATCH /api/settings` -> `PATCH /settings` (admin-only, field allowlist)
- [ ] Settings PATCH: allowlist specific fields to prevent injection of unexpected keys

### Task 2.4: Test REST proxy routes

**File(s):** `frontend/__tests__/api-proxies.test.ts` (or per-route test files)

- [ ] Test auth rejection (401) for each route
- [ ] Test admin-only rejection (403) for settings PATCH and agent-restart
- [ ] Test successful proxy passthrough (mock daemon responses)
- [ ] Test error passthrough (daemon returns 404, 500, etc.)
- [ ] Test session ownership check on DELETE

**Verification:** All 10 new routes respond correctly with auth, forward to daemon, and pass through errors.

---

## Stream 3: Authorization Enrichment

### Task 3.1: Role-based middleware enhancements

**File(s):** `frontend/middleware.ts`

- [ ] Ensure all `/api/*` routes (except `/api/auth`, `/api/people`) require auth
- [ ] Add utility function `requireAdmin(session)` that returns 403 if not admin
- [ ] Add utility function `requireOwnership(session, sessionId)` that checks `human_email` match

### Task 3.2: Daemon-side identity header validation

**File(s):** `teleclaude/api_server.py` (minimal change)

- [ ] Add middleware/dependency that checks: if `X-Web-User-*` headers present, request must come from Unix socket or 127.0.0.1
- [ ] Reject requests with identity headers from non-trusted sources with 403
- [ ] Log rejected attempts at WARNING level

### Task 3.3: Test authorization

- [ ] Test admin route access by non-admin (403)
- [ ] Test session ownership check (user A can't delete user B's session)
- [ ] Test daemon rejects spoofed identity headers from external source

**Verification:** Role-based and ownership-based access control enforced end-to-end.

---

## Stream 4: Frontend WebSocket Client (depends on Stream 1)

### Task 4.1: WebSocket context and hook

**File(s):** `frontend/lib/ws/WebSocketProvider.tsx`, `frontend/lib/ws/useWebSocket.ts`

- [ ] Create `WebSocketProvider` that manages a single WS connection per authenticated session
- [ ] `useWebSocket()` hook exposes: `status`, `subscribe()`, `unsubscribe()`, `lastEvent`
- [ ] Connection states: `connecting`, `connected`, `reconnecting`, `disconnected`
- [ ] Auto-connect on mount, auto-disconnect on unmount
- [ ] Reconnection with exponential backoff (mirrors server-side logic)

### Task 4.2: Event type definitions

**File(s):** `frontend/lib/ws/types.ts`

- [ ] Define TypeScript types for daemon WS messages: subscription request/response, session events, computer events, error messages
- [ ] Match daemon's `SessionSummaryDTO`, `ComputerDTO` shapes
- [ ] Type-safe event dispatcher

### Task 4.3: Integrate WebSocket provider into app layout

**File(s):** `frontend/app/(chat)/layout.tsx`

- [ ] Wrap authenticated layout with `<WebSocketProvider>`
- [ ] Connection status available to all child components

**Verification:** Browser connects to WS on login, receives real-time session events, reconnects after daemon restart.

---

## Stream 5: Frontend State Management (depends on Streams 2 + 4)

### Task 5.1: Add React Query

**File(s):** `frontend/package.json`, `frontend/lib/query/QueryProvider.tsx`

- [ ] `pnpm add @tanstack/react-query`
- [ ] Create `QueryClientProvider` wrapper in app layout
- [ ] Configure default stale time, retry, and error handling

### Task 5.2: Data-fetching hooks

**File(s):** `frontend/lib/hooks/useSessions.ts`, `useComputers.ts`, `useProjects.ts`, etc.

- [ ] `useSessions()` -- fetches `GET /api/sessions`, cache key `['sessions']`
- [ ] `useComputers()` -- fetches `GET /api/computers`, cache key `['computers']`
- [ ] `useProjects(computer)` -- fetches `GET /api/projects?computer=X`, cache key `['projects', computer]`
- [ ] `useTodos()` -- fetches `GET /api/todos`, cache key `['todos']`
- [ ] `useAgentAvailability()` -- fetches `GET /api/agents/availability`
- [ ] `useSettings()` -- fetches `GET /api/settings` (admin only)

### Task 5.3: WebSocket-driven cache invalidation

**File(s):** `frontend/lib/ws/useCacheInvalidation.ts`

- [ ] Listen to WS events and invalidate corresponding React Query caches
- [ ] `session_updated` / `session_created` / `session_closed` -> invalidate `['sessions']`
- [ ] `computer_updated` -> invalidate `['computers']`
- [ ] Avoid full refetch on every event: use granular invalidation

### Task 5.4: Mutation hooks

**File(s):** `frontend/lib/hooks/useSessionActions.ts`, etc.

- [ ] `useEndSession(id)` -- calls `DELETE /api/sessions/[id]`, optimistic removal from cache
- [ ] `useCreateSession()` -- calls `POST /api/sessions`, invalidates session list
- [ ] `useAgentRestart(id)` -- calls `POST /api/sessions/[id]/agent-restart`
- [ ] `useUpdateSettings()` -- calls `PATCH /api/settings`

**Verification:** Frontend lists update in real-time via WS events; mutations reflect immediately via optimistic updates.

---

## Build Sequence

```
Stream 1 (WS Bridge)     ──────────────────────────────────►
Stream 2 (REST Proxy)     ──────────────────────────────────►
Stream 3 (Auth/RBAC)      ──────────────────────────────────►
Stream 4 (FE WS Client)          ├── after Stream 1 ───────►
Stream 5 (FE State)                       ├── after 2+4 ───►
```

Streams 1, 2, 3 can run fully in parallel (assigned to separate team members).
Stream 4 starts once Stream 1 delivers a working WS route.
Stream 5 starts once Streams 2 and 4 are both available.

## Files Changed (estimated)

| File                                                    | Change                                                     |
| ------------------------------------------------------- | ---------------------------------------------------------- |
| `frontend/package.json`                                 | Add `ws`, `@types/ws`, `@tanstack/react-query`             |
| `frontend/app/api/ws/route.ts`                          | New: WebSocket bridge route                                |
| `frontend/lib/proxy/ws-bridge.ts`                       | New: WS bridge logic (reconnection, subscription tracking) |
| `frontend/app/api/sessions/[id]/route.ts`               | Add DELETE handler                                         |
| `frontend/app/api/sessions/[id]/messages/route.ts`      | New: transcript messages proxy                             |
| `frontend/app/api/sessions/[id]/agent-restart/route.ts` | New: agent restart proxy                                   |
| `frontend/app/api/sessions/[id]/revive/route.ts`        | New: session revival proxy                                 |
| `frontend/app/api/computers/route.ts`                   | New: computers list proxy                                  |
| `frontend/app/api/projects/route.ts`                    | New: projects list proxy                                   |
| `frontend/app/api/todos/route.ts`                       | New: todos list proxy                                      |
| `frontend/app/api/agents/availability/route.ts`         | New: agent availability proxy                              |
| `frontend/app/api/settings/route.ts`                    | New: settings read/write proxy                             |
| `frontend/middleware.ts`                                | Enhance auth coverage for new routes                       |
| `frontend/lib/ws/WebSocketProvider.tsx`                 | New: WS connection context                                 |
| `frontend/lib/ws/useWebSocket.ts`                       | New: WS hook                                               |
| `frontend/lib/ws/types.ts`                              | New: WS message types                                      |
| `frontend/lib/ws/useCacheInvalidation.ts`               | New: WS -> React Query bridge                              |
| `frontend/lib/query/QueryProvider.tsx`                  | New: React Query provider                                  |
| `frontend/lib/hooks/useSessions.ts`                     | New: sessions data hook                                    |
| `frontend/lib/hooks/useComputers.ts`                    | New: computers data hook                                   |
| `frontend/lib/hooks/useProjects.ts`                     | New: projects data hook                                    |
| `frontend/lib/hooks/useSessionActions.ts`               | New: session mutation hooks                                |
| `frontend/app/(chat)/layout.tsx`                        | Add WS and Query providers                                 |
| `teleclaude/api_server.py`                              | Add identity header source validation                      |

## Risks

1. **Next.js WebSocket support** -- App Router has limited native WS support. May need `next-ws` package or custom server. Research actual API before implementation.
2. **React Query + WS cache invalidation** -- Granular invalidation is tricky. Start with broad invalidation (invalidate all sessions on any session event) and optimize later.
3. **Daemon subscription protocol** -- Must match daemon's expected message format exactly. Read `teleclaude/api_server.py` WebSocket handler implementation before writing bridge.
4. **Auth on WS upgrade** -- NextAuth session cookies must be accessible during WS upgrade. Verify Next.js passes cookies on upgrade request.

## Verification

- All 10 REST proxy routes return correct data with auth
- WebSocket bridge connects and relays messages bidirectionally
- Frontend React Query hooks return data from proxied endpoints
- WebSocket events trigger cache invalidation (session list refreshes on session create/delete)
- Admin-only routes reject non-admin users
- `make lint` and `pnpm tsc --noEmit` pass
- `web-api-facade` route map updated
