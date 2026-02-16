# Requirements: Web Interface Phase 4 — Session Management & Role-Based Access

## Goal

Add session management sidebar, session switching, new session creation, session actions, role-based visibility routing, and an admin dashboard to the TeleClaude web interface.

## Problem Statement

Phase 3 delivered a working chat interface with AssistantUI streaming. However, the `SessionPicker` is a basic inline list navigating via URL query params. There is no persistent sidebar, no session creation UI, no way to end sessions from the browser, no visibility enforcement, and no admin overview. Users must know session IDs to interact, and all sessions are visible to all authenticated users regardless of role.

## Scope

### In scope

**Session management UI:**

1. **Sidebar layout** — persistent left sidebar with session list and main chat area. Responsive: collapsible on small screens.
2. **Session list** — active sessions with title, agent icon (claude/gemini/codex), last activity timestamp, status badge (running/idle/stopped). Sorted by last activity.
3. **Session switching** — click a session to change which session the SSE stream follows. The `AssistantChatTransport` re-mounts with the new `sessionId`.
4. **New session creation** — dialog/form with: computer selector (from `GET /computers`), project selector (from `GET /projects?computer=X`), agent picker (claude/gemini/codex), thinking mode (fast/med/slow), optional title, optional initial message.
5. **Session actions** — end session button (calls `DELETE /sessions/{id}?computer=X`). Confirmation dialog before ending.

**Role-based visibility:**

6. **Frontend session filtering** — filter session list by role: admin sees all sessions, members see own + shared, others see only own.
7. **Backend enforcement** — daemon SSE endpoint and session list endpoint enforce visibility based on `human_email`/`human_role` from identity headers. Returns 403 for unauthorized session access.
8. **Session visibility field** — sessions have a `visibility` property (`private` | `shared`). Default: `private`. Admin can toggle to `shared`.

**Admin dashboard:**

9. **Dashboard page** — route `/dashboard`, admin-only. Shows: computers with status, projects per computer with active session counts, total active sessions.
10. **Computer status cards** — name, role (local/remote), online/offline, active session count.
11. **Project summary** — project name, path, active session count per computer.

**Real-time updates:**

12. **WebSocket integration** — connect to daemon `/ws` for session status updates. Update sidebar session list in real-time (new sessions, status changes, session endings).

### Out of scope

- Session sharing UI (marking sessions as shared) — future phase.
- Session history/archive browsing.
- Session transcript export.
- Memory search from dashboard.
- Security event log in dashboard.
- Per-session access control lists.
- Mobile-optimized layout.

## Functional Requirements

### FR1: Sidebar layout

- Persistent sidebar on the left (240-280px width).
- Session list in sidebar, chat area in main content.
- Sidebar shows: session list header, "New Session" button, session entries.
- Collapsible via hamburger icon on screens < 768px.
- Selected session highlighted in sidebar.

### FR2: Session list

- Each entry shows: title (truncated), agent icon, last activity relative time, status badge.
- Sorted by `last_activity` descending (most recent first).
- Status badges: green dot (running), yellow dot (idle), gray dot (stopped).
- Agent icons: distinct icon or color per agent type (claude, gemini, codex).
- Empty state: "No active sessions" with prompt to create one.
- Loading state: skeleton entries during fetch.

### FR3: Session switching

- Click session entry → update URL to `/?sessionId={id}`.
- Chat component re-mounts with new session ID (existing key-based pattern).
- Previous SSE stream disconnects, new stream connects.
- Switching preserves sidebar scroll position.

### FR4: New session creation

- "New Session" button in sidebar header opens a dialog/sheet.
- Step 1: Select computer (dropdown from `GET /computers`, default: local).
- Step 2: Select project (dropdown from `GET /projects?computer=X`, shows project name + path).
- Step 3: Select agent (radio group: claude/gemini/codex, default: claude).
- Step 4: Select thinking mode (radio group: fast/med/slow, default: med).
- Step 5: Optional title input (auto-generated if empty).
- Step 6: Optional initial message textarea.
- Submit: `POST /api/sessions` → on success, navigate to new session.
- Error handling: show error toast on failure.

### FR5: Session actions

- End session: button in session header (chat area) or context menu in sidebar.
- Confirmation dialog: "End session {title}? This cannot be undone."
- On confirm: `DELETE /sessions/{id}?computer=X`.
- On success: remove from sidebar, navigate to next available session or empty state.

### FR6: Role-based session filtering

- **Admin** (`role === "admin"`): sees all sessions across all users.
- **Member** (`role === "member"`): sees own sessions + sessions marked `shared`.
- **Contributor/Newcomer**: sees only own sessions.
- Filtering happens server-side: daemon `GET /sessions` respects identity headers and returns only visible sessions.
- Frontend does not do client-side filtering — it trusts the API response.

### FR7: Backend visibility enforcement

- Daemon `GET /sessions` filters by `human_email` + `human_role`:
  - If `human_role == "admin"`: return all sessions.
  - If `human_role == "member"`: return sessions where `human_email == requester` OR `visibility == "shared"`.
  - Otherwise: return sessions where `human_email == requester` only.
- Daemon `POST /api/chat/stream` checks: does requester have access to this session? 403 if not.
- Daemon `DELETE /sessions/{id}` checks: is requester the owner or admin? 403 if not.
- Daemon `POST /sessions/{id}/message` checks: does requester have access? 403 if not.

### FR8: Admin dashboard

- Route: `/dashboard`.
- Protected: redirects non-admin to `/`.
- Layout: grid of computer cards, each showing projects and session counts.
- Data source: `GET /computers` + `GET /sessions` (admin sees all).
- Computer cards: name, status (online/offline from cache), session count.
- Project rows within each computer: name, active session count.
- Refresh: auto-refresh via WebSocket session updates or polling fallback (30s).

### FR9: WebSocket session updates

- Connect to daemon `/ws` on app mount.
- Subscribe to session updates: new sessions, status changes, endings.
- Update sidebar session list in real-time without full refetch.
- Reconnect on disconnect with exponential backoff.
- Fallback: if WS unavailable, poll `GET /sessions` every 15s.

## Non-functional Requirements

1. Sidebar renders within 200ms of page load.
2. Session switching completes (new stream connected) within 500ms.
3. WebSocket reconnection within 5s of disconnect.
4. Dashboard data loads within 1s.

## Acceptance Criteria

1. Session list sidebar shows real-time status updates via WebSocket.
2. Switching sessions reconnects SSE stream correctly (no stale data).
3. New session creation works end-to-end from browser (computer → project → agent → create).
4. Ending a session from browser removes it from sidebar and updates UI.
5. Non-admin cannot see sessions they don't own (verified via API 403).
6. Admin sees all sessions in sidebar and dashboard.
7. Dashboard shows accurate computer/project/session counts.
8. Session creation dialog validates required fields before submission.

## Dependencies

- **web-interface-3** (DELIVERED) — chat interface and part rendering.
- **Daemon API** — `GET /sessions`, `POST /sessions`, `DELETE /sessions/{id}`, `GET /computers`, `GET /projects`, `/ws` WebSocket — all exist.
- **Identity headers** — `X-Web-User-Email`, `X-Web-User-Name`, `X-Web-User-Role` — already passed by proxy layer.

## Technology

- Existing: Next.js 15, shadcn/ui, Tailwind, AssistantUI, Drizzle.
- New: `Sheet` or `Sidebar` component from shadcn/ui for sidebar layout.
- New: WebSocket client (native browser `WebSocket` or lightweight wrapper).
