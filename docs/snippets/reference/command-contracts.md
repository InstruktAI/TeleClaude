---
id: teleclaude/reference/command-contracts
type: reference
scope: project
description: Command contract highlights for session creation, messaging, and agent control.
requires: []
---

Reference
- new_session requires project_path; launch_intent selects EMPTY, AGENT, AGENT_THEN_MESSAGE, or AGENT_RESUME.
- agent_restart requires session_id and resumes using stored native_session_id.
- message requires session_id and text; it injects text and starts output polling.
- cancel/cancel2x/kill send SIGINT/SIGINT/SIGKILL to the tmux pane.
