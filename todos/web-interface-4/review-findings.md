# Review Findings: web-interface-4

**Reviewer:** Claude (automated)
**Date:** 2026-02-18
**Scope:** 8 commits, 22 files changed (merge-base..HEAD)
**Verdict:** REQUEST CHANGES

---

## Critical

### C1: `visibility` not mapped through `_to_core_session` — shared-session access always 403

**Files:** `teleclaude/core/db.py:84-127`, `teleclaude/core/models.py:457-501`, `teleclaude/api/session_access.py:54`

`check_session_access` calls `db.get_session(session_id)` which returns a `core.models.Session` dataclass. This dataclass has no `visibility` field. The `getattr(session, "visibility", "private")` fallback in `session_access.py:54` therefore always returns `"private"`, rendering the member-can-see-shared-sessions access model completely non-functional.

The `_filter_sessions_by_role` path (list filtering) works correctly because it reads from `SessionSummary.from_db_session` which accesses `db_models.Session.visibility` directly. The bug is isolated to the per-session access check path.

**Fix:** Add `visibility: Optional[str] = "private"` to `core.models.Session` dataclass and map it in `Db._to_core_session`.

### C2: POST /api/sessions proxy drops 5 of 7 fields from NewSessionDialog

**Files:** `frontend/app/api/sessions/route.ts:60`, `frontend/components/sidebar/NewSessionDialog.tsx:77-85`

The dialog sends `{ computer, project_path, agent, thinking_mode, launch_kind, title, message }`. The proxy destructures only `{ computer, title, initial_message }` and drops the rest. Field name mismatch: dialog sends `message`, proxy reads `initial_message`.

Sessions created from the new dialog will lack project path, agent selection, thinking mode, and initial message. Core session creation functionality is broken.

**Fix:** Update the proxy POST handler to forward all relevant fields and align the field name (`message` → daemon's expected field).

---

## Important

### I1: Session-scoped endpoints `/keys`, `/voice`, `/file` lack access checks

**File:** `teleclaude/api_server.py:584-657`

`POST /sessions/{id}/keys`, `POST /sessions/{id}/voice`, and `POST /sessions/{id}/file` send inputs to sessions but have no `check_session_access` call. Any authenticated web user can send keystrokes, voice, and files to any session. Compare with `POST /sessions/{id}/message` which correctly guards access.

### I2: WebSocket `sessions_initial` push skips role filtering

**File:** `teleclaude/api_server.py` (WebSocket handler)

`_send_initial_state` emits `sessions_initial` events over WebSocket without applying `_filter_sessions_by_role`. A web client subscribed to sessions receives all sessions regardless of identity/role, bypassing the visibility model.

### I3: `handleEndSession` silently swallows DELETE errors

**File:** `frontend/components/sidebar/SessionHeader.tsx:59-75`

If DELETE returns 4xx/5xx, no feedback is shown. The UI resets to the "End" button with no indication the action failed. Add error state and display feedback on failure.

### I4: No cache invalidation after successful session delete

**File:** `frontend/components/sidebar/SessionHeader.tsx:68`

After successful DELETE, only `router.push("/")` is called. No `queryClient.invalidateQueries({ queryKey: ["sessions"] })`. The deleted session persists in the sidebar until next WS event or 15s polling interval. Contrast with `NewSessionDialog` which correctly invalidates after creation.

### I5: `fetchSessions()` duplicated across three components

**Files:** `frontend/components/sidebar/SessionList.tsx:38-43`, `frontend/components/sidebar/SessionHeader.tsx:36-41`, `frontend/app/dashboard/page.tsx:15-20`

Identical function defined in three files. Divergence risk if API response shape changes. Extract to a shared module (e.g., `frontend/lib/api/sessions.ts`).

### I6: NewSessionDialog fetch effects lack AbortController

**File:** `frontend/components/sidebar/NewSessionDialog.tsx:34-60`

Both `useEffect` hooks use raw `fetch()` without abort cleanup. Rapid open/close or computer changes cause request races. The last to resolve wins and may set stale data.

### I7: Projects "Loading..." shown permanently on fetch error

**File:** `frontend/components/sidebar/NewSessionDialog.tsx:152-155`

After a failed project fetch, `projects` remains empty and the select shows "Loading..." indefinitely. No separate loading/error state for projects. User is stuck with a broken form.

### I8: No tests for security-critical session access control

No test files were added or modified for the new `session_access.py` module, `_filter_sessions_by_role`, or the visibility filtering logic. These are security-critical code paths that enforce who can see and interact with sessions.

### I9: `SessionPicker.tsx` not deleted — dead code

**File:** `frontend/components/SessionPicker.tsx`

The implementation plan specifies "Remove (replaced by Sidebar + SessionList)". The file is no longer imported but still exists in the codebase.

---

## Suggestions

### S1: Admin bypasses session-existence check on delete

**File:** `teleclaude/api/session_access.py:37-39`

When `role == "admin"` and `require_owner=True`, the function returns immediately without verifying the session exists. DELETE of a nonexistent session produces a 500 from the command layer rather than a clean 404.

### S2: `computers` fetch re-fires on every computer-select change

**File:** `frontend/components/sidebar/NewSessionDialog.tsx:34-46`

Dependency array `[open, computer]` causes unnecessary re-fetch of the computers list when the user changes computer selection. Remove `computer` from deps and use functional `setComputer` update.

### S3: Unstable array reference in dashboard query key

**File:** `frontend/app/dashboard/page.tsx:50`

`queryKey: ["dashboard-projects", computers?.map((c) => c.name)]` creates a new array each render. Use a joined string instead for stability.

### S4: Lazy imports of `check_session_access` in 4 endpoint functions

**Files:** `teleclaude/api/streaming.py:245`, `teleclaude/api_server.py:544,568,739`

No circular dependency risk exists. Move to top-level import for clarity and consistency.

### S5: No focus trap for mobile sidebar drawer

**File:** `frontend/components/sidebar/Sidebar.tsx:35-41`

Mobile overlay lacks keyboard focus trapping. Screen reader and keyboard users can interact with content behind the drawer.
