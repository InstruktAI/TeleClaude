# Review Findings: fix-tui-preview-race

**Ad-hoc review (via from-main)**

**Commit:** `f5e75a90e` — fix(tui): make session events optimistic, remove eager \_refresh_data

## Summary

The change replaces eager `_refresh_data()` calls (full API re-fetch) in session event
handlers with optimistic updates — directly updating the pane bridge catalog and sessions
view from the WebSocket event payload. Two new methods on `PaneManagerBridge`
(`update_single_session`, `remove_session`) support incremental catalog maintenance.

---

## Critical

_(none)_

## Important

### 1. Missing direct unit tests for new `PaneManagerBridge` methods

**Location:** `tests/unit/cli/tui/test_pane_bridge.py` (missing tests)
**New code:** `teleclaude/cli/tui/pane_bridge.py:164-186`

`update_single_session` has non-trivial replace-or-append logic and `remove_session`
has filter logic. Both call `pane_manager.update_session_catalog()`. These are only
tested indirectly through `test_app_ws.py` using a `_PaneBridge` stub that records
calls but does not exercise the actual implementation.

Required tests:

- `update_single_session` with an existing session (verifies replacement, not duplication)
- `update_single_session` with a new session (verifies append)
- `remove_session` with an existing session
- `remove_session` with a nonexistent session_id (verifies idempotency)
- Both methods must verify `pane_manager.update_session_catalog` receives the correct list

## Suggestions

### 1. Inline imports could be top-level

**Location:** `teleclaude/cli/tui/app_ws.py:147, 169, 183`

The same `from teleclaude.cli.tui.pane_bridge import PaneManagerBridge` appears three
times inside method bodies. No circular dependency exists (`pane_bridge` does not import
from `app_ws` or `app`). The existing inline import at line 232 (`ActivityTrigger`) is
behind a conditional, which justifies inline placement — these three are unconditional.

Moving to a top-level import would satisfy "All imports at module top level" and
eliminate the repetition.

---

## Lane Results

| Lane       | Executed | Findings                                                                                |
| ---------- | -------- | --------------------------------------------------------------------------------------- |
| code       | Yes      | No issues (code reviewer: clean, follows patterns)                                      |
| paradigm   | Yes      | No issues (follows established query_one + message handler patterns)                    |
| principles | Yes      | No violations (immutability preference followed, no fallbacks, no DIP violations)       |
| security   | Yes      | No issues (pure UI event handling, no injection surfaces)                               |
| tests      | Yes      | 1 Important (missing direct unit tests for PaneManagerBridge methods)                   |
| errors     | Yes      | No silent failures introduced (pre-existing PaneWriter log context noted, out of scope) |
| types      | Yes      | No new types introduced                                                                 |
| comments   | Yes      | Comments accurate and descriptive                                                       |
| logging    | Yes      | No logging changes; consistent with existing handlers                                   |
| scope      | N/A      | Ad-hoc item                                                                             |
| demo       | N/A      | Ad-hoc item                                                                             |
| docs       | Yes      | No CLI/config/API changes                                                               |

---

## Fixes Applied

### 1. Missing direct unit tests for new `PaneManagerBridge` methods

- **Fix:** Added comprehensive unit tests covering existing/new session updates and existing/missing session removal.
- **Commit:** `cfd27f9e7`

### 2. Inline imports could be top-level

- **Fix:** Moved `PaneManagerBridge` import to module top-level in `app_ws.py` and removed redundant inline imports.
- **Commit:** `eecf49b88`

## Verdict: REQUEST CHANGES

**Unresolved Critical:** 0
**Unresolved Important:** 0
