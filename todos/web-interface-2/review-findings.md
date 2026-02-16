# Review Findings: web-interface-2

**Review round:** 2
**Reviewer:** Claude (Opus 4.6)
**Date:** 2026-02-16
**Verdict:** REQUEST CHANGES

---

## Round 1 Fix Verification

| Finding                           | Status         | Notes                                                        |
| --------------------------------- | -------------- | ------------------------------------------------------------ |
| C1: Chat route buffering          | Resolved       | `daemonStream` now used, stream relayed correctly            |
| C2: Middleware blocks /api/people | **Incomplete** | Middleware fixed, but route handler still blocks (see R2-C1) |
| C3: Session body injection        | Resolved       | Field allowlist implemented                                  |
| I1: Email expiry mismatch         | Resolved       | Both text and HTML say "3 minutes"                           |
| I2: daemonStream dead code        | Resolved       | Now used by chat route                                       |
| I3: Redundant SessionWithRole     | Resolved       | Removed, uses `session.user.role` directly                   |
| I4: loadConfig crash handling     | Resolved       | Try-catch with ENOENT/EACCES/parse errors                    |
| I5: Broad catch blocks            | Resolved       | JSON parse (400) separated from daemon errors (503)          |
| I6: Cast in identity-headers      | Resolved       | Simplified to `if (session.user.role)`                       |

---

## Critical

### R2-C1: People route auth check still blocks login flow (C2 fix incomplete)

`frontend/app/api/people/route.ts:6-8` still calls `auth()` and returns 401 when there is no session. The C2 fix (commit 8c0bd253) correctly added `/api/people` to the middleware matcher exclusion, but the route handler itself was not modified. The request now reaches the handler instead of being redirected, but the handler rejects it with 401.

**Trace:**

1. Unauthenticated user loads `/login`
2. Login page fetches `/api/people` (line 27 of `login/page.tsx`)
3. Middleware: passes through (excluded from matcher) -- OK
4. Route handler: `auth()` returns null -> returns `{ error: "Unauthorized" }` with status 401
5. Login page: `r.ok` is false for 401 -> returns `[]`
6. Login page: dropdown renders empty -> login impossible

**Evidence:** `git diff 97f47382..HEAD -- frontend/app/api/people/route.ts` shows no changes to this file.

**Fix:** Remove the auth check from the people GET handler. The people list contains names/emails/roles from the config file and is needed for the pre-auth login flow. The middleware exclusion was correct intent; the route handler needs to match.

---

## Important

### R2-I1: Sessions POST uses stale role resolution pattern (I6 inconsistency)

`frontend/app/api/sessions/route.ts:70-71` uses `"role" in session.user ? (session.user.role as string) : undefined`. This is the exact pattern removed from `identity-headers.ts` in the I6 fix (commit e6f2a576). The type augmentation at `types/next-auth.d.ts:10` types `role` as `string | undefined`, making both the `"role" in` check and `as string` cast unnecessary.

**Fix:** Replace with `human_role: session.user.role,`

---

## Suggestions

### R2-S1: Login page should surface people-fetch errors to the user

`frontend/app/(auth)/login/page.tsx:27-33` catches all errors from `/api/people` and falls back to an empty array with no user feedback. When the people list fails (config missing, daemon down, or the auth issue above), the user sees an empty dropdown with no explanation. Consider setting the `error` state with a message like "Failed to load people list" so the user knows something is wrong.

### R2-S2: Pages Router `_error.tsx` still present

`frontend/pages/_error.tsx` is a Pages Router artifact. With App Router, `app/not-found.tsx` and error boundaries are the canonical approach. Carryover from round 1 S3.

---

## Requirements Traceability (Round 2)

| Requirement                           | Status   | Notes                                                        |
| ------------------------------------- | -------- | ------------------------------------------------------------ |
| FR1: assistant-ui scaffold            | Pass     | Layout, runtime provider, thread UI present                  |
| FR2: Next.js API as public entrypoint | Pass     | All routes implemented, browser calls Next.js only           |
| FR3: Streaming passthrough            | Pass     | Chat route now uses `daemonStream`, stream relayed correctly |
| FR4: Identity boundary                | Pass     | Headers correct, allowlist on session creation               |
| FR5: Route map                        | Pass     | `route-map.md` complete and accurate                         |
| NFR1: No daemon URL exposure          | Pass     | Socket path server-side only                                 |
| NFR2: Proxy latency measurable        | Pass     | Request ID + timing in proxy logs                            |
| NFR3: No secret leakage in logs       | Pass     | Allowlist headers, no tokens logged                          |
| NFR4: Daemon API compatibility        | Pass     | Path mapping matches daemon endpoints                        |
| Login flow functional                 | **Fail** | People route auth check blocks login (R2-C1)                 |

---

## Verdict: REQUEST CHANGES

1 critical issue blocks approval: the people route auth check makes login non-functional (R2-C1). The C2 middleware fix was correct in intent but incomplete in execution. The route handler must also allow unauthenticated access.

1 important issue (R2-I1) is a consistency cleanup from the I6 fix that was not applied to all locations.

---

## Fixes Applied (Round 2)

| Finding | Fix                                               | Commit   | Verification |
| ------- | ------------------------------------------------- | -------- | ------------ |
| R2-C1   | Removed auth check from people route              | 60d3c64a | Hooks passed |
| R2-I1   | Simplified role resolution to `session.user.role` | e44ebd3e | Hooks passed |

**Status:** All Critical and Important issues addressed. Ready for re-review.

---

## Round 1 History

<details>
<summary>Round 1 findings and fixes (click to expand)</summary>

### Round 1 Findings (Original)

**Critical:** C1 (streaming), C2 (middleware), C3 (body injection)
**Important:** I1 (email expiry), I2 (dead code), I3 (SessionWithRole), I4 (config crash), I5 (catch blocks), I6 (cast)
**Suggestions:** S1 (login error handling), S2 (no tests), S3 (Pages Router error)

### Fixes Applied

| Finding | Commit                       | Status                                 |
| ------- | ---------------------------- | -------------------------------------- |
| C1      | db56db7a                     | Resolved                               |
| C2      | 8c0bd253                     | Incomplete (route handler not updated) |
| C3      | 27df916a                     | Resolved                               |
| I1      | 3acaddc5                     | Resolved                               |
| I2      | (via C1)                     | Resolved                               |
| I3      | 59333aeb                     | Resolved                               |
| I4      | aff0c715                     | Resolved                               |
| I5      | db56db7a, 27df916a, 7958a764 | Resolved                               |
| I6      | e6f2a576                     | Resolved                               |

</details>
