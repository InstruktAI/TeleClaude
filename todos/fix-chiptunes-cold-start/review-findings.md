# Review Findings: fix-chiptunes-cold-start

**Type:** Ad-hoc review (via from-main)

## Round 1 — Resolved

### 1. Stale `pending_command_id` causes permanent TUI button deadlock (Critical — remediated)

**Location:** `teleclaude/config/runtime_settings.py:169-179`

The cold-start resume path in `issue_chiptunes_command` sets `pending_command_id`
before branching into `start()` / `start_from_runtime_state()`. These methods start
the worker directly — they do not send the `command_id` to the worker, so the worker
never emits `command_done` for it. The stale `pending_command_id` persists through
`sync_chiptunes_state` → `_broadcast_chiptunes_state` → `ChiptunesStateEvent` WS
events, keeping the TUI footer in permanent pending state.

**Fix applied:** Clear `pending_command_id` and `pending_action` immediately after the
cold-start branch (commit 683975657).

### 2. Orphan-exclude scope contamination (Important — remediated)

**Location:** `pyproject.toml:358-360`

Three orphan-exclude entries for test files belonging to a different slug were included.

**Fix applied:** Removed the three orphan-exclude entries (commit 6fee4a368).

### 3. No tests for cold-start resume in `issue_chiptunes_command` (Important — remediated)

**Fix applied:** Added `test_issue_chiptunes_command_cold_starts_without_track` and
`test_issue_chiptunes_command_cold_starts_with_track` (commit 5621f033f).

### 4. No test for `bootstrap_chiptunes` stale-clearing (Important — remediated)

**Fix applied:** Added `test_bootstrap_chiptunes_clears_stale_pending_fields` (commit 5621f033f).

### 5. No test for `enqueue_command` reconnection (Important — remediated)

**Fix applied:** Added `test_enqueue_command_reconnects_when_socket_is_none` (commit cdf70fc78).

### 7. No logging at pending-clearing points (Suggestion — remediated)

**Fix applied:** Added debug logging at both bootstrap and cold-start clearing points
(commit 5621f033f).

## Round 2

### Verification of Round 1 Remediation

All round 1 findings confirmed resolved:

- **Finding #1:** `pending_command_id` and `pending_action` cleared at lines 185-186
  after cold-start branch. Debug log at line 184.
- **Finding #2:** Orphan-exclude entries removed from diff.
- **Finding #3:** Two cold-start tests exist (lines 278-307 of test_runtime_settings.py),
  covering both trackless and track-based paths. Tests pass.
- **Finding #4:** Stale-clearing test exists (lines 168-188 of test_runtime_settings.py)
  with before/after assertions. Test passes.
- **Finding #5:** Reconnection test exists (lines 220-239 of test_manager.py), verifying
  socket transitions from None to connected and command delivery. Test passes.
- **Finding #7:** Debug logging added at bootstrap clearing (line 123-127) and cold-start
  clearing (line 184).

All 32 tests pass (verified via `pytest`).

### Code Lane

No new findings. The cold-start pattern mirrors `set_chiptunes_paused` (lines 148-155).
UP038 lint fixes (`isinstance(x, int | float)`) are correct modern Python syntax.

### Paradigm Lane

No findings. Good paradigm-fit with established codebase patterns. The cold-start
branch in `issue_chiptunes_command` uses the same `start()` / `start_from_runtime_state()`
dispatch as `set_chiptunes_paused`.

### Principles Lane

No findings. No unjustified fallbacks — the unconditional clearing in `bootstrap_chiptunes`
is correct (stale pending state from a dead worker must always be cleared). No DIP
violations, no coupling issues, no SRP violations.

### Security Lane

No findings. No secrets, injection vectors, auth changes, or sensitive data in logs.

### Errors Lane

No new findings introduced by this diff. Pre-existing `_send_cmd` silent-drop behavior
(when `sock is None`) applies to all command methods — the new `enqueue_command`
reconnection path actually improves the situation by attempting recovery before the
drop point. Pre-existing patterns in `_read_events`, `_handle_event`, and
`_schedule_flush` are out of scope for this review.

### Tests Lane

No findings. All three new behavioral paths have direct test coverage:

- `enqueue_command` reconnection: `test_enqueue_command_reconnects_when_socket_is_none`
- `bootstrap_chiptunes` stale-clearing: `test_bootstrap_chiptunes_clears_stale_pending_fields`
- `issue_chiptunes_command` cold-start: two tests covering trackless and track-based paths

Tests verify behavior (stub call records, state transitions), not implementation details.

### Comments Lane

No findings. All new comments accurately describe present behavior:

- `bootstrap_chiptunes`: "Clear stale pending commands from previous daemon session"
- `issue_chiptunes_command`: "Cold start: if the worker isn't running, launch it before sending"
- "Playback starts directly — no command_done event will arrive"

### Logging Lane

No findings. Debug logging present at both clearing points (bootstrap and cold-start).

### Suggestions (non-blocking)

#### S1. `enqueue_command` blocks caller thread on reconnection

**Location:** `teleclaude/chiptunes/manager.py:128-130`

When `_sock is None`, `enqueue_command` calls `_ensure_worker()` (up to 5s polling)
and `_connect()` (blocking socket I/O) on the caller's thread. This is a recovery
scenario (socket lost while manager was running) and acceptable in current code paths,
but future callers from async contexts should be aware of the blocking potential.

#### S2. Race condition on `_sock` check

**Location:** `teleclaude/chiptunes/manager.py:128`

`self._sock is None` is checked outside `self._lock`. TOCTOU gap exists with concurrent
`_disconnect()`/`_connect()`. Low probability in practice — `enqueue_command` is called
from a single event loop context and the reconnection scenario is rare.

## Why No Issues (Round 2)

1. **Paradigm-fit verified:** Cold-start pattern matches `set_chiptunes_paused` (same
   `start()` / `start_from_runtime_state()` dispatch, same track-path branching).
2. **Requirements met:** Both bugs addressed — stale pending commands cleared on bootstrap,
   cold-start path restored for `issue_chiptunes_command`.
3. **Copy-paste duplication checked:** No duplication. The cold-start logic in
   `issue_chiptunes_command` and `set_chiptunes_paused` serve different entry points
   (command receipt vs pause/resume toggle) with different state management needs.
4. **Security reviewed:** No secrets, injection, auth, or info-leakage vectors in diff.

## Verdict

**Unresolved Critical:** 0
**Unresolved Important:** 0
**Unresolved Suggestions:** 2

**Verdict: APPROVE**
