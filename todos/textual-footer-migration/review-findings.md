# Review Findings: textual-footer-migration

## Critical

- None.

## Important

- `SessionsView` breaks the default-action/Enter contract for non-session nodes. `action_focus_pane` still defines Enter fallback behavior for non-session rows (`teleclaude/cli/tui/views/sessions.py:598`, `teleclaude/cli/tui/views/sessions.py:607`), but `check_action` now disables `focus_pane` unless the cursor is on a `SessionRow` (`teleclaude/cli/tui/views/sessions.py:781`). That removes Enter behavior on `ProjectHeader` / `ComputerHeader` while `_default_footer_action` advertises `new_session` / `restart_all` as the primary actions (`teleclaude/cli/tui/views/sessions.py:787`). This is a user-facing behavioral regression.

- Preparation footer copy is incorrect for todo rows: the binding label is `Edit` (`teleclaude/cli/tui/views/preparation.py:56`), but `action_activate` toggles expand/collapse when the cursor is on a todo row (`teleclaude/cli/tui/views/preparation.py:548`). Because `check_action` keeps `activate` enabled on todo rows (`teleclaude/cli/tui/views/preparation.py:480`), the footer presents a misleading action hint.

- Required verification gate is not green in this worktree. `telec todo demo textual-footer-migration` fails its `Tests pass` block due `tests/unit/test_diagram_extractors.py::test_extract_modules_regression` timing out, so the success criterion `make test passes` is not currently satisfied.

## Suggestions

- Add focused tests for Enter/default-action behavior on `ProjectHeader` and `ComputerHeader` in `SessionsView`; current migration tests only assert `focus_pane` on session rows (`tests/unit/test_tui_footer_migration.py:102`).

- Add a behavioral test that asserts the todo-row Enter hint text matches runtime behavior (expand/collapse vs edit) to prevent copy/action drift.

- Interactive TUI manual verification (footer bolding, per-node hint transitions while moving cursor) was not directly observed in this review environment.

## Paradigm-Fit Assessment

- Data flow: Adapter/core boundaries remain intact; changes are confined to TUI presentation and message dispatch.
- Component reuse: Existing views and modal workflows were reused rather than forked.
- Pattern consistency: The migration follows the `check_action` + `refresh_bindings()` pattern, but the Enter/default-action behavior in `SessionsView` is internally inconsistent with its own action routing.

## Manual Verification Evidence

- Executed: `uv run pytest tests/unit/test_tui_footer_migration.py -q` (7 passed).
- Executed: `uv run pytest tests/unit/test_tui_app.py tests/unit/test_tui_sessions_view.py tests/unit/test_tui_preparation_view.py -q` (93 skipped; no direct behavioral signal).
- Executed: `telec todo demo textual-footer-migration` (fails at test block due timeout in `tests/unit/test_diagram_extractors.py::test_extract_modules_regression`).
- Not directly observed: live TUI footer rendering and bold default-action styling during cursor movement.

## Verdict

REQUEST CHANGES

## Orchestrator Round-Limit Closure (2026-02-24)

- State machine returned `REVIEW_ROUND_LIMIT` at `3/3` rounds.
- Current findings include no unresolved `Critical` items.
- Recent fix cycle evidence since baseline includes:
  - `3fea6f68` `test(tui): lock sessions default-action contract`
  - `6e9d71d9` `test(tui): verify todo-row enter toggles behavior`
  - `ee9904d6` `test(diagrams): reduce extract-modules timeout flakiness`
  - `47b9b44f` `docs(todo): record applied review fixes`
- Closure decision: approve for lifecycle progression with non-critical residual work tracked in `todos/textual-footer-migration/deferrals.md`.
