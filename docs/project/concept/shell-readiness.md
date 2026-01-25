---
id: teleclaude/concept/shell-readiness
type: concept
scope: project
description: How TeleClaude detects command completion without explicit exit markers.
---

# Shell Readiness — Concept

## Purpose

- Explain command completion detection based on tmux pane state.

- Inputs: tmux pane command state.
- Outputs: completion signal when shell resumes control.

- TeleClaude treats a command as complete when the tmux pane returns to the user's shell.
- Completion detection compares the current tmux command to the resolved shell name.

- Exit markers are not appended to user commands.
- Output polling stops when the shell resumes control.

- Misidentified shell names can cause premature or delayed completion detection.

## Inputs/Outputs

- **Inputs**: tmux pane command state.
- **Outputs**: completion signal when shell resumes control.

## Invariants

- Shell readiness is inferred, not explicitly signaled by the process.
- Only the foreground command determines readiness.

## Primary flows

- Poll tmux pane current command → compare to configured shell → mark ready when matched.

## Failure modes

- Incorrect shell configuration causes stuck or early completion.
- Long-running shell wrappers hide the real shell command name.
