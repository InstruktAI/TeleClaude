# Review Findings: tui-footer-clickable-agents

## Review Round: 1

## Paradigm-Fit Assessment

- **Data flow**: Correct. TUI calls API client, API server calls db methods. No direct db imports from TUI. ✓
- **Component reuse**: StatusBar extended in-place rather than duplicated. `SettingsChanged` message pattern reused consistently with other toggles. ✓
- **Pattern consistency**: Click handling follows the established region-tracking pattern from the right-side toggles. ✓

One paradigm violation found: dict-to-DTO conversion is copy-pasted (see Important #3 below).

## Requirements Trace

| Success Criterion                       | Implemented | Evidence                                                          |
| --------------------------------------- | ----------- | ----------------------------------------------------------------- |
| Click available → degraded (1h)         | Yes         | `app.py:596-597`, `api_server.py:1027-1029`                       |
| Click degraded → unavailable (1h)       | Yes         | `app.py:598-599`, `api_server.py:1030-1033`                       |
| Click unavailable → available           | Yes         | `app.py:600-601`, `api_server.py:1024-1025`                       |
| Round-trips through API (not direct db) | Yes         | `app.py:606` calls `self.api.set_agent_status`                    |
| Immediate visual update                 | Yes         | `app.py:609-610` updates dict and calls `refresh()`               |
| All three agents independent            | Yes         | `status_bar.py:129` iterates all three, regions tracked per-agent |

## Critical

### 1. `mark_agent_unavailable` doesn't clear `degraded_until` — premature availability reset

**File:** `teleclaude/core/db.py:1153-1168`

When the TUI cycles degraded→unavailable, `mark_agent_unavailable` sets `available=0, unavailable_until=T2, reason="manual"` but leaves `degraded_until=T1` from the previous degraded state. Since `clear_expired_agent_availability` uses an OR clause (`unavailable_until expired OR degraded_until expired`), when T1 expires before T2, the agent is prematurely reset to available even though `unavailable_until` hasn't expired yet.

**Scenario:** User clicks claude available→degraded at 10:00 (degraded_until=11:00), then clicks degraded→unavailable at 10:01 (unavailable_until=11:01). At 11:00:01, the periodic job fires: `degraded_until < now` is true, OR matches, agent is reset to available — but `unavailable_until` still has ~1 minute left.

**Fix:** Add `row.degraded_until = None` in both branches of `mark_agent_unavailable`, mirroring how `mark_agent_available` already clears it.

## Important

### 2. `get_agent_availability` doesn't check `degraded_until` expiry inline

**File:** `teleclaude/core/db.py:1107-1135`

The method auto-clears expired `unavailable_until` on fetch (lines 1108-1122) but doesn't do the same for `degraded_until`. A degraded agent past its timer will still report as degraded until the periodic `clear_expired_agent_availability` job runs. This creates an inconsistency: unavailable agents get real-time expiry, degraded agents don't.

**Fix:** Add an analogous inline expiry check for `degraded_until` after the `unavailable_until` check block.

### 3. Duplicated dict-to-DTO conversion in api_server.py

**File:** `teleclaude/api_server.py:990-1002` (GET handler), `teleclaude/api_server.py:1037-1050` (POST handler)

The conversion from db info dict to `AgentAvailabilityDTO` is copy-pasted identically in both handlers. This is a paradigm-fit violation — the same 8-line block appears twice and will diverge if either is updated independently.

**Fix:** Extract a helper like `_build_agent_dto(agent: str, info: dict) -> AgentAvailabilityDTO` and call it from both endpoints.

### 4. Missing API endpoint tests

**Ref:** Implementation plan Task 4.1

The plan explicitly calls for "Add or update tests for the API endpoint" but no test exists for `POST /agents/{agent}/status`. The endpoint includes status routing, duration computation, and error handling — all untested.

### 5. Missing status cycle logic tests

**Ref:** Implementation plan Task 4.1

The plan explicitly calls for "Add or update tests for the status cycle logic" but no test exists for the available→degraded→unavailable→available cycle in `app.py:586-612`. The cycle logic (including the fallback to "degraded" when no current info exists) is untested.

## Suggestions

### 6. Consider `@work` decorator for async API call in settings handler

`app.py:578` — `on_settings_changed` is async but doesn't use `@work`. The API call at line 606 could briefly block the event loop. However, this is consistent with how other keys in the same handler work (`run_job` at line 616 also makes an API call without `@work`), so this is a style observation, not a required change.

## Manual Verification Evidence

This review was conducted as a code review only. The TUI is a user-facing interactive widget that requires manual testing (clicking agent pills, observing visual state changes). Manual verification was not performed in this review environment. The click-handling logic and region tracking appear correct from code inspection but should be manually validated before delivery.

## Verdict: REQUEST CHANGES

**Critical: 1** | **Important: 4** | **Suggestions: 1**

The critical bug (#1) can cause premature availability resets in the degraded→unavailable transition path. The missing tests (#4, #5) leave the new API endpoint and cycle logic unverified. These must be addressed before approval.

---

## Fixes Applied

### Critical #1: Clear degraded_until when marking agent unavailable

**Fix:** Added `row.degraded_until = None` to both branches (new row and existing row) in `mark_agent_unavailable`, mirroring the field-clearing pattern in `mark_agent_available`.
**Commit:** d785fcdc
**Verification:** Tests passing, lint passing

### Important #2: Add inline expiry check for degraded_until

**Fix:** Added inline expiry check for `degraded_until` in `get_agent_availability`, matching the existing behavior for `unavailable_until`. When `degraded_until` has expired, it's now cleared immediately on fetch rather than waiting for the periodic cleanup job.
**Commit:** 46517b91
**Verification:** Tests passing, lint passing

### Important #3: Extract dict-to-DTO conversion helper

**Fix:** Created `_build_agent_dto(agent, info)` helper function and replaced the duplicated 8-line conversion blocks in both GET and POST endpoints with calls to this helper.
**Commit:** bf2515ce
**Verification:** Tests passing, lint passing, guardrails passing (typed dict signature matches db return type)

### Important #4: Add API endpoint tests

**Fix:** Added comprehensive tests for POST `/agents/{agent}/status` endpoint covering:

- Setting agent to available status
- Setting agent to degraded status with custom duration
- Setting agent to unavailable status
- Duration computation verification
- Error handling (500 on DB exception)
  **Commit:** 91b26caa
  **Verification:** All new tests passing

### Important #5: Add status cycle logic tests

**Fix:** Created new test file `test_tui_agent_status_cycle.py` with comprehensive coverage:

- available→degraded cycle
- degraded→unavailable cycle
- unavailable→available cycle
- No current info defaults to degraded (fallback behavior)
- API error triggers error notification
  **Commit:** 91b26caa
  **Verification:** All new tests passing (5 tests, all green)

All findings (Critical and Important) have been addressed with commits and verification. Ready for re-review.
