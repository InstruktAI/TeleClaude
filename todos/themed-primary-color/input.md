# Input: themed-primary-color

## Problem

The TUI's Textual theme uses `primary="#808080"` (gray) for all pane theming carousel levels. This means structural UI elements — focus borders, TextArea outlines, scrollbar accents, selection backgrounds — are always neutral gray, even when the carousel is at agent-colored levels (1, 3, 4).

Additionally, the standalone `EditorApp` (`teleclaude/cli/editor.py`) does not register any custom Textual theme at all, so it falls back to Textual's built-in default which uses `#0178d4` (blue) for `$primary`. This causes a visible blue focus outline on the TextArea when the editor is launched for preview (spacebar) or edit.

## Intended Outcome

Introduce a warm primary color (Claude's orange) for the Textual theme that activates when the pane theming carousel is at agent-colored levels. At peaceful level (0), the theme stays neutral gray.

### Color Mapping

- **Peaceful (level 0)**: `$primary` = `#808080` (current gray), `$secondary` = `#626262` (current gray)
- **Agent levels (1-4)**: `$primary` = `#d7af87` (claude-normal dark / `#875f00` light), `$secondary` = `#af875f` (claude-muted dark / `#af875f` light)
- **`$accent`**: stays `#585858` (gray) across all levels — footer keys and subtle accents remain neutral

### Architecture

1. **Two dark + two light themes**: `teleclaude-dark` (peaceful) and `teleclaude-dark-agent` (warm primary), same for light variants.
2. **Carousel handler updates**: `action_cycle_pane_theming` additionally switches the active Textual theme name when crossing the peaceful/agent boundary.
3. **EditorApp theming**: The standalone editor registers and uses the same themes. It receives the active theme mode via a CLI flag (e.g., `--theme teleclaude-dark-agent`) so it matches the main TUI.

### What This Affects

Textual generates these CSS variables from `$primary`:

- `$border` — focus outlines on all widgets (TextArea, Input, Select, Button)
- `$block-cursor-background` — list selection highlight
- `$scrollbar-*` — scrollbar accent coloring
- `$primary-background` — subtle primary-tinted backgrounds

With claude-orange as primary, focus borders become warm instead of gray, giving the UI agent-specific character at higher carousel levels.

### What This Does NOT Affect

- Agent-specific session row colors (those use the `resolve_style()` / `resolve_color()` system — unchanged)
- Pane background tinting (tmux-level, unchanged)
- The neutral structural gradient (`$neutral-*` variables — unchanged)

## Context

- Theme definitions: `teleclaude/cli/tui/app.py` lines 75-170 (`_TELECLAUDE_DARK_THEME`, `_TELECLAUDE_LIGHT_THEME`)
- Pane theming carousel: `teleclaude/cli/tui/theme.py` lines 318-405
- Carousel handler: `teleclaude/cli/tui/app.py` `action_cycle_pane_theming()`
- Editor: `teleclaude/cli/editor.py` — separate `App` subprocess, no theme registered
- Textual's `$border` variable: generated from `Theme.primary` in `textual/design.py`

## Success Criteria

1. At peaceful level (0): focus borders on TextArea, Input, Select, Button remain gray
2. At agent levels (1-4): focus borders show Claude's warm orange
3. The standalone editor matches the main TUI's active theme (no blue outlines)
4. Cycling the carousel toggles the warm/neutral theme smoothly
5. Both dark and light mode variants work correctly
