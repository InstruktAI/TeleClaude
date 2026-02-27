# DOR Report: fix-sticky-removal-layout-issues

## Draft Assessment

### Gate 1: Intent & Success

**Pass.** Problem statement is explicit: un-stickying causes layout instability. Intended outcome is concrete: un-sticky transitions to preview, preserving layout stability. Success criteria in `requirements.md` are testable (6 checkboxes, all observable).

### Gate 2: Scope & Size

**Pass.** The work is atomic — two files to modify (`state.py` reducer, `sessions.py` view), one read-only verification (`pane_bridge.py`), and test updates. Fits a single AI session easily. No cross-cutting changes.

### Gate 3: Verification

**Pass.** Clear verification path: unit tests for the reducer transition, existing test to update (`test_remove_sticky_clears_preview_for_same_session`), two new tests specified, plus manual TUI verification steps. Edge cases identified (ordering of StickyChanged/PreviewChanged messages).

### Gate 4: Approach Known

**Pass.** The technical path is specified in `implementation-plan.md` with exact code changes. The pattern exists in the codebase — `PreviewState(session_id)` is already used in the SET_PREVIEW reducer branch. The change is a 3-line reducer modification plus a message flow update in sessions.py.

### Gate 5: Research Complete

**N/A.** No third-party dependencies. Automatically satisfied.

### Gate 6: Dependencies & Preconditions

**Pass.** No prerequisite tasks. The partial fix (clearing stale preview on un-sticky) is already on main. The contaminated frontend work has been reverted. Codebase is in a clean state for this work.

### Gate 7: Integration Safety

**Pass.** The change is incremental — modifying reducer behavior for one intent type. Rollback is trivial (revert the commit). The change is contained within `teleclaude/cli/tui/` with no external API surface changes.

### Gate 8: Tooling Impact

**N/A.** No tooling changes. Automatically satisfied.

## Open Questions

- The `sessions.py` TOGGLE_STICKY handler has a `decision.clear_preview` branch. The implementation plan notes this may need adjustment when the preview is being set explicitly on un-sticky. The builder should verify whether `clear_preview` logic conflicts with the new explicit preview set.

## Assumptions

- The `PreviewChanged` message posted after un-sticky will be processed correctly by `pane_bridge.py` without ordering issues. Implementation plan Task 1.3 covers read-only verification of this.
- Existing `interaction.py` gesture logic is correct and does not need changes (confirmed in requirements scope).

## Blockers

None identified.
