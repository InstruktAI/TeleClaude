# DOR Report: bugs-round-1

## Gate Assessment (Final)

### Gate 1: Intent & success

**Pass.** Two concrete visual bugs with clear reproduction steps from user observation. Success criteria are testable (visual inspection of slug inversion and pane background after toggle).

### Gate 2: Scope & size

**Pass.** Two independent bugs in two files (`session_row.py`, `pane_manager.py`). Small, atomic changes. Fits a single AI session.

### Gate 3: Verification

**Pass.** Verification is manual (visual inspection) with clear reproduction steps. Edge cases identified (both dark/light toggle directions, focused vs unfocused pane states). Manual verification is appropriate and sufficient for TUI visual bugs.

### Gate 4: Approach known

**Conditional pass.** Bug 1 has a clear, straightforward fix path in `_build_title_line()`. Bug 2 has a clear hypothesis (tmux style refresh) with bounded investigation scope (Task 2.1) to determine which tmux command to use (`select-pane` round-trip or `refresh-client`). The unknown is small and implementation-level, not a fundamental approach gap.

### Gate 5: Research complete

**Auto-pass.** No third-party dependencies introduced.

### Gate 6: Dependencies & preconditions

**Fail (administrative blocker).** `bugs-round-1` is not listed in `roadmap.yaml`. Must be added with appropriate description and priority before this work can be scheduled. No technical dependencies or preconditions identified.

### Gate 7: Integration safety

**Pass.** Both fixes are additive visual corrections with no behavioral side effects. Safe to merge incrementally.

### Gate 8: Tooling impact

**Auto-pass.** No tooling changes.

## Gate Verdict

**Score: 8/10** — Technical quality meets readiness threshold.

**Status: needs_work** — Single administrative blocker prevents scheduling.

**Blocker:** `bugs-round-1` not in `roadmap.yaml`.

**Once roadmap is updated, this work is ready for build phase.**

### Summary by Gate

| Gate | Result        | Note                                         |
| ---- | ------------- | -------------------------------------------- |
| 1    | ✓ Pass        | Clear intent and concrete success criteria   |
| 2    | ✓ Pass        | Atomic scope, fits single session            |
| 3    | ✓ Pass        | Manual verification path is appropriate      |
| 4    | ✓ Conditional | Bug 1 clear, Bug 2 has bounded investigation |
| 5    | ✓ Auto-pass   | No third-party dependencies                  |
| 6    | ❌ Fail       | Roadmap gap (administrative, not technical)  |
| 7    | ✓ Pass        | Safe for incremental merge                   |
| 8    | ✓ Auto-pass   | No tooling impact                            |

## Actions to Unblock

1. Add `bugs-round-1` to `roadmap.yaml` with description and priority position.
2. No technical artifact revisions needed — requirements and implementation plan are solid.

## Open Questions

1. **Bug 2 investigation (Task 2.1):** Determine whether the issue is tmux not re-evaluating `window-active-style` for unfocused panes, or Textual app's background rendering masking the tmux pane background. Builder should test by temporarily disabling Textual theme switching and observing tmux-only behavior.

## Assumptions

- The slug rendering in `_build_title_line()` is the only place child session slugs are displayed.
- The SIGUSR1 handler path (`_appearance_refresh`) is the only path that hot-swaps dark/light mode (SIGUSR2 does full restart, not affected).
