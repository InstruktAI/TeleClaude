# Implementation Plan: Web Interface Phase 4 — Session Management & Role-Based Access

## Objective

Add session management sidebar with switching, creation, and actions. Enforce role-based visibility on daemon endpoints. Build admin dashboard.

## Architecture

```
Sidebar (persistent)          Main Area
┌──────────────────┐     ┌────────────────────────────┐
│ [+ New Session]  │     │ Session Header (title,      │
│                  │     │   agent, status, [End])     │
│ ● Session A  2m  │     │                            │
│   Session B  1h  │ ──→ │ Chat Stream (AssistantUI)  │
│   Session C  3h  │     │                            │
│                  │     │ Composer                    │
└──────────────────┘     └────────────────────────────┘
```

## Phase 1: Daemon visibility enforcement

- [x] ### Task 1.1: Session visibility filtering on GET /sessions

**File:** `teleclaude/api_server.py`

Add role-based filtering to the `GET /sessions` endpoint:

- Read `X-Web-User-Email` and `X-Web-User-Role` headers.
- If no identity headers present (TUI/MCP client): return all (existing behavior).
- If `role == "admin"`: return all sessions.
- If `role == "member"`: return own sessions + sessions with `visibility == "shared"`.
- Otherwise: return only sessions where `human_email` matches requester.

Filter is applied after the existing session merge logic (local + remote cache).

**Verification:** Admin user sees all sessions; member sees only own; contributor sees only own.

- [x] ### Task 1.2: Access check on session-scoped endpoints

**File:** `teleclaude/api_server.py`

Add a shared `_check_session_access(session_id, email, role)` helper:

- Loads session metadata.
- Returns `True` if: requester is owner, requester is admin, or session is shared + requester is member.
- Returns `False` otherwise.

Apply to:

- `POST /api/chat/stream` → 403 if no access.
- `POST /sessions/{id}/message` → 403 if no access.
- `DELETE /sessions/{id}` → 403 if not owner and not admin.
- `GET /sessions/{id}/messages` → 403 if no access.

**Verification:** Non-owner gets 403 on stream, message send, and delete.

- [x] ### Task 1.3: Visibility field on session model

**File:** `teleclaude/core/models.py`, `teleclaude/db/helpers.py`

- Add `visibility` column to sessions table: `TEXT DEFAULT 'private'`, values: `private`, `shared`.
- Add `visibility` to `SessionSummaryDTO`.
- Migration: add column with default.

**Verification:** New sessions default to `private`. Field appears in API response.

## Phase 2: Sidebar layout

- [x] ### Task 2.1: Layout restructure

**Files:**

- `frontend/app/(chat)/layout.tsx` (new)
- `frontend/components/Sidebar.tsx` (new)
- `frontend/app/(chat)/page.tsx` (modify)

Create a layout with persistent sidebar:

```tsx
// (chat)/layout.tsx
export default function ChatLayout({ children }) {
  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex-1">{children}</main>
    </div>
  );
}
```

Remove `SessionPicker` from page.tsx — its functionality moves into the sidebar.

**Verification:** Sidebar visible on all chat pages. Main area fills remaining width.

- [x] ### Task 2.2: Session list component

**File:** `frontend/components/SessionList.tsx` (new)

- Fetches `GET /api/sessions` on mount.
- Renders session entries: title, agent icon, relative time, status badge.
- Selected session highlighted (from URL `sessionId` param).
- Click navigates to `/?sessionId={id}`.
- Empty state message.
- Loading skeleton.

Agent icons: use Lucide icons or colored circles:

- claude → purple circle / brain icon
- gemini → blue circle / sparkles icon
- codex → green circle / code icon

Status badges:

- running → green pulsing dot
- idle → yellow dot
- stopped → gray dot

**Verification:** Sessions render with correct metadata. Selection highlights correctly.

- [x] ### Task 2.3: Responsive sidebar

**File:** `frontend/components/Sidebar.tsx`

- Desktop (≥768px): sidebar always visible, 256px width.
- Mobile (<768px): sidebar hidden by default, toggled via hamburger button in header.
- Use shadcn `Sheet` component for mobile overlay.

