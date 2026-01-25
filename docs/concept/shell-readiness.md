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
