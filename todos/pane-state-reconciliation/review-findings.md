# Review Findings: pane-state-reconciliation

**Reviewer:** Claude (Opus 4.6)
**Date:** 2026-02-21
**Round:** 1
**Baseline commit:** 4931faa5

---

## Critical

_None._

## Important

### 1. `_reconcile()` lacks TUI pane sanity check

**File:** `teleclaude/cli/tui/pane_manager.py:208-220`
**Severity:** Important
**Confidence:** 85%

If `list-panes` returns empty output (tmux transient error, race during teardown), all `session_to_pane` entries are pruned and `active_session_id` is cleared — a full state wipeout. The TUI's own pane (`_tui_pane_id`) should always appear in `list-panes` output since the TUI is running inside tmux. Checking for its presence would distinguish "tmux is broken" from "child panes died."

**Suggested fix:** After parsing `live_panes`, bail early if `self._tui_pane_id not in live_panes` — this means the query itself is unreliable, not that everything is dead.

### 2. `seed_for_reload()` thread-safety invariant is undocumented

**File:** `teleclaude/cli/tui/pane_manager.py:168-186`
**Severity:** Important
**Confidence:** 80%

`seed_for_reload()` mutates `self.state` directly on the Textual main thread. This is safe _in practice_ because on reload `_initial_layout_applied=True`, so no `_apply()` is queued to the PaneWriter before seeding completes. However, this ordering invariant is implicit. A future change that queues work before seeding would introduce a data race.

**Suggested fix:** Add a brief comment above `seed_for_reload()` documenting the invariant: "Must run before any PaneWriter work is queued. Safe on reload because \_initial_layout_applied=True prevents \_apply() scheduling."

### 3. Missing unit test for `seed_for_reload()`

**File:** `tests/unit/test_pane_manager.py`
**Severity:** Important
**Confidence:** 90%

`seed_for_reload()` is a key method in the reload path — it populates `state.session_to_pane` from `_reload_session_panes` and sets `active_session_id`. It has no dedicated unit test. The reload init test (`test_reload_init_preserves_existing_panes`) covers `_adopt_for_reload()` but not the seeding step that happens earlier in the flow.

**Suggested fix:** Add a test that sets `_reload_session_panes`, calls `seed_for_reload()`, and asserts the resulting state.

## Suggestions

### 4. Consider logging in `_reconcile()` when pruning dead panes

**File:** `teleclaude/cli/tui/pane_manager.py:208-220`

Silent pruning makes debugging harder. A `logger.debug` line when dead sessions are removed would aid troubleshooting without adding noise.

### 5. Bridge `_reload_session_panes` access crosses encapsulation boundary

**File:** `teleclaude/cli/tui/pane_bridge.py:72`

`pane_bridge.py` reads `self._pane_manager._reload_session_panes` directly (private attribute). This works but creates a coupling that bypasses the public interface. A lightweight accessor (property or method) on PaneManager would be cleaner.

---

## Requirement Tracing

| Requirement                                                  | Status               |
| ------------------------------------------------------------ | -------------------- |
| PaneState reduced to `session_to_pane` + `active_session_id` | Implemented          |
| `_reconcile()` queries tmux before every `apply_layout()`    | Implemented          |
| `_sync_sticky_mappings` removed                              | Confirmed removed    |
| Old 7-field PaneState fields removed from all TUI code       | Confirmed            |
| Cold-start kills orphaned panes                              | Implemented + tested |
| SIGUSR2 reload adopts existing panes                         | Implemented + tested |
| `seed_for_reload()` populates state from reload env          | Implemented          |
| No regressions in existing pane manager tests                | 19/19 pass           |

## Deferrals

No `deferrals.md` exists. No implicit deferrals detected beyond Task 4.3 (manual verification), which is appropriately deferred to the reviewer and confirmed: the implementation matches the plan.

## Test Coverage Assessment

- **19/19 pane manager tests pass** (verified via `.venv/bin/pytest tests/unit/test_pane_manager.py -v`)
- **Lint clean:** 0 errors, 0 warnings
- **Pre-existing failures** in unrelated modules (`test_tui_sessions_view.py`, `test_tui_theme.py`, `test_tui_view_snapshots.py`) — not caused by this branch
- **Coverage gaps:** `seed_for_reload()` (Important #3), `_reconcile()` with empty tmux output (addressed by Important #1)
- **Overall test quality:** Good — tests verify behavioral contracts, not implementation details

## Verdict: APPROVE

The implementation correctly fulfills all requirements. PaneState is cleanly reduced, `_reconcile()` provides the intended single-query-before-layout pattern, and the reload flow is properly restructured. The three Important findings are real improvements but none represent blocking defects — the code is correct as-is, and the suggestions strengthen robustness for future maintainers.
