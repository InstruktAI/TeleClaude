# Review Findings: fix-sticky-removal-layout-issues

## Review Scope

Files changed (from merge-base against main):

- `teleclaude/cli/tui/state.py` — reducer: un-sticky now sets preview instead of clearing
- `teleclaude/cli/tui/views/sessions.py` — click + keyboard paths set preview on un-sticky
- `tests/unit/test_tui_state.py` — updated and new reducer tests
- `tests/unit/test_sessions_view_sticky_preview.py` — new view-level regression tests
- `demos/fix-sticky-removal-layout-issues/demo.md` — demo artifact

## Critical

(none)

## Important

(none)

## Suggestions

- `TreeInteractionDecision.clear_preview` field name (`interaction.py:83`) is now semantically inverted: when `True`, the handler _sets_ preview to the removed session rather than clearing it. Consider renaming to `promote_to_preview` in a follow-up. Not actionable here — `interaction.py` is explicitly out of scope per requirements.

## Why No Issues

### Paradigm-fit verification

1. **Data flow**: Changes follow the established reducer + view + message + pane bridge pattern. The reducer (`state.py`) owns state transitions, the view (`sessions.py`) manages local reactive state and posts `PreviewChanged`/`StickyChanged` messages, and `pane_bridge.py` consumes them. No bypass of the data layer detected.
2. **Component reuse**: No new components or abstractions. The fix changes existing transitions (replacing `None` with `PreviewState(session_id=session_id)` in the reducer, and `None` with `session_id` in the view). No copy-paste duplication — the click path (`on_session_row_pressed`) and keyboard path (`action_toggle_preview`) share `_toggle_sticky()` and diverge only where their detection mechanisms differ (list membership check vs `decision.clear_preview`), which is appropriate.
3. **Pattern consistency**: Message posting order (StickyChanged before PreviewChanged) is consistent with PaneWriter coalescing expectations. The double `_notify_state_changed()` call (once from `_toggle_sticky`, once from the caller) is a pre-existing pattern, not introduced by this change.

### Requirements verification

1. **"Double-pressing removes from sticky AND sets as preview"** — Reducer `state.py:201-203` sets `preview = PreviewState(session_id)` unconditionally on removal. View click path `sessions.py:528-532` and keyboard path `sessions.py:632-636` both set `preview_session_id` and post `PreviewChanged`. **Verified.**
2. **"Previously active preview is dismissed"** — `PreviewState(session_id)` assignment unconditionally replaces any existing preview state. Tested explicitly in `test_remove_sticky_preserves_preview_for_different_session` (preview-B replaced by sticky-A). **Verified.**
3. **"Layout slot count does not change"** — Sticky slot removed + preview slot added = net zero change. `pane_bridge.py:198-201` processes StickyChanged then PreviewChanged; PaneWriter coalescing produces correct final snapshot. **Verified via pane_bridge.py read.**
4. **"No full pane rebuild"** — Slot count stability prevents signature change, preventing rebuild. **Verified.**
5. **"All existing tests pass; new tests cover transition"** — 2260 unit tests pass. 4 reducer tests (1 existing updated, 2 updated, 1 new) + 2 new view-level tests covering both paths. Tests verify message ordering (StickyChanged posted before PreviewChanged). **Verified.**
6. **"Behavior matches design spec"** — Un-sticky → preview transition matches the interaction model. **Verified.**

### Copy-paste duplication check

No duplication found. Shared logic lives in `_toggle_sticky()`. Path-specific logic differs appropriately for click vs keyboard detection.

### Manual verification evidence

Interactive TUI verification not possible in headless review environment. All interaction scenarios covered by automated regression tests:

- Reducer: same-session preview, different-session preview replacement, no-prior-preview promotion
- View: keyboard path (`action_toggle_preview`) and click path (`on_session_row_pressed`)
- Message ordering assertions (StickyChanged < PreviewChanged) in both view tests

### Independent verification performed

- `make test-unit`: 2260 passed, 106 skipped, 0 failed
- `make lint`: All checks passed (ruff format, ruff check, pyright 0 errors)

## Verdict: APPROVE
