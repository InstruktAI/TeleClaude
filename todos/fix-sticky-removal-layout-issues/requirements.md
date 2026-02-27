# Requirements: fix-sticky-removal-layout-issues

## Goal

Fix sticky session removal in the Python TUI to follow the interaction model defined in `@docs/project/design/ux/session-preview-sticky.md`. Currently, un-stickying a session causes layout instability (split panes, full rebuilds). The correct behavior is: un-stickying transitions the session to preview, preserving layout stability.

## Context

A previous attempt (commit `849c3a22`) incorrectly applied fixes to the TypeScript frontend (`frontend/cli/`) instead of the Python TUI (`teleclaude/cli/tui/`). That work has been reverted. The contaminated `frontend/cli/` directory has been removed entirely.

A partial fix is already on main: the TOGGLE_STICKY reducer in `state.py` now clears stale preview when removing a sticky. This prevents state corruption but does not implement the full un-sticky → preview transition.

## Scope

### In scope

- Implement un-sticky → preview transition in the Python TUI reducer (`teleclaude/cli/tui/state.py`)
- Ensure `sessions.py` TOGGLE_STICKY handler posts the correct `PreviewChanged` message after un-stickying
- Update existing tests and add new tests covering the transition
- Verify layout stability: un-stickying must not trigger a full pane rebuild

### Out of scope

- Any changes to the TypeScript frontend (`frontend/`)
- Changes to the gesture/interaction state machine (`interaction.py`) — the gestures are correct
- Changes to `pane_manager.py` layout signature or render logic — these should work correctly once state is right

## Success Criteria

- [ ] Double-pressing a sticky session removes it from sticky list AND sets it as the active preview
- [ ] Any previously active preview is dismissed when the un-stickied session becomes preview
- [ ] Layout slot count does not change on un-sticky (sticky slot becomes preview slot)
- [ ] No full pane rebuild occurs on un-sticky (signature stays stable)
- [ ] All existing tests pass; new tests cover the un-sticky → preview transition
- [ ] Behavior matches `@docs/project/design/ux/session-preview-sticky.md` for all interaction cases

## Constraints

- Changes MUST be in the Python TUI only (`teleclaude/cli/tui/`)
- Do NOT modify `frontend/` — architecture boundary is enforced (see `frontend/AGENTS.master.md`)
- The reducer is the source of truth for state transitions; views emit intents and messages

## Risks

- The `pane_bridge.py` processes `StickyChanged` and `PreviewChanged` messages in sequence. Ordering matters — ensure `PreviewChanged` with the new preview arrives and is processed correctly.
