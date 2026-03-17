# Review Findings: fix-tui-new-session-ux

**Ad-hoc review (via from-main)** — requirements and implementation plan are stubs.
Scope lane and demo lane skipped per ad-hoc review policy.

## Diff summary

Single file changed: `teleclaude/cli/tui/views/sessions.py`

Three behavioral changes:

1. **Auto-select without tmux readiness check** — removed the guard `if not widget.session.tmux_session_name: return` from `_apply_pending_selection`. Selection now fires immediately when the session appears in the tree.
2. **`request_focus=True`** — changed from `False` to `True` in the `PreviewChanged` message posted on auto-select.
3. **All new sessions auto-expand** — removed the headless-only condition from `_mount_node`; all first-mount sessions now get added to `_collapsed_sessions` (which controls expanded state).

---

## Lane Results

### Code lane

**No unresolved findings.** The removal of the tmux readiness check is architecturally correct — the guard was in the wrong layer. `pane_layout.py:73` verifies `session.tmux_session_name` before building the `active_spec`, so when the pane doesn't exist yet, the layout is simply rendered with no active spec and no crash.

The `request_focus=True` change flows through `pane_bridge.on_preview_changed` → `_apply(focus=True)` → `pane_manager.apply_layout(focus=True)` → `focus_pane_for_session`, which gracefully returns `False` if no pane is mapped yet (`pane_manager.py:649-656`). Delegation is substantiated.

Auto-expand behavior is wider than the comment implies (all first-mount sessions, not just "new" sessions that the user initiated). On first TUI load, any session that had not been mounted in the current process will auto-expand. This is likely acceptable (one-time startup effect) and consistent with the UX goal.

### Paradigm lane

No violations. Changes use established TUI patterns: `_pending_select_session_id`, `PreviewChanged` messages, `_collapsed_sessions` set. No data layer bypass, no copy-paste.

### Principles lane

No violations. Code is simpler post-change (KISS). No DIP violations, no SRP violations, no unjustified fallbacks.

### Security lane

No findings. No credentials, no user input, no injection vectors, no auth gaps.

**Why No Issues:** Diff is purely TUI widget logic — no I/O, no auth, no external data handling. Security gate verified against DoD Section 5 checklist.

### Tests lane

**[Important] Missing tests for `_apply_pending_selection` behavioral change**
Location: `tests/unit/cli/tui/views/test_sessions.py`

Three behavioral changes were delivered with no new tests. The existing test file contains only an importability check.

The sub-agent analysis confirms that `_apply_pending_selection` is unit-testable without a running Textual app: it operates on `self._nav_items` (a plain list) and calls `self.post_message()` which can be patched. A minimal test would:

- Inject a mock `SessionRow`-like object with `session_id` and `session.tmux_session_name = None` into `_nav_items`
- Set `_pending_select_session_id`
- Patch `post_message`
- Call `_apply_pending_selection()`
- Assert: pending cleared, `post_message` called with `PreviewChanged(target_id, request_focus=True)`

This verifies both the removal of the tmux readiness gate AND the `request_focus=True` change in one test.

The auto-expand change in `_mount_node` is harder to test (DOM mutation required). That gap is defensible given the Textual constraint.

**Note:** The project has established a pattern of importability-only tests for Textual widget methods that require a running app. If the builder determines that patching Textual internals is not viable without the app, this finding should be explicitly documented in the test file with reasoning.

### Silent failures lane

**No findings.** The removed guard delegated to the pane bridge, which is verified: `pane_layout.apply_layout` skips the active spec when `session.tmux_session_name` is absent (`pane_layout.py:73`), producing a no-op layout with no crash or blank-pane state. The next data refresh with a populated `tmux_session_name` will trigger a layout update.

### Types lane

No type signature changes in the diff. Not triggered.

### Comments lane

**[Resolved During Review]** Two stale comments auto-remediated inline:

1. `sessions.py:117-118` — Inline comment for `_pending_select_session_id` said "with a tmux pane ready"; updated to remove the tmux pane condition since that readiness check was removed.

2. `sessions.py:239-244` — Docstring for `request_select_session` said "the session may not yet be in the tree or may not yet have a tmux pane"; removed the "tmux pane" clause since it's no longer a pending condition.

### Logging lane

No logging changes. No ad-hoc debug probes introduced.

### Simplify lane

Code is already simpler post-change (5 lines removed, 0 added). No further simplification needed.

---

## Resolved During Review

| Finding                                            | Resolution                                                 |
| -------------------------------------------------- | ---------------------------------------------------------- |
| Stale comment `_pending_select_session_id`         | Fixed inline — removed "with a tmux pane ready"            |
| Stale docstring `request_select_session`           | Fixed inline — removed tmux pane clause                    |
| Silent failure concern (delegation to pane bridge) | Investigated — `pane_layout.py:73` confirms graceful no-op |

---

## Unresolved Findings

None.

---

## Round 2 — Fix verification (d1d79d782)

Fixer added 4 characterization tests in `tests/unit/cli/tui/views/test_sessions.py`:

- `test_apply_pending_selection_selects_without_tmux_pane` — confirms selection proceeds with `tmux_session_name=None` (removed guard verified)
- `test_apply_pending_selection_transfers_focus` — confirms `PreviewChanged.request_focus=True`
- `test_apply_pending_selection_noop_when_session_not_in_tree` — pending ID kept when session missing
- `test_apply_pending_selection_noop_when_no_pending` — no-op when no pending selection

All tests use duck-typed `_FakeSessionRow` with `isinstance` patching to avoid Textual coupling. Clean approach. All hooks passed.

Important finding resolved.

---

## Verdict

**APPROVE**

Critical: 0
Important: 0
Suggestions: 0
Resolved during review: 3 (inline) + 1 (via fixer round)
