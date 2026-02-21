# Requirements: themed-primary-color

## Goal

Introduce a warm primary color (Claude's orange) into the Textual theme system so that structural UI elements (focus borders, scrollbar accents, selection highlights) reflect agent character at higher pane theming carousel levels, while maintaining neutral grays at the peaceful level. Also fix the standalone editor's missing theme registration that causes blue Textual defaults to leak through.

## Scope

### In scope:

- Create agent-variant Textual themes (`teleclaude-dark-agent`, `teleclaude-light-agent`) with Claude-orange primary
- Switch active Textual theme when the carousel crosses the peaceful/agent boundary
- Register themes in the standalone `EditorApp` with CLI flag for active theme
- Both dark and light mode variants

### Out of scope:

- Agent-specific session row colors (those use `resolve_style()` — unchanged)
- Tmux pane background tinting (unchanged)
- Neutral structural gradient variables (`$neutral-*` — unchanged)
- Per-agent primary colors (only Claude orange as the universal warm primary)

## Success Criteria

- [ ] Peaceful level (0): focus borders on TextArea, Input, Select, Button are gray (`#808080`)
- [ ] Agent levels (1-4): focus borders show Claude's warm orange (`#d7af87` dark / `#875f00` light)
- [ ] Standalone editor matches the main TUI's active theme (no blue outlines ever)
- [ ] Cycling the carousel toggles warm/neutral theme smoothly without flicker
- [ ] Both dark and light mode variants render correctly
- [ ] Existing TCSS rules that reference `$connector`, `$input-border` etc. still work (no regressions)

## Constraints

- Theme objects must be importable from both `app.py` and `editor.py` without circular imports
- The editor subprocess receives theme selection via CLI argument (it has no IPC to the main TUI)
- `$accent` stays gray across all levels — footer keys remain neutral
- No changes to the pane theming carousel cycle order or level semantics

## Risks

- Textual's auto-generated variables from `$primary` may affect widgets in unexpected ways (e.g., `$block-cursor-background`, `$primary-background`). Mitigate by testing all interactive widgets at both peaceful and agent levels.