**Verification:** Sidebar collapses on mobile. Toggle works.

## Phase 3: Session switching and actions

- [x] ### Task 3.1: Session switching

**File:** `frontend/app/(chat)/page.tsx` (modify)

Current behavior: `sessionId` from URL params → `Chat` component key. This already works. Ensure:

- Sidebar click updates URL.
- Chat component unmounts and remounts (key change).
- Previous SSE stream disconnects (AssistantUI handles this via unmount).
- New stream connects for selected session.

No new code needed beyond sidebar integration — the existing key-based pattern handles this.

**Verification:** Switching sessions shows correct messages. No stale streams.

- [x] ### Task 3.2: Session header

**File:** `frontend/components/SessionHeader.tsx` (new)

Header bar above chat area showing:

- Session title.
- Agent name + icon.
- Computer name.
- Status badge.
- "End Session" button (right-aligned, destructive variant).

Data source: session metadata from `GET /sessions` (cached from sidebar fetch).

**Verification:** Header shows correct session info. Updates on session switch.

- [x] ### Task 3.3: End session action

**File:** `frontend/components/SessionHeader.tsx`, `frontend/app/api/sessions/[id]/route.ts` (new)

- "End Session" button opens confirmation dialog (shadcn `AlertDialog`).
- On confirm: `DELETE /api/sessions/{id}` (frontend proxy route).
- Frontend proxy: `DELETE /api/sessions/[id]/route.ts` → daemon `DELETE /sessions/{id}?computer=X`.
- On success: remove session from list, navigate to next available or empty state.
- On failure: toast error.

**Verification:** Session ends. Removed from sidebar. Chat area updates.

- [x] ### Task 3.4: New session creation dialog

**Files:**

- `frontend/components/NewSessionDialog.tsx` (new)
- `frontend/app/api/computers/route.ts` (new)
- `frontend/app/api/projects/route.ts` (new)

Dialog flow:

1. Computer dropdown → fetches `GET /api/computers` (proxy to daemon).
2. Project dropdown → fetches `GET /api/projects?computer=X` (proxy to daemon).
3. Agent radio group: claude (default), gemini, codex.
4. Thinking mode radio group: fast, med (default), slow.
5. Title input (optional, placeholder: "Auto-generated").
6. Initial message textarea (optional).
7. Submit → `POST /api/sessions` with all fields.
8. On success → navigate to new session.

New proxy routes:

- `GET /api/computers` → daemon `GET /computers`.
- `GET /api/projects?computer=X` → daemon `GET /projects?computer=X`.

**Verification:** Full creation flow works. New session appears in sidebar.

## Phase 4: WebSocket real-time updates

- [ ] ### Task 4.1: WebSocket client hook

**File:** `frontend/hooks/useWebSocket.ts` (new)

Custom hook that:

- Connects to daemon WebSocket endpoint (via proxy or direct).
- Reconnects on disconnect with exponential backoff (1s, 2s, 4s, max 30s).
- Exposes: `lastMessage`, `isConnected`, `send()`.
- Subscribes to session updates on connect.

WebSocket URL: `ws://localhost:8420/ws` (daemon TCP port) or proxied through Next.js.

**Verification:** Connects, reconnects on drop.

- [ ] ### Task 4.2: Real-time session list updates

**File:** `frontend/components/SessionList.tsx` (modify)

- On WebSocket session event (new/updated/closed): update session list state.
- Event types from daemon: session status changes, new sessions, session endings.
- No full refetch — apply incremental updates.
- Fallback: if WS disconnected, poll `GET /api/sessions` every 15s.

**Verification:** New session creation from TUI/Telegram appears in web sidebar within 2s.

## Phase 5: Admin dashboard

- [ ] ### Task 5.1: Dashboard page

**Files:**

- `frontend/app/dashboard/page.tsx` (new)
- `frontend/app/dashboard/layout.tsx` (new)
- `frontend/components/dashboard/ComputerCard.tsx` (new)
- `frontend/components/dashboard/ProjectRow.tsx` (new)

Route: `/dashboard`. Admin-only (middleware check or page-level redirect).

