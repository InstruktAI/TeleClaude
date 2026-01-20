---
id: teleclaude/concept/shell-readiness
type: concept
scope: project
description: How TeleClaude detects command completion without explicit exit markers.
requires: []
---

Purpose
- Explain command completion detection based on tmux pane state.

Concept
- TeleClaude treats a command as complete when the tmux pane returns to the user's shell.
- Completion detection compares the current tmux command to the resolved shell name.

Implications
- Exit markers are not appended to user commands.
- Output polling stops when the shell resumes control.
