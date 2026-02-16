# Review Findings: web-interface-2

**Review round:** 1
**Reviewer:** Claude (Opus 4.6)
**Date:** 2026-02-16
**Verdict:** REQUEST CHANGES

---

## Critical

### C1: Chat route buffers entire response instead of streaming (FR3 violation)

`frontend/app/api/chat/route.ts:16` uses `daemonRequest()` which buffers the full response body in memory before returning. FR3 requires: "Streaming responses are relayed without buffering full output." The `daemonStream()` function was built for exactly this purpose but is never called.

**Fix:** Replace `daemonRequest` with `daemonStream` in the chat route and pipe `res.stream` into the `NextResponse`.

### C2: Middleware blocks login page from fetching `/api/people` (login broken)

`frontend/middleware.ts:20-22` matcher excludes only `api/auth`. The login page (`frontend/app/(auth)/login/page.tsx:27`) fetches `/api/people` to populate the person selector. Since the user is unauthenticated at login time, middleware redirects `/api/people` to `/login`, returning HTML instead of JSON. The catch handler silently falls back to an empty array, rendering an empty dropdown. Login is non-functional.

**Fix:** Add `api/people` to the middleware matcher exclusion, or remove the auth check from the people route since it serves the pre-auth login flow.

### C3: Sessions POST allows client to inject trusted identity fields (FR4 weakness)

`frontend/app/api/sessions/route.ts:56-59` spreads `...body` from the client and then overlays `human_email`/`human_role`. Because object spread processes left-to-right, server values do win. However, any other identity-adjacent fields the client injects in the body will pass through unchecked. The architecture design specifies trusted identity via headers, not body injection.

**Fix:** Strip identity-adjacent fields from the client body before spreading, or forward only an explicit allowlist of session-creation fields.

---

## Important

### I1: Email template says "10 minutes" but token expires in 3 minutes

`frontend/lib/identity/email.ts:28,40` says "This code expires in 10 minutes" in both text and HTML. `frontend/auth.ts:33` sets `maxAge: 3 * 60` (3 minutes). Users will be confused when codes expire faster than promised.

**Fix:** Align the email copy with the actual `maxAge` value (either change copy to "3 minutes" or change expiry to 10).

### I2: `daemonStream` is dead code

`frontend/lib/proxy/daemon-client.ts:72-119` defines `daemonStream()` which is never imported or called anywhere. This is the streaming function that should be used by the chat route (see C1).

**Fix:** Wire it into the chat route (resolves both C1 and I2), or delete it if streaming is intentionally deferred.

### I3: Redundant `SessionWithRole` type in auth.ts

`frontend/auth.ts:74-82` defines a local `SessionWithRole` interface and uses `(session as SessionWithRole).user.role` to set the role. `frontend/types/next-auth.d.ts` already augments the `Session` type with `role?: string`. The cast is unnecessary and the local interface duplicates the augmentation.

**Fix:** Remove `SessionWithRole` and use `session.user.role` directly.

### I4: `loadConfig()` in people.ts crashes on missing config file

`frontend/lib/identity/people.ts:20-26` calls `readFileSync` and `parse` with no error handling. If the config file is missing, has wrong permissions, or contains invalid YAML, the entire route crashes with an unhandled exception. This affects both `/api/people` and all auth callbacks that call `findPersonByEmail`.

**Fix:** Wrap in try-catch with meaningful error logging. Either return empty array or throw a domain-specific error that routes can map to an appropriate HTTP status.

### I5: Broad catch blocks conflate JSON parse errors with daemon errors

`frontend/app/api/chat/route.ts:36-41`, `frontend/app/api/sessions/route.ts:71-75`, `frontend/app/api/sessions/[id]/messages/route.ts:37-44` catch both `request.json()` parse errors and daemon connection errors in the same block, returning "Service unavailable" (503) for what may be a client-side bad request (400).

**Fix:** Separate `request.json()` into its own try-catch returning 400, with the daemon call in a second try-catch returning 503.

### I6: `as string` cast in identity-headers.ts

`frontend/lib/proxy/identity-headers.ts:15-16` uses `"role" in session.user && session.user.role` with `as string` cast. Since the module augmentation already types `role` as `string | undefined`, a simple `session.user.role` truthy check suffices.

**Fix:** Replace with `if (session.user.role) { headers["X-Web-User-Role"] = session.user.role; }`.

---

## Suggestions

### S1: Login page silently swallows all fetch errors

`frontend/app/(auth)/login/page.tsx:27-34` catches all errors from `/api/people` and falls back to an empty array with no user-visible feedback. Consider showing an error message when the people list fails to load.

### S2: No frontend-specific tests

No test files exist for the new frontend code. Auth callbacks, proxy logic, identity header building, and people config loading are all untested. Consider adding targeted tests for critical paths before merge.

### S3: `pages/_error.tsx` is redundant with App Router

`frontend/pages/_error.tsx` is a Pages Router error page. With App Router, `frontend/app/not-found.tsx` and error boundaries are the canonical approach. Unless there's a specific reason to keep the Pages Router fallback, consider removing it.

---

## Requirements Traceability

| Requirement                           | Status   | Notes                                                 |
| ------------------------------------- | -------- | ----------------------------------------------------- |
| FR1: assistant-ui scaffold            | Pass     | Layout, runtime provider, thread UI present           |
| FR2: Next.js API as public entrypoint | Pass     | All routes implemented, browser calls Next.js only    |
| FR3: Streaming passthrough            | **Fail** | Chat route buffers (C1)                               |
| FR4: Identity boundary                | Partial  | Headers correct; body injection needs tightening (C3) |
| FR5: Route map                        | Pass     | `route-map.md` complete and accurate                  |
| NFR1: No daemon URL exposure          | Pass     | Socket path server-side only                          |
| NFR2: Proxy latency measurable        | Pass     | Request ID + timing in proxy logs                     |
| NFR3: No secret leakage in logs       | Pass     | Allowlist headers, no tokens logged                   |
| NFR4: Daemon API compatibility        | Pass     | Path mapping matches daemon endpoints                 |

## Test Coverage Assessment

No frontend-specific tests. High regression risk on auth flow, proxy behavior, and streaming. The quality checklist notes `make test` passes but only covers pre-existing backend tests.

---

## Verdict: REQUEST CHANGES

5 critical/important issues must be resolved before approval. C1 (streaming) and C2 (login broken) are the primary blockers.
