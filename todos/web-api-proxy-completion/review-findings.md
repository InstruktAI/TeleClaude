# Review Findings: web-api-proxy-completion

**Review round:** 2
**Verdict:** REQUEST CHANGES

---

## Round 1 Recap

Round 1 found 3 critical, 4 important, and 2 suggestion issues. Fixes were applied for C1–C3, I1–I4 (see commits `a9a09a54`, `ec92f018`, `50f38365`, `480682b3`, `d9454b7c`). Round 2 re-verifies those fixes and evaluates any regressions.

### Round 1 Fix Verification

| Finding                          | Status                        | Notes                                                                                                       |
| -------------------------------- | ----------------------------- | ----------------------------------------------------------------------------------------------------------- |
| C1 (ownership enforcement)       | **Regression** — see C4 below | Fix introduced `GET /sessions/{id}` metadata fetch, but this daemon endpoint does not exist                 |
| C2 (CacheInvalidation unmounted) | **Verified**                  | `CacheInvalidation.tsx` mounted in chat layout (`ec92f018`)                                                 |
| C3 (WS cookie name)              | **Verified**                  | `extractSessionToken()` returns `{ token, cookieName }`, passed through to `validateSession()` (`50f38365`) |
| I1 (auth-guards dead code)       | **Verified**                  | `requireAdmin()` imported in settings and agent-restart routes (`480682b3`)                                 |
| I2 (route map outdated)          | **Verified**                  | `web-api-facade.md` updated with all 15 routes + WS bridge (`d9454b7c`)                                     |
| I3 (test coverage gaps)          | **Partial**                   | Mock divergence fixed, ownership tests added; remaining gaps carried forward as I7                          |
| I4 (WS fetch timeout)            | **Verified**                  | `AbortSignal.timeout(5000)` added (`50f38365`)                                                              |

---

## Critical

### C4: Ownership metadata fetch targets non-existent daemon endpoint

**Files:** `frontend/app/api/sessions/[id]/route.ts:20-24`, `frontend/app/api/sessions/[id]/revive/route.ts:19-23`

The C1 fix introduced a `GET /sessions/${id}` call to fetch session metadata for ownership enforcement. **This endpoint does not exist on the daemon.** The daemon's session routes are:

- `GET /sessions` — list all sessions
- `DELETE /sessions/{session_id}` — end a session
- `POST /sessions/{session_id}/message|keys|voice|file|agent-restart|revive` — actions
- `GET /sessions/{session_id}/messages` — message history

There is no `GET /sessions/{session_id}` single-session fetch. FastAPI returns **405 Method Not Allowed** (the path matches the DELETE route but not GET). The proxy interprets `status >= 400` as failure and returns the error — meaning **both DELETE and revive routes are completely broken for all users**.

**Fix options:**

1. Use `GET /sessions` (list endpoint) and filter by `session_id` client-side — `SessionSummaryDTO` includes `human_email`.
2. Add a `GET /sessions/{session_id}` endpoint to the daemon (out of scope per requirements, but may be the cleaner long-term solution).

### C5: Ownership metadata fetch outside try/catch — unhandled 500 on daemon-down

**Files:** `frontend/app/api/sessions/[id]/route.ts:20-30`, `frontend/app/api/sessions/[id]/revive/route.ts:19-29`

The `daemonRequest()` call for ownership metadata sits **before** the try/catch block. If the daemon is unreachable, `daemonRequest()` throws (confirmed: `daemon-client.ts:57-63` rejects with an Error on connection failure). This produces an unhandled exception → 500 response instead of the expected 503 from `normalizeUpstreamError`.

**Fix:** Move the metadata fetch inside the existing try/catch, or wrap it in its own error handler that returns 503.

---

## Important

### I5: DELETE route missing required `computer` query parameter

**File:** `frontend/app/api/sessions/[id]/route.ts:32-38`

The daemon's `DELETE /sessions/{session_id}` endpoint requires `computer: str = Query(...)` as a mandatory query parameter. The proxy DELETE handler does not forward any query parameters from the incoming request. The daemon will reject the call with 422 Unprocessable Entity.