Layout: grid of computer cards. Each card:

- Computer name, role badge (local/remote).
- Status: online/offline (from `/computers` endpoint).
- Active session count.
- Expand: list of projects with session counts.

Data: combine `GET /api/computers` + `GET /api/sessions` (admin sees all).

**Verification:** Dashboard shows accurate data. Non-admin redirected.

- [ ] ### Task 5.2: Dashboard middleware/guard

**File:** `frontend/middleware.ts` (modify)

Add dashboard route protection:

- `/dashboard` requires `role === "admin"`.
- Redirect non-admin to `/`.

Alternative: page-level check with `redirect()` in server component if simpler.

**Verification:** Non-admin cannot access dashboard.

## Files Expected to Change

**Daemon:**

| File                        | Change                                                                    |
| --------------------------- | ------------------------------------------------------------------------- |
| `teleclaude/api_server.py`  | Visibility filtering on GET /sessions, access checks on session endpoints |
| `teleclaude/core/models.py` | Add `visibility` field to session model                                   |
| `teleclaude/db/helpers.py`  | Add `visibility` column, migration                                        |
| `teleclaude/api_models.py`  | Add `visibility` to `SessionSummaryDTO`                                   |

**Frontend:**

| File                                             | Change                                     |
| ------------------------------------------------ | ------------------------------------------ |
| `frontend/app/(chat)/layout.tsx`                 | New — sidebar + main area layout           |
| `frontend/app/(chat)/page.tsx`                   | Remove SessionPicker, rely on sidebar      |
| `frontend/components/Sidebar.tsx`                | New — persistent sidebar shell             |
| `frontend/components/SessionList.tsx`            | New — session list with status             |
| `frontend/components/SessionHeader.tsx`          | New — session info header                  |
| `frontend/components/NewSessionDialog.tsx`       | New — session creation dialog              |
| `frontend/hooks/useWebSocket.ts`                 | New — WS client hook                       |
| `frontend/app/api/sessions/[id]/route.ts`        | New — delete session proxy                 |
| `frontend/app/api/computers/route.ts`            | New — computers proxy                      |
| `frontend/app/api/projects/route.ts`             | New — projects proxy                       |
| `frontend/app/dashboard/page.tsx`                | New — admin dashboard                      |
| `frontend/app/dashboard/layout.tsx`              | New — dashboard layout                     |
| `frontend/components/dashboard/ComputerCard.tsx` | New — computer status card                 |
| `frontend/components/dashboard/ProjectRow.tsx`   | New — project row                          |
| `frontend/middleware.ts`                         | Add dashboard route protection             |
| `frontend/components/SessionPicker.tsx`          | Remove (replaced by Sidebar + SessionList) |

## Build Sequence

```
Phase 1 (daemon) → Phase 2 (sidebar) → Phase 3 (switching + actions) → Phase 4 (WS) → Phase 5 (dashboard)
```

Phases 2-3 can proceed in parallel with Phase 1 by mocking visibility responses (frontend shows all sessions initially, backend enforcement lands independently).

Phase 4 is an enhancement — sidebar works with polling first, WS adds real-time.

Phase 5 is independent of 2-4 and can be built in parallel.

## Risks

1. **Daemon visibility enforcement** — adding filtering to `GET /sessions` must not break TUI/MCP clients that don't send identity headers. Guard: only apply filtering when headers are present.
2. **WebSocket proxy** — Next.js middleware cannot proxy WebSocket connections directly. Options: (a) frontend connects to daemon WS directly (requires TCP port), (b) use polling fallback. TCP port already exists from Phase 1 delivery.
3. **Session deletion race** — user ends session while SSE stream is active. The stream should detect the session ending and close gracefully.
4. **AssistantUI re-mount** — switching sessions causes full re-mount. Verify no memory leaks from accumulated AssistantUI instances.

## Verification

- Sidebar shows sessions with real-time status.
- Switching sessions reconnects stream correctly.
- New session creation end-to-end from browser.
- End session removes from sidebar.
- Non-admin gets 403 on other users' sessions.
- Admin dashboard shows all computers/projects/sessions.
- WebSocket delivers session updates in real-time.
