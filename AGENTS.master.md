# AGENTS.md

## Purpose

This file provides guidance to agents when working with code in this repository.

## Required reads

- @docs/project/baseline.md
- @docs/project/baseline-progressive.md

## External instrumentation

The TUI is instrumented by the dotfiles repository at `~/Sync/dotfiles/terminal/`. Key interactions:

- **Appearance sync:** `appearance.py reload` sends SIGUSR1 to the TUI when OS dark/light mode changes. The TUI handles this by saving state and restarting (same as SIGUSR2). The appearance script also sets tmux `@appearance_mode` and syncs agent CLI themes.
- **Agent restart:** tmux `bind R` triggers agent restart via the daemon API.
- See `~/Sync/dotfiles/terminal/AGENTS.md` for full architecture.

## TUI work

- After any TUI code change, send SIGUSR2 to the running TUI to reload. (SIGUSR1 is reserved for appearance/theme refresh.)
  ```bash
  pkill -SIGUSR2 -f -- "-m teleclaude.cli.telec$"
  ```
  The `$` anchor ensures only the TUI process is matched, not `telec watch` or other Python processes.
- Do not restart the daemon and do not instruct the user to restart telec.
- Verify the change in the TUI after reload.
