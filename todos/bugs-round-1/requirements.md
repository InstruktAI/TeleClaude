# Requirements: bugs-round-1

## Goal

Fix two visual bugs in the TUI session list:

1. **Slug color inversion on selection** — child session slugs ignore row selection/highlight state, producing broken contrast when the row is selected or previewed.
2. **TUI pane background after dark/light toggle** — SIGUSR1 appearance refresh does not fully update the TUI pane background when switching dark/light mode while focus is on another pane.

## Scope

### In scope

- Fix slug text rendering in `SessionRow._build_title_line()` so the slug respects the row's selected/previewed background color.
- Fix the SIGUSR1 appearance refresh flow so the TUI pane background updates correctly regardless of which pane has focus at signal time.

### Out of scope

- Redesigning the color tier system.
- Changing agent pane (tmux) background handling for non-TUI panes.
- Changes to SIGUSR2 (full restart) flow — that works correctly.

## Success Criteria

- [ ] When a session row with a slug is selected (highlighted), the slug text inverts to the selection foreground color on the selection background — no "hole" in the highlight bar.
- [ ] When a session row with a slug is previewed, the slug text inverts to the selection foreground color on the preview background.
- [ ] When a session row is not selected, the slug displays in its normal agent color without bold or italic.
- [ ] After toggling dark/light mode via SIGUSR1, the TUI pane background updates immediately — regardless of whether the TUI pane or the preview pane is focused at signal time.
- [ ] Switching pane focus after appearance toggle shows correct backgrounds for both active and inactive states.

## Constraints

- Slug normal styling: agent highlight color only. No bold, no italic, no background color in unselected state.
- Must not break the 5-level pane theming paradigm (levels 0-4).
- Changes should follow existing `session_row.py` and `theme.py` patterns.
- TUI pane reload via `pkill -SIGUSR2` must still work as before.

## Risks

- tmux `window-style`/`window-active-style` interaction with focus state may require a workaround (e.g., select-pane to force tmux style re-evaluation).
