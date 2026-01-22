---
description: Tmux session orchestration, input injection, and per-session temp directories.
id: teleclaude/architecture/tmux-management
requires:
  - teleclaude/concept/shell-readiness
scope: project
type: architecture
---

## Purpose

- Describe how TeleClaude manages tmux sessions and input injection.

## Inputs/Outputs

- Inputs: commands, control keys, and session creation requests.
- Outputs: tmux sessions, captured output, and shell-ready signals.

## Primary flows

- Session names are derived from session_id with a stable prefix.
- Each session gets a dedicated TMPDIR to avoid filesystem watcher issues.
- tmux commands enforce timeouts to prevent hangs.

## Invariants

- Session tmp directories are created under ~/.teleclaude/tmp/sessions by default.
- Shell readiness is determined by comparing the tmux command to the user shell.

## Failure modes

- tmux command timeouts can leave sessions unresponsive until restarted.
