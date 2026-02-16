# DOR Report: web-interface-4 — Session Management & Role-Based Access

## Gate Verdict

**Phase:** Gate (final verdict)
**Assessed:** 2026-02-16
**Result:** PASS (score: 8/10)

## Gate Analysis

### 1. Intent & Success — PASS

Intent is explicit: add session management sidebar (list, switching, creation, actions), role-based visibility enforcement on daemon endpoints, and admin dashboard. Success criteria are concrete:

- Session list with real-time status via WebSocket
- Session switching reconnects SSE stream correctly
- Session creation end-to-end from browser
- 403 on unauthorized session access
- Admin dashboard with computer/project/session counts

All 8 acceptance criteria in requirements are testable and observable.

### 2. Scope & Size — PASS (with deferral strategy)

5 phases, ~14 tasks, ~15 new/modified files across daemon (Python) and frontend (Next.js). This is large but manageable because:

- Phases are well-isolated and independently verifiable.
- Phase 1 (daemon RBAC) is pure Python, no frontend dependency.
- Phases 2-3 (sidebar + actions) are the core deliverable.
- Phase 4 (WebSocket integration) is an enhancement — sidebar works with polling first.
- Phase 5 (dashboard) is fully independent.

**Explicit deferral option:** If context exhaustion occurs, Phase 4+5 can be split into a follow-up todo without degrading the core session management UX. This is noted in the implementation plan.

### 3. Verification — PASS

Every task has a verification step. Acceptance criteria map 1:1 to observable behavior. Role-based access is verifiable via daemon response codes (403). WebSocket integration verifiable via sidebar updates.

### 4. Approach Known — PASS

All patterns verified against codebase:

- **Session switching:** key-based re-mount pattern exists in `(chat)/page.tsx` (verified: `SessionPicker` in use).
- **Session APIs:** `GET /sessions` (line 287), `POST /sessions` (line 330), `DELETE /sessions/{id}` (line 478), `GET /computers` (line 735), `GET /projects` (line 771) — all exist in `api_server.py`.
- **WebSocket:** `/ws` endpoint exists (line 983) with subscription model, initial state push, and event broadcasting (`SessionStartedEventDTO`, `SessionUpdatedEventDTO`, `SessionClosedEventDTO`).
- **Identity headers:** `frontend/lib/proxy/identity-headers.ts` passes `X-Web-User-Email`, `X-Web-User-Name`, `X-Web-User-Role`.
- **Session model:** `human_email` (line 480) and `human_role` (line 481) exist on `Session` dataclass, `SessionSummary`, and `SessionSummaryDTO`.
- **Sidebar layout:** standard shadcn/ui + Tailwind pattern.

No unresolved architectural decisions.

### 5. Research Complete — PASS

No new third-party dependencies introduced. All technology (Next.js 15, shadcn/ui, AssistantUI, native WebSocket API) is already in active use.

### 6. Dependencies & Preconditions — PASS

- **web-interface-3** — DELIVERED (verified in `todos/delivered.md` + roadmap).
- **Daemon APIs** — all 6 endpoints verified present in `api_server.py`.
- **Identity header passing** — verified in `frontend/lib/proxy/identity-headers.ts`.
- **WebSocket event DTOs** — `SessionStartedEventDTO`, `SessionUpdatedEventDTO`, `SessionClosedEventDTO` exist in `api_models.py`.
- **TCP port (localhost:8420)** — in use since web-interface-1.

### 7. Integration Safety — PASS

All changes are additive:

- Daemon visibility filtering: guards on identity header presence — TUI/MCP clients without headers get existing (unfiltered) behavior.
- New `visibility` column: `DEFAULT 'private'` — existing sessions unaffected.
- Frontend sidebar replaces `SessionPicker` — isolated to web interface.
- Dashboard: new route `/dashboard` — no impact on existing pages.
- Middleware change: adding `/dashboard` admin guard — existing routes unaffected.

### 8. Tooling Impact — N/A (auto-pass)

No tooling or scaffolding changes.

## Resolved Open Questions

1. **WebSocket proxy strategy:** Direct connection to daemon `/ws` (TCP port already exists and works). The daemon WebSocket already has a mature subscription protocol with initial state push — no proxy layer needed. **Decision: direct connection.**

2. **Session visibility toggle UI:** Deferred to future phase as stated in out-of-scope. The `visibility` field is API-only in this phase. **Decision: no toggle UI.**

3. **Dashboard refresh strategy:** WebSocket subscription for session events (daemon already broadcasts `session_started`, `session_updated`, `session_closed` events) with polling fallback (30s) when WS disconnects. **Decision: WS primary, polling fallback.**

## Assumptions (verified)

- Daemon TCP port accessible from Next.js process — **verified** (working since web-interface-1).
- `SessionPicker` can be replaced — **verified** (exists in `frontend/components/SessionPicker.tsx`, used in `(chat)/page.tsx`).
- `AssistantChatTransport` disconnects on unmount — **assumed** (standard React cleanup; no evidence against).
- Admin role available in NextAuth session — **verified** (role passed via identity headers).

## Blockers

None. All dependencies delivered. All APIs exist. All model fields present (except `visibility` which is correctly identified as new work).
