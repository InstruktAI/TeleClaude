# Review Findings: web-interface-4 (Round 2)

**Reviewer:** Claude (automated)
**Date:** 2026-02-18
**Scope:** Re-review of round 1 fixes — 11 commits since baseline `6b764b55`
**Verdict:** REQUEST CHANGES

---

## Round 1 Fix Verification

All 11 round 1 findings (C1, C2, I1–I9) were addressed with commits. 10 of 11 fixes are correct. C2 fix introduced a regression (see C1 below).

| Round 1                                     | Status         | Notes                                                              |
| ------------------------------------------- | -------------- | ------------------------------------------------------------------ |
| C1: visibility not mapped                   | Fixed          | `core.models.Session.visibility` added, `_to_core_session` maps it |
| C2: POST proxy drops fields                 | **Regression** | Fields forwarded, but field name wrong — see C1 below              |
| I1: /keys, /voice, /file lack access checks | Fixed          | `check_session_access` added to all three                          |
| I2: WS sessions_initial skips filtering     | Fixed          | Inline role filter in `_send_initial_state`                        |
| I3: handleEndSession swallows errors        | Fixed          | `endError` state with UI feedback                                  |
| I4: No cache invalidation after delete      | Fixed          | `invalidateQueries` before router push                             |
| I5: fetchSessions duplicated                | Fixed          | Extracted to `frontend/lib/api/sessions.ts`                        |
| I6: Fetch effects lack AbortController      | Fixed          | Both useEffects have abort cleanup                                 |
| I7: Projects loading forever on error       | Fixed          | `projectsLoading`/`projectsError` states                           |
| I8: No tests for session access             | Fixed          | 9 tests in `test_session_access.py`                                |
| I9: SessionPicker dead code                 | Fixed          | File deleted                                                       |

---

## Critical

### C1: POST proxy sends `initial_message` — daemon expects `message`

**File:** `frontend/app/api/sessions/route.ts:72`

The C2 fix correctly destructures `message` from the dialog body (line 60) but sends it as `initial_message` to the daemon (line 72). The daemon's `CreateSessionRequest` model (`teleclaude/api_models.py:22`) has field `message`, not `initial_message`. Pydantic v2 default extra handling silently ignores unrecognized fields, so `message` stays `None`.

**Impact:** When `launch_kind` is `agent_then_message`, the daemon validates `message is not None` and returns HTTP 400. Session creation with an initial message is broken.

**Fix:** Change line 72 from `initial_message: message` to `message`.

---

## Suggestions (carried forward)

These non-blocking suggestions from round 1 remain unaddressed. No action required for approval.

### S1: Admin bypasses session-existence check on delete

**File:** `teleclaude/api/session_access.py:37-39`

When `role == "admin"` and `require_owner=True`, the function returns immediately without verifying the session exists. DELETE of a nonexistent session produces a 500 from the command layer rather than a clean 404.

### S2: Unstable array reference in dashboard query key

**File:** `frontend/app/dashboard/page.tsx:45`

`queryKey: ["dashboard-projects", computers?.map((c) => c.name)]` creates a new array each render. Use a joined string (e.g., `computers?.map(c => c.name).join(",")`) for referential stability.

### S3: Lazy imports of `check_session_access` in 7 endpoint functions

**Files:** `teleclaude/api_server.py:544,568,592,619,649,751`, `teleclaude/api/streaming.py:245`

No circular dependency risk exists. Move to top-level import for clarity.

### S4: No focus trap for mobile sidebar drawer

**File:** `frontend/components/sidebar/Sidebar.tsx:35-41`

Mobile overlay lacks keyboard focus trapping. Screen reader and keyboard users can interact with content behind the drawer.

---

## Fixes Applied (Round 2)

| Issue                                                             | Fix                                                                                        | Commit   |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------ | -------- |
| C1: POST proxy sends `initial_message` — daemon expects `message` | Changed `initial_message: message` to `message` in `frontend/app/api/sessions/route.ts:72` | cb391d49 |

---

**Tests:** 9 new tests PASSING. Existing suite unaffected.
**Lint:** PASSING.
