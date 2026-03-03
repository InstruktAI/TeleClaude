# Demo: Config Wizard Overhaul

Four critical bug fixes that made `telec config wizard` actually work: correct tab, guided mode wiring, adaptive colors, and live theme refresh.

## 1. CLI command exists and accepts wizard subcommand

```bash
cd /Users/Morriz/Workspace/InstruktAI/TeleClaude && telec config wizard --help 2>&1 | head -5
```

Verify: output should show usage information for the config wizard command.

## 2. Start view is Config tab (index 4), not Jobs tab (index 3)

```bash
cd /Users/Morriz/Workspace/InstruktAI/TeleClaude && grep -n 'start_view=4' teleclaude/cli/telec.py
```

Verify: `_run_tui_config_mode` passes `start_view=4` to `_run_tui`.

## 3. Guided mode parameter is wired through the stack

```bash
cd /Users/Morriz/Workspace/InstruktAI/TeleClaude && grep -n 'config_guided' teleclaude/cli/telec.py teleclaude/cli/tui/app.py | head -20
```

Verify: `config_guided` appears in telec.py (CLI layer), app.py (TUI app constructor), and app.py (on_mount activation).

## 4. No hardcoded colors in config view

```bash
cd /Users/Morriz/Workspace/InstruktAI/TeleClaude && grep -c '#d0d0d0' teleclaude/cli/tui/views/config.py
```

Verify: output should be `0` — no hardcoded color constants remain.

## 5. Adaptive color function exists

```bash
cd /Users/Morriz/Workspace/InstruktAI/TeleClaude && grep -n '_normal_style' teleclaude/cli/tui/views/config.py | head -5
```

Verify: `_normal_style()` function is defined and uses `get_neutral_color`.

## 6. Config view included in theme refresh

```bash
cd /Users/Morriz/Workspace/InstruktAI/TeleClaude && grep -n 'ConfigContent' teleclaude/cli/tui/app.py | head -5
```

Verify: `ConfigContent` appears in `_appearance_refresh()` method.

## 7. Unit tests validate the wiring

```bash
cd /Users/Morriz/Workspace/InstruktAI/TeleClaude && python -m pytest tests/unit/test_telec_cli.py -k "config_wizard or config_mode" -v 2>&1 | tail -10
```

Verify: tests for guided mode activation and start_view=4 pass.

## 8. Guided TUI walkthrough

<!-- skip-validation: requires live terminal to observe guided mode activation and color adaptation -->

**Guided step for the presenter:**

1. Launch `telec config wizard` in a terminal.
2. Observe: TUI opens directly on the **Config** tab (not Jobs).
3. Observe: Guided mode activates automatically with step-by-step prompts.
4. Switch theme (dark/light) and observe: config panel colors update live.
