# Bug: Config wizard: wrong pane, hardcoded colors, missing features, poor UX

## Symptom

Config wizard: wrong pane, hardcoded colors, missing features, poor UX

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-03

## Investigation

Traced four independent issues across three files:

1. **Wrong pane**: `_run_tui_config_mode` in `telec.py:1210` passed `start_view=3`, which maps to the "jobs" tab. The config tab is at index 4.

2. **Hardcoded colors**: `config.py:40` defined `_NORMAL = Style(color="#d0d0d0")` as a module-level constant with a dark-mode-only hex value. In light mode this produces near-invisible text on a light background. Additionally, `_appearance_refresh` in `app.py` refreshed `SessionRow`, `TodoRow`, `Banner`, and `BoxTabBar` but not `ConfigContent`, so dark/light mode switches would not update the config view.

3. **Missing feature — guided mode not wired**: `_run_tui(start_view=..., config_guided=guided)` in `telec.py:1180` accepted `config_guided` but never passed it to `TelecApp`. `TelecApp.__init__` had no `config_guided` parameter. So `telec config wizard` never activated guided mode. Furthermore, the wizard command itself called `_run_tui_config_mode(guided=False)`, suppressing guided mode even if wiring had existed.

4. **Poor UX**: All of the above compound — the wizard opened on the wrong tab, displayed wrong colors in light mode, and never entered guided mode (the defining behavior of a "wizard").

## Root Cause

- `telec.py:1210`: `start_view=3` off-by-one (should be 4).
- `telec.py:1180`: `config_guided` silently dropped — not forwarded to `TelecApp`.
- `telec.py:2995`: `guided=False` on the wizard command — should be `True`.
- `config.py:40`: `_NORMAL` hardcoded to dark-mode color, computed at import time, not render time.
- `app.py`: `_appearance_refresh` missing `ConfigContent` refresh.

## Fix Applied

**`teleclaude/cli/telec.py`**:

- `_run_tui_config_mode`: `start_view=3` → `start_view=4`
- `_run_tui`: forward `config_guided` to `TelecApp`
- `_handle_config` wizard branch: `guided=False` → `guided=True`

**`teleclaude/cli/tui/app.py`**:

- `TelecApp.__init__`: added `config_guided: bool = False` parameter; stored as `self._config_guided`
- `on_mount`: added `call_after_refresh(self._activate_config_guided_mode)` when `_config_guided` is True
- Added `_activate_config_guided_mode` method: queries `#config-view` and calls `action_toggle_guided_mode()`
- `_appearance_refresh`: added `ConfigContent` refresh after dark/light mode switch

**`teleclaude/cli/tui/views/config.py`**:

- Replaced `_NORMAL = Style(color="#d0d0d0")` with `_normal_style()` function that calls `get_neutral_color("highlight")` at render time
- Updated all 5 call sites to use `_normal_style()`
- Added `get_neutral_color` to imports
