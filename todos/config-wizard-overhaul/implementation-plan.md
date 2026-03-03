# Implementation Plan: config-wizard-overhaul

## Scope

Bug fix — four independent issues in the config wizard TUI.

## Tasks

1. **Fix wrong pane index** — `telec.py:1210`: `start_view=3` → `start_view=4`
2. **Wire guided mode** — Forward `config_guided` param through `_run_tui` → `TelecApp.__init__` → `on_mount`; set `guided=True` in wizard command
3. **Fix hardcoded colors** — Replace module-level `_NORMAL = Style(color="#d0d0d0")` with `_normal_style()` that reads theme at render time via `get_neutral_color("highlight")`
4. **Fix appearance refresh** — Add `ConfigContent` to `_appearance_refresh` so dark/light mode switches update the config view

## Files Modified

- `teleclaude/cli/telec.py` — tasks 1, 2
- `teleclaude/cli/tui/app.py` — tasks 2, 4
- `teleclaude/cli/tui/views/config.py` — task 3