**Fix:** Forward `request.nextUrl.searchParams` to the daemon request path, or extract and validate `computer` from the incoming query string.

### I6: WS bridge teardown race condition — daemon connection leak

**File:** `frontend/lib/proxy/ws-bridge.ts`

If `connectToDaemon()` is in-flight when the client disconnects and `cleanup()` fires, the pending daemon WebSocket will complete connection after cleanup runs but never be closed. The `daemon.on("open")` handler should check `if (!client.running)` before proceeding with subscription replay, and close the daemon socket if the client has already disconnected.

### I7: Test coverage gaps remain significant

**File:** `frontend/lib/__tests__/proxy-routes.test.ts`

7 of 11 handler variants still have zero test coverage:

- `GET /api/projects` — untested
- `GET /api/todos` — untested
- `GET /api/agents/availability` — untested
- `GET /api/sessions/{id}/messages` — untested
- `POST /api/sessions/{id}/messages` — untested
- `POST /api/sessions/{id}/revive` — untested (ownership flow also untested)
- `GET /api/sessions` — untested

Additionally:

- `extractSessionToken()` in `server.ts` has no unit tests
- Identity headers (`X-Web-User-Email/Name/Role`) are never asserted on any `daemonRequest` mock call
- WS bridge (`ws-bridge.ts`, `server.ts` upgrade handling) has zero test coverage
- Frontend hooks and `CacheInvalidation` component have no tests

---

## Suggestions

### S1 (carry-over): `url.parse()` deprecated in `server.ts`

**File:** `frontend/server.ts:14,28,35`

`url.parse()` is deprecated since Node.js 11. Use `new URL(req.url, \`http://${req.headers.host}\`)` instead.

### S3: WS event `subscribe` types should be `WsEventType[]` not `string[]`

**File:** `frontend/lib/ws/types.ts`

The `subscribe` field accepts `string[]` but events are dispatched by `WsEventType`. Using the union type prevents typos and enables exhaustiveness checking.

### S4: `"preparation_initial"` not handled in cache invalidation switch

**File:** `frontend/lib/ws/useCacheInvalidation.ts`

The WS event type union includes `"preparation_initial"` but the switch statement in `useCacheInvalidation` does not handle it. If emitted by the daemon, the event is silently dropped. Either handle it or add a comment explaining why it's intentionally skipped.

### S5: `role?: string` should be `HumanRole` in next-auth type augmentation

**File:** `frontend/types/next-auth.d.ts`

The `role` field on the session user is typed as `string` but the codebase has a `HumanRole` union type. Using the narrow type ensures compile-time safety for role checks.

---

## Round 2 Fixes Applied

| Finding                                 | Fix                                                                                                                       | Commit     |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- | ---------- |
| C4 (non-existent GET /sessions/{id})    | Switched to `GET /sessions` list + client-side filter by `session_id` in both DELETE and revive routes                    | `2cfbf0a7` |
| C5 (ownership fetch outside try/catch)  | Moved entire metadata fetch + ownership check inside the existing try/catch block                                         | `2cfbf0a7` |
| I5 (missing `computer` param on DELETE) | Extracts `computer` from `request.nextUrl.searchParams` and appends to daemon DELETE path                                 | `2cfbf0a7` |
| I6 (WS bridge teardown race)            | Added `if (!client.running)` guard in `daemon.on("open")` — closes in-flight daemon socket if client already disconnected | `2cfbf0a7` |

---

## Summary

| Severity    | Count | Blocking |
| ----------- | ----- | -------- |
| Critical    | 2     | Yes      |
| Important   | 3     | No\*     |
| Suggestions | 4     | No       |

\* I5 (missing `computer` param) will cause runtime 422 errors on DELETE but is not a security issue. I7 (test gaps) is tracked for awareness.

C4 is the primary blocker: the ownership enforcement added in round 1 targets a daemon endpoint that doesn't exist, making DELETE and revive routes non-functional. C5 compounds this by leaving the fetch unguarded against connection failures. Both must be fixed before this can ship.
