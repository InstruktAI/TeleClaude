# AGENTS.md

## Purpose

This file provides guidance to agents when working with code in this repository.

## Required reads

- @docs/project/baseline.md

## TUI work

- After any TUI code change, send SIGUSR2 to the running TUI to reload. (SIGUSR1 is reserved for appearance/theme refresh.)
  ```bash
  pkill -SIGUSR2 -f -- "-m teleclaude.cli.telec$"
  ```
  The `$` anchor ensures only the TUI process is matched, not `telec watch` or other Python processes.
- Do not restart the daemon and do not instruct the user to restart telec.
- Verify the change in the TUI after reload.
