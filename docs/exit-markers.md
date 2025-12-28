# Shell-Readiness Completion Detection

## Overview

TeleClaude no longer appends exit markers to commands. Completion is detected by
checking whether the tmux pane has returned to the user's shell.

## How It Works

- `terminal_bridge.is_process_running()` compares `#{pane_current_command}` with
  the user's shell (`$SHELL`, resolved at import time).
- `OutputPoller` stops polling when the foreground command is the shell and
  emits a `ProcessExited` event for UI completion status.

## Troubleshooting

- If polling never stops, verify `#{pane_current_command}` and `_SHELL_NAME`.
- For uncommon shells, ensure `$SHELL` resolves correctly on the host.
