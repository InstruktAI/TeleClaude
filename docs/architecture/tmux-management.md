---
description: Tmux session orchestration, input injection, and per-session temp directories.
id: teleclaude/architecture/tmux-management
scope: project
type: architecture
---

# Tmux Management — Architecture

## Purpose

- @docs/concept/shell-readiness

- Describe how TeleClaude manages tmux sessions and input injection.

- Inputs: commands, control keys, and session creation requests.
- Outputs: tmux sessions, captured output, and shell-ready signals.

- Session names are derived from session_id with a stable prefix.
- Each session gets a dedicated TMPDIR to avoid filesystem watcher issues.
- tmux commands enforce timeouts to prevent hangs.

- Session tmp directories are created under ~/.teleclaude/tmp/sessions by default.
- Shell readiness is determined by comparing the tmux command to the user shell.

- tmux command timeouts can leave sessions unresponsive until restarted.

- TBD.

- TBD.

- TBD.

- TBD.

## Inputs/Outputs

- TBD.

## Invariants

- TBD.

## Primary flows

- TBD.

## Failure modes

- TBD.
