# Requirements: web-api-proxy-completion

## Goal

Complete the Next.js thin proxy layer over the TeleClaude Python daemon API. The daemon is a process orchestrator (tmux, EventBus, cache, Redis, SQLite) that exposes an HTTP/WS surface. Next.js owns auth, identity enrichment, and the web contract; the daemon owns all business logic. This todo closes the gap between the 5 currently proxied routes and the full set needed by the web interface.

## Context

Research (`todos/api-migration-research.md`) evaluated three architecture options and concluded that the **thin proxy pattern (Option C)** is the correct approach. It is already documented in `project/design/architecture/web-api-facade`, partially implemented, and aligns with the system's actual boundaries. Full migration (Option A) would add IPC complexity without eliminating the daemon. Partial migration (Option B) introduces SQLite contention and cache coherence issues.

**Current state:** 5 of 26 daemon endpoints are proxied through Next.js. The WebSocket has no proxy at all.

## Scope

### In scope

1. **WebSocket bridge** -- Next.js WS route that authenticates browser connections, connects to daemon `ws://127.0.0.1:8420/ws`, and bridges messages bidirectionally with reconnection handling.

2. **REST proxy expansion** -- Add proxy routes for all daemon endpoints the web UI needs:
   - `DELETE /api/sessions/[id]` -- end session
   - `GET /api/sessions/[id]/messages` -- transcript messages
   - `POST /api/sessions/[id]/agent-restart` -- agent restart
   - `POST /api/sessions/[id]/revive` -- session revival
   - `GET /api/computers` -- computer list
   - `GET /api/projects` -- project list
   - `GET /api/todos` -- todo list
   - `GET /api/agents/availability` -- agent availability
   - `GET /api/settings` -- runtime settings (read)
   - `PATCH /api/settings` -- runtime settings (write, admin-only)

3. **Identity & authorization enrichment** -- All proxy routes inject identity headers (`X-Web-User-Email`, `X-Web-User-Name`, `X-Web-User-Role`). Admin-only routes enforce role checks. Daemon-side validation rejects identity headers from non-trusted sources.

4. **Frontend WebSocket client** -- React hook/context for WebSocket connection to Next.js WS route, with subscription management and reconnection logic.

5. **Frontend state integration** -- Wire REST and WS data into React state (React Query or similar), with WS-driven cache invalidation replacing polling.

### Out of scope

- TUI/Telegram-specific endpoints: `/sessions/{id}/keys`, `/sessions/{id}/voice`, `/sessions/{id}/file` (not consumed by web UI)
- Memory API (`/api/memory/*`) -- MCP tool surface consumed by AI agents, not browser
- Hooks API (`/hooks/*`) -- webhook management consumed by CLI/daemon
- Channels API (`/api/channels/*`) -- internal Redis channel management
- Health endpoint (`/health`) -- daemon internal, not exposed to browser
- Moving any endpoint from proxy to native (premature optimization; only `/api/people` qualifies today)
- Daemon-side API changes (beyond identity header validation)

## Functional Requirements

### FR1: WebSocket Bridge

- Next.js route accepts browser WebSocket upgrade requests at `/api/ws`
- Auth validated on upgrade (reject unauthenticated connections)
- Connects to daemon WS at `ws://127.0.0.1:8420/ws` as internal client
- Bridges all messages bidirectionally (subscription, events, initial state)
- Handles daemon restart: detect disconnect, exponential backoff reconnection, replay subscriptions
- Injects identity context into subscription messages

### FR2: REST Proxy Routes

- Each new route follows the established pattern: auth check -> identity headers -> `daemonRequest()` -> response passthrough
- Route parameter mapping: Next.js `[id]` -> daemon `{id}`
- Error passthrough: daemon HTTP errors forwarded with status code and body
- Field allowlisting on mutation routes (POST/PATCH/DELETE) to prevent injection

### FR3: Authorization Enforcement

- All proxy routes require authenticated session (NextAuth)
- Admin-only routes (`PATCH /api/settings`, `POST /api/sessions/[id]/agent-restart`) check `session.user.role === 'admin'`
- Non-admin users can only end their own sessions (`DELETE /api/sessions/[id]` with ownership check)
- Daemon validates that identity headers come from trusted source (Unix socket or localhost)

### FR4: Frontend WebSocket Hook

- `useWebSocket()` hook provides connection state, subscription management, and message handlers
- Automatic reconnection with exponential backoff (1s, 2s, 4s, max 30s)
- Subscription API: `subscribe(computer, interests)` / `unsubscribe(computer)`
- Event callbacks for session updates, session created, session closed
- Connection status exposed for UI indicators

### FR5: Frontend State Management

- REST data fetched via React Query (or equivalent) with cache keys
- WebSocket events invalidate relevant query caches (e.g., session update -> invalidate sessions list)
- Optimistic updates where appropriate (e.g., session deletion)
- Loading/error states for all data-fetching hooks

## Non-functional Requirements

1. WebSocket bridge latency: < 50ms added over daemon WS direct connection
2. REST proxy latency: < 10ms added over daemon direct (Unix socket hop)
3. WebSocket reconnection: automatic within 5 seconds of daemon restart
4. No browser console errors during normal operation
5. All proxy routes handle daemon unavailability gracefully (503 with meaningful error)

## Success Criteria

- [ ] All 10 new REST proxy routes implemented and tested
- [ ] WebSocket bridge connects, authenticates, and bridges messages bidirectionally
- [ ] WebSocket reconnects automatically after daemon restart
- [ ] Frontend state updates in real-time via WebSocket (no polling)
- [ ] Admin-only routes reject non-admin users with 403
- [ ] Session ownership enforced on delete endpoint
- [ ] `web-api-facade` route map updated to reflect completed proxy surface

## Constraints

- Daemon process must stay running for web to function (this is by design, not a bug)
- Daemon TCP port 8420 must remain bound to 127.0.0.1 (no external exposure)
- Two SQLite databases remain separate: `teleclaude.db` (daemon) and `teleclaude-web.db` (NextAuth)
- WebSocket proxy must use TCP (WS over Unix socket is non-standard in Node.js)

## Risks

1. **WebSocket bridging complexity** (High) -- Daemon WS uses subscription-based protocol with interest tracking. Bridge must faithfully relay subscription state. Mitigation: transparent pass-through; daemon handles all subscription logic.
2. **Daemon restart during active WS connections** (Medium) -- Browser clients lose stream. Mitigation: frontend auto-reconnect with subscription replay.
3. **Auth token leakage** (Medium) -- Identity headers spoofable if daemon TCP is exposed. Mitigation: daemon binds to localhost; add daemon-side header source validation.
4. **Feature drift** (Low) -- New daemon endpoints may not get corresponding Next.js routes. Mitigation: update route map in `web-api-facade` doc as part of each todo.

## Dependencies

- **web-interface-3** (delivered) -- chat interface and streaming
- **web-interface-2** (delivered) -- Next.js scaffold, auth, base proxy infrastructure
- **web-interface-1** (delivered) -- daemon SSE endpoint and transcript converter

## Technology

- Next.js 15 App Router API routes (existing)
- `ws` package for server-side WebSocket in Next.js route handler
- `@tanstack/react-query` for frontend data fetching and cache management
- Existing `daemonRequest()` / `daemonStream()` from `frontend/lib/proxy/daemon-client.ts`
- Existing `buildIdentityHeaders()` from `frontend/lib/proxy/identity-headers.ts`
