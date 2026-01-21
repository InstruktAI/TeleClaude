---
id: teleclaude/reference/command-contracts
type: reference
scope: project
description: Command contract highlights for session creation, messaging, and agent control.
requires: []
---

## What it is

- Command contract highlights for session creation, messaging, and agent control.

## Canonical fields

- `new_session`: requires `project_path`; `launch_intent` selects `EMPTY`, `AGENT`, `AGENT_THEN_MESSAGE`, or `AGENT_RESUME`.
- `agent_restart`: requires `session_id`; resumes using stored `native_session_id`.
- `message`: requires `session_id` and `text`; injects text and starts output polling.
- `run_agent_command`: requires `session_id` and raw agent payload.
- `keys`: requires `session_id`, key name, and optional args.
- `cancel`/`cancel2x`/`kill`: send SIGINT/SIGINT/SIGKILL to the tmux pane.
- `handle_voice`: requires `session_id` and a local audio file path; transcribed text is forwarded as a message.
- `handle_file`: requires `session_id`, file path, and filename; the file path is injected into the session.

## Allowed values

- Enumerated command fields (like `launch_intent`) must match the command definitions.

## Known caveats

- Commands are rejected if the session does not exist or is closed.
