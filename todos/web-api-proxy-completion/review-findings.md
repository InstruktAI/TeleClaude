# Review Findings: web-api-proxy-completion

**Review round:** 1
**Verdict:** REQUEST CHANGES

---

## Critical

### C1: Missing ownership enforcement on DELETE and revive routes

**Files:** `frontend/app/api/sessions/[id]/route.ts:7-48`, `frontend/app/api/sessions/[id]/revive/route.ts:6-45`

FR3 requires: "Non-admin users can only end their own sessions" and the implementation plan marks DELETE as "(auth + ownership check)" and revive as "(auth + ownership check)". Both routes authenticate but perform no ownership check — any authenticated user can delete or revive any session.

`requireOwnership()` in `auth-guards.ts` was written for exactly this purpose but is never imported. The routes need to fetch the session metadata from daemon, extract `human_email`, and gate on ownership before forwarding the destructive action.

### C2: `useCacheInvalidation()` never mounted — WS-driven cache invalidation is dead code

**Files:** `frontend/lib/ws/useCacheInvalidation.ts`, `frontend/app/(chat)/layout.tsx`

FR5 / Stream 5 Task 5.3 requires WS events to invalidate React Query caches. The `useCacheInvalidation()` hook is correctly implemented but never called anywhere in the component tree. The chat layout mounts `QueryProvider` and `WebSocketProvider` but no component invokes `useCacheInvalidation()`.

Fix: Create a thin client component that calls the hook and mount it inside the layout (between `WebSocketProvider` and `{children}`).

### C3: WS session cookie name not preserved for production

**File:** `frontend/server.ts:89-101`

`extractSessionToken()` correctly checks both `authjs.session-token` and `__Secure-authjs.session-token`, but `validateSession()` always forwards the token as `authjs.session-token`. In production HTTPS, NextAuth sets the `__Secure-` prefixed cookie. The self-loop fetch to `/api/auth/session` sends the wrong cookie name, causing NextAuth to return an empty session — all WS upgrades fail with 401 in production.

Fix: Track which cookie name was found in `extractSessionToken()` and pass it through to `validateSession()` so the cookie header matches what NextAuth expects.

---

## Important

### I1: `auth-guards.ts` is dead code

**File:** `frontend/lib/proxy/auth-guards.ts`

`requireAdmin()` and `requireOwnership()` are well-implemented but never imported. Routes inline admin checks manually (e.g., `settings/route.ts:48`, `agent-restart/route.ts:15`). This creates logic drift risk — the centralized guards should be used instead of inlining.

### I2: `web-api-facade.md` route map not updated

**File:** `docs/project/design/architecture/web-api-facade.md`

Success criteria require: "web-api-facade route map updated to reflect completed proxy surface." The route map still shows only the original 5 routes. The 10 new routes plus the WS bridge are missing from the Public Contract table.

### I3: Test coverage gaps

**File:** `frontend/lib/__tests__/proxy-routes.test.ts`

- 8 of the new proxy routes have zero test coverage (projects, todos, agents/availability, messages GET/POST, revive, sessions GET/POST)
- Zero WebSocket bridge test coverage (server.ts, ws-bridge.ts)
- Identity headers (`X-Web-User-*`) never asserted on any `daemonRequest` call
- Ownership check untested (follows from C1 — the feature is missing)
- `normalizeUpstreamError` mock diverges from real implementation (uses "Upstream error" vs "Upstream service error")

### I4: WS self-loop session validation lacks timeout

**File:** `frontend/server.ts:97`

The `fetch()` call in `validateSession()` has no timeout. Under load or if the Next.js server is slow to respond, hung upgrade handlers accumulate. Add `signal: AbortSignal.timeout(5000)`.

---

## Suggestions

### S1: `node:url` `parse()` is deprecated

**File:** `frontend/server.ts:14,28,35`

`url.parse()` is deprecated since Node.js 11. Use `new URL(req.url, \`http://\${req.headers.host}\`)` instead.

### S2: Use `requireAdmin()` from auth-guards in settings and agent-restart routes

**Files:** `frontend/app/api/settings/route.ts:48`, `frontend/app/api/sessions/[id]/agent-restart/route.ts:15`

Replace inlined `session.user.role !== "admin"` checks with `requireAdmin(session)` from `auth-guards.ts` to centralize the admin check logic.

---

## Summary

| Severity    | Count |
| ----------- | ----- |
| Critical    | 3     |
| Important   | 4     |
| Suggestions | 2     |

The three critical issues are blockers: missing ownership enforcement (C1) is a security gap where any user can delete any session; dead cache invalidation (C2) means FR5 real-time updates don't work; and the cookie name bug (C3) breaks all WebSocket connections in production. All must be fixed before this can ship.

---

## Fixes Applied

### C1 — Ownership enforcement on DELETE and revive

**Fix:** Both routes now fetch session metadata (`GET /sessions/{id}`) to extract `human_email`, then call `requireOwnership(session, ownerEmail)` before proceeding. Admins bypass the check.
**Commits:** `a9a09a54`
**Tests:** Added owner allowed, non-owner 403, and admin bypass test cases.

### C2 — useCacheInvalidation never mounted

**Fix:** Created `frontend/lib/ws/CacheInvalidation.tsx` (thin client component) and mounted it inside `WebSocketProvider` in the chat layout.
**Commit:** `ec92f018`

### C3 — WS cookie name not preserved for production

**Fix:** `extractSessionToken()` now returns `{ token, cookieName }`. The call site passes `cookieName` through to `validateSession()` which uses it in the cookie header.
**Commit:** `50f38365`

### I1 — auth-guards.ts dead code

**Fix:** Replaced inline `session.user.role !== "admin"` checks in `settings/route.ts` and `agent-restart/route.ts` with `requireAdmin(session)` from `auth-guards.ts`.
**Commit:** `480682b3`

### I2 — web-api-facade.md route map outdated

**Fix:** Updated Public Contract table to include all 15 routes + WS bridge with auth guard annotations.
**Commit:** `d9454b7c`

### I3 — Test coverage gaps (partial)

**Fix:** Fixed `normalizeUpstreamError` mock divergence ("Upstream error" → "Upstream service error"). Added ownership check tests for DELETE route (owner, non-owner, admin bypass).
**Commit:** `a9a09a54`
**Note:** Remaining gaps (projects, todos, agents/availability, messages, revive, sessions GET/POST, WS bridge, identity header assertions) were not addressed in this pass.

### I4 — WS fetch lacks timeout

**Fix:** Added `signal: AbortSignal.timeout(5000)` to the `fetch()` call in `validateSession()`.
**Commit:** `50f38365`

**Tests:** PASSING (200/200)
**Lint:** PASSING
