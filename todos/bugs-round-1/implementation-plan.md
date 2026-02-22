# Implementation Plan: bugs-round-1

## Overview

Two independent visual bugs, both in the TUI rendering layer. Bug 1 is a Rich Text styling issue in `session_row.py`. Bug 2 is a tmux pane style refresh issue in the SIGUSR1 handler path. Both can be fixed with minimal, targeted changes.

## Phase 1: Fix slug color inversion on selection

### Task 1.1: Make slug style respect selection/preview state

**File(s):** `teleclaude/cli/tui/widgets/session_row.py`

- [x] In `_build_title_line()` (line ~171), replace the hardcoded `resolve_style(self.agent, self._tier("normal"))` for the slug span with logic that:
  - When `selected` or `previewed`: uses the row `style` (which includes `bgcolor` and inverted `color`), preserving the selection bar continuity.
  - When neither: uses `resolve_style(self.agent, self._tier("normal"))` as today (agent color, no bold, no italic, no bgcolor).
- [x] Verify the badge style (line ~153) is correct — it already uses its own style and does NOT inherit selection bg (by design, per the comment on line 149).

### Task 1.2: Verify tier shifting is preserved

**File(s):** `teleclaude/cli/tui/widgets/session_row.py`

- [x] Confirm that headless sessions still get tier-shifted slug colors in unselected state.
- [x] Confirm that the `_tier()` shift does not apply to selected state (selected always uses inverted fg/bg, not tier-dependent colors).

---

## Phase 2: Fix TUI pane background after appearance toggle

### Task 2.1: Investigate TUI pane background refresh on SIGUSR1

**File(s):** `teleclaude/cli/tui/app.py`, `teleclaude/cli/tui/pane_manager.py`

- [x] Trace the SIGUSR1 flow: `_handle_sigusr1()` -> `_appearance_refresh()` -> `theme.refresh_mode()` -> `pane_bridge.reapply_colors()` -> `reapply_agent_colors()` -> `_set_tui_pane_background()`.
- [x] Identify why `_set_tui_pane_background()` sets both `window-style` and `window-active-style` but the TUI pane's background may not visually update when the pane doesn't have focus.
- [x] Determine if tmux requires a focus cycle (select-pane) or explicit refresh to apply the new `window-active-style` to an inactive pane.

### Task 2.2: Apply the fix

**File(s):** `teleclaude/cli/tui/pane_manager.py` (and possibly `app.py`)

- [x] If tmux doesn't re-evaluate styles on style change alone, add a `select-pane` round-trip or `refresh-client` after setting new styles in `_set_tui_pane_background()`.
- [x] Ensure the fix works for both directions (dark->light and light->dark).
- [x] Ensure the fix doesn't cause visual flicker (brief focus change).

---

## Phase 3: Validation

### Task 3.1: Manual verification

- [x] Toggle dark/light mode with TUI pane focused — verify immediate background update.
- [x] Toggle dark/light mode with preview pane focused — verify TUI pane background updates when switching back.
- [x] Select a session row with a slug — verify slug text is fully inverted with the selection bar.
- [x] Navigate away from the selected row — verify slug returns to normal agent color.

### Task 3.2: Quality checks

- [x] Run `make lint`
- [x] Run `make test`
- [x] Verify no unchecked implementation tasks remain

---

## Phase 4: Review Readiness

- [x] Confirm requirements are reflected in code changes
- [x] Confirm implementation tasks are all marked `[x]`
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable)
