# Review Findings: atomic-layout-messages

Baseline: `255357f833b188c22268e8c0f4e3b2973699d111`

## Critical

- None.

## Important

- F1. `teleclaude/cli/tui/views/sessions_actions.py:139`, `teleclaude/cli/tui/views/sessions_actions.py:153`, `teleclaude/cli/tui/views/sessions.py:608`:
  the extracted `_toggle_sticky_state` helper now returns early when `MAX_STICKY`
  is reached, but it no longer tells callers whether a mutation happened. Both
  `_toggle_sticky` and the double-click path still post `StickyChanged` and mark
  state dirty after that no-op. Reproduced locally with a full sticky list:
  `_toggle_sticky("overflow")` leaves `_sticky_session_ids` unchanged but still
  posts `StickyChanged` and calls `_notify_state_changed()`. Before this refactor,
  `_toggle_sticky` returned before posting anything. This is a behavioral
  regression outside the atomic-message requirement and needs a changed/no-op
  signal so notifications only fire on real mutations.

- F2. `tools/session_scope.py:47`:
  the lint-mode filter no longer checks whether a touched Python file still exists
  before emitting it. Session-touched files can include deletions, and
  `tools/lint.sh:76` forwards the scoped list directly to `ruff`, `pyright`,
  `mypy`, and `pylint`. Reproduced locally: `_filter_by_mode("lint",
{"teleclaude/missing.py"}, Path("."))` returns the missing path, and
  `ruff check teleclaude/missing.py` fails with `E902 No such file or directory`.
  This change is also outside the approved TUI/message scope for the todo.

## Suggestions

- None.

## Completeness

- `implementation-plan.md` is fully checked.
- No `deferrals.md` file is present.

## Scope Lane

- Finding F2. The approved scope was the TUI messaging and bridge layer, but the
  delivery also changes `tools/session_scope.py` and regresses scoped linting.
- No other requirement gaps were found in the TUI change set.

## Code Lane

- Finding F1. The sticky-toggle refactor broke the prior no-op contract when the
  sticky limit is already full.
- Finding F2. The tooling change introduces a missing-file failure path into the
  lint gate.

## Paradigm Lane

- No additional findings. The atomic message plus bridge forwarding follow the
  existing Textual message-bubbling pattern.

## Principles Lane

- Finding F2. Removing the existence guard in `tools/session_scope.py` creates an
  unjustified fallback from "valid touched file set" to "emit whatever string was
  seen", which violates fail-fast and scope discipline for the lint boundary.
- No additional boundary-purity or adapter-coupling issues were found in the TUI
  changes.

## Security Lane

- No findings. I did not find secrets, unsafe shell interpolation in the TUI
  changes, auth regressions, or end-user error leakage.

## Tests Lane

- The branch includes direct coverage for R1-R4 and preserves the delivered spec
  assertions. Comparing `0d2a6dfae..HEAD` shows the spec tests only had their
  `xfail` markers removed; assertions were not weakened or deleted.
- I re-ran the targeted TUI tests in the project venv:
  `tests/unit/cli/tui/test_pane_bridge.py::test_on_sticky_and_preview_changed_applies_both_state_and_marks_layout_dirty_once`,
  `tests/unit/cli/tui/test_app_actions.py::test_app_on_sticky_and_preview_changed_delegates_to_bridge_updates_banner_and_schedules_sky_width`,
  `tests/unit/cli/tui/views/test_sessions_actions.py::test_toggle_sticky_state_mutation_does_not_call_post_message`,
  `tests/unit/cli/tui/views/test_sessions_actions.py::test_action_toggle_preview_toggle_sticky_with_clear_preview_posts_single_atomic_message`,
  `tests/unit/cli/tui/views/test_sessions_actions.py::test_action_toggle_sticky_sessions_scope_off_posts_single_atomic_message`,
  `tests/unit/cli/tui/views/test_sessions.py::test_on_session_row_pressed_double_click_sticky_posts_single_atomic_message`,
  and the broader four-file TUI subset plus `tests/unit/tools/test_session_scope.py`; all passed.
- Finding F1 remains untested: there is no regression test proving that hitting
  `MAX_STICKY` is a true no-op for message emission after the helper extraction.

## Errors Lane

- Finding F1. The refactor now emits a state-change message on a no-op overflow
  path instead of preserving the previous early return.
- Finding F2. Scoped linting now turns a deleted touched file into an immediate
  tool failure.

## Types Lane

- No findings. The new `StickyAndPreviewChanged` payload shape is explicit and the
  bridge/app handlers remain typed.

## Comments Lane

- No findings. The new comments/docstrings match the implemented atomic-message
  behavior.

## Logging Lane

- No findings. The change set does not add ad-hoc debug probes or logging-policy
  violations.

## Demo Lane

- No findings. The demo commands target real tests and real files, and the grep
  inspection matches the implemented handler/message names.

## Docs Lane

- Not triggered. The change does not add or modify CLI commands, config keys, or
  public API surface.

## Simplify Lane

- Skipped because blocking Important findings remain.

## User-Facing Verification

- Builder evidence is adequate for the intended scope: this is an internal Textual
  message-path change, not a browser-facing change. The targeted TUI tests above
  are the observable verification path. No Playwright browser smoke review was
  applicable.

## Fixes Applied

| Finding | Fix                                                                                                                                                              | Commit      |
| ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- |
| F1      | `_toggle_sticky_state` returns `bool`; `_toggle_sticky` and double-click path skip `StickyChanged`/`_notify_state_changed` on no-op. Two regression tests added. | `c0038d94e` |
| F2      | Added `(project_root / f).exists()` guard in lint-mode filter. Three existing tests updated to create source files on disk. One regression test added.           | `66583da35` |

## Verdict

- REQUEST CHANGES
