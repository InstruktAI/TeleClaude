# Review Findings: fix-sticky-removal-layout-issues

## Round 2

Re-review after merge with main (`41e19cdd`). No code changes since round 1 APPROVE — merge only touched orchestrator-managed files (`state.yaml`, `quality-checklist.md`, `review-findings.md`).

### Verification

- `git diff 8ea37947..HEAD -- teleclaude/ tests/`: empty — zero code drift
- `git diff main -- teleclaude/ tests/`: identical to round 1 diff
- `make test-unit`: 2260 passed, 106 skipped
- `make lint`: ruff + pyright = 0 errors
- Pane bridge ordering re-verified: `on_sticky_changed` → `on_preview_changed` → PaneWriter coalescing produces correct final snapshot (`pane_bridge.py:140-161`)

### Round 2 Findings

(none — no code changes since round 1)

---

## Round 1

### Review Scope

Files changed (from merge-base):

- `teleclaude/cli/tui/state.py` — reducer change
- `teleclaude/cli/tui/views/sessions.py` — click + keyboard path changes
- `tests/unit/test_tui_state.py` — updated reducer tests
- `tests/unit/test_sessions_view_sticky_preview.py` — new view-level tests
- `demos/fix-sticky-removal-layout-issues/demo.md` — demo artifact

## Critical

(none)

## Important

(none)

## Suggestions

- `TreeInteractionDecision.clear_preview` field name is now semantically inverted: it triggers _setting_ preview to the removed session rather than clearing it. Consider renaming to `promote_to_preview` or `unsticky_sets_preview` in a follow-up. Not actionable in this change — `interaction.py` is explicitly out of scope per requirements.

## Why No Issues

### Paradigm-fit verification

1. **Data flow**: Changes follow the established reducer + view + message + pane bridge pattern. State transitions happen in the reducer (`state.py`), view-level local state is updated in `sessions.py`, and `PreviewChanged`/`StickyChanged` messages propagate to the pane bridge. No bypass of the data layer.
2. **Component reuse**: No new components or abstractions introduced. The fix parameterizes existing state transitions (replacing `None` with `PreviewState(session_id)`). No copy-paste duplication detected — the click and keyboard paths use different detection mechanisms (`not in list` vs `decision.clear_preview`) appropriate to their context.
3. **Pattern consistency**: Message posting order (StickyChanged before PreviewChanged) is consistent with the PaneWriter coalescing pattern. The `_notify_state_changed()` double-call pattern (once from `_toggle_sticky`, once from the caller) is pre-existing and consistent across both code paths.

### Requirements verification

1. "Double-pressing removes from sticky AND sets as preview" — reducer `state.py:201-203` sets `preview = PreviewState(session_id)` unconditionally on removal. View paths (`sessions.py:528-532`, `sessions.py:632-636`) set `preview_session_id` and post `PreviewChanged`. **Verified.**
2. "Previously active preview is dismissed" — `PreviewState(session_id)` assignment unconditionally replaces any existing preview. **Verified.**
3. "Layout slot count does not change" — sticky slot removed + preview slot added = net zero. PaneWriter coalescing ensures the final layout snapshot has both changes. **Verified via pane_bridge.py read.**
4. "No full pane rebuild" — slot count stability prevents rebuild. Design spec invariant #5 confirmed. **Verified.**
5. "All existing tests pass; new tests cover transition" — 3 updated reducer tests + 2 new view tests + 1 new reducer test. Tests verify message ordering (StickyChanged < PreviewChanged). **Verified.**
6. "Matches design spec" — all interaction rules in `session-preview-sticky.md` double-press table row 2 ("Sticky → Remove sticky, set as preview, dismiss old preview") are implemented. Invariant #2 ("Un-sticky always transitions to preview") is satisfied. **Verified.**

### Copy-paste duplication check

No duplication found. The click path (`on_session_row_pressed`) and keyboard path (`action_toggle_preview`) share `_toggle_sticky()` for the common toggle logic and diverge only in detection mechanism, which is appropriate for their different input contexts.

### Manual verification evidence

Interactive TUI verification was not possible in this headless review. The builder covered all interaction scenarios through automated regression tests:

- Reducer: same-session, different-session, no-prior-preview cases
- View: keyboard (action_toggle_preview) and click (on_session_row_pressed) paths
- Message ordering assertions in both view tests

## Verdict: APPROVE
