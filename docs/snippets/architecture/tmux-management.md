---
id: architecture/tmux-management
description: Tmux session orchestration, input injection, and per-session temporary directories.
type: architecture
scope: project
requires: []
---

# Tmux Management

## Purpose
- Provide stateless utilities for creating tmux sessions and sending input/control keys.
- Isolate each session with a dedicated TMPDIR to avoid filesystem watcher issues.

## Inputs/Outputs
- Inputs: session IDs, tmux session names, working directories, key commands.
- Outputs: tmux sessions, captured pane output, process signals.

## Invariants
- Per-session TMPDIR is created under `~/.teleclaude/tmp/sessions/<safe-id>` and contains `teleclaude_session_id`.
- Tmux session names are owned by TeleClaude when prefixed with `tc_`.
- Subprocess calls are guarded by timeouts; failures raise structured errors.

## Primary Flows
- Create: build tmux session in target working dir and wire pipe-pane output.
- Input: send keys, control sequences, or signals to active tmux pane.
- Inspect: capture pane output and check session/process liveness.

## Failure Modes
- Subprocess timeouts kill hung tmux commands and raise errors.
- Missing tmux sessions short-circuit polling and trigger cleanup upstream.
