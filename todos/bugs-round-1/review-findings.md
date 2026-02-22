# Review Findings: bugs-round-1

## Review Round 1

### Critical

(none)

### Important

(none)

### Suggestions

1. **`pane_manager.py:1058-1059,1065-1066` — Duplicate `refresh-client` in both branches**
   The `refresh-client` call appears identically in both the themed and unthemed branches of `_set_tui_pane_background()`. It could be extracted to after the if/else block. However, keeping it inside each branch is defensible — it makes the intent self-documenting per branch and avoids a subtle bug if a future branch is added that should not refresh. No action needed.

### Analysis

**Bug 1 (slug color inversion):** The fix at `session_row.py:173` correctly ternaries on `selected or previewed` to use the row `style` (which carries inverted fg/bg) or the agent normal color. All state combinations verified:

- Selected: slug inherits selection bar style (inverted fg/bg, bold). Correct.
- Previewed: slug inherits preview bar style. Correct.
- Both selected and previewed: `_get_row_style` returns selection (checked first). Ternary also resolves to `style`. Correct.
- Neither: falls through to `resolve_style(self.agent, self._tier("normal"))`. Correct.
- Headless (tier-shifted): unselected slug gets muted tier; selected slug gets selection style (not tier-dependent). Matches plan Task 1.2.
- Collapsed with activity highlight: slug stays in normal tier while row is in highlight tier. Preserves slug visual identity. Correct.

**Bug 2 (TUI pane background):** `refresh-client` at `pane_manager.py:1059,1066` forces tmux to re-render all panes with current style definitions without changing focus. Placed after all style-setting commands in both branches. Only one `refresh-client` fires per SIGUSR1 cycle. Not in any hot path — no flicker or performance concern.

**Comments:** The old comment ("always highlighted regardless of activity state") was inaccurate and replaced with a correct description. New comments are accurate and minimal.

**Test coverage:** These are visual/TUI bugs involving tmux subprocess interaction and Rich rendering. Manual verification (Phase 3) is appropriate. Lint and test suites passed.

**Requirements trace:** All five success criteria from requirements.md map to implemented code paths.

## Verdict: APPROVE
