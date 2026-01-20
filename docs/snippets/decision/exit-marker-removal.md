---
id: teleclaude/decision/exit-marker-removal
type: decision
scope: project
description: Decision to detect command completion via shell readiness instead of exit markers.
requires:
  - ../concept/shell-readiness.md
---

Decision
- Stop appending exit markers to commands and detect completion by checking shell readiness.

Rationale
- Avoids altering user commands and output streams.
- Works with interactive shells and agents without injecting sentinel strings.

Consequences
- tmux pane command detection must remain reliable across shells.
- Output polling depends on accurate shell name resolution.
