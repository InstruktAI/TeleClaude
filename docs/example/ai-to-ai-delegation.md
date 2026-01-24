---
id: example/ai-to-ai-delegation
type: example
scope: global
description: Code example of a Master AI delegating a task to a Worker AI.
---

## What it is

- Example of a master AI delegating a task to a worker AI over MCP.

## Canonical fields

- Tool calls and parameters used for delegation.

```python
# 1. Discover the server
teleclaude__list_computers()
# -> [{"name": "server1", "status": "online"}]

# 2. Start the worker session
teleclaude__start_session(
    computer="server1",
    project_path="/home/user/apps/TeleClaude",
    title="Verification run",
    message="Please run 'make test' and summarize failures.",
    agent="claude"
)
# -> Returns session_id: "test-abc-123"

# 3. Wait for notification...
# Master receives TurnCompleted event with summary

# 4. Review and cleanup
teleclaude__end_session(computer="server1", session_id="test-abc-123")
```

## Allowed values

- `computer` must match a listed computer name.

## Known caveats

- Use `teleclaude__list_projects` before starting a session to select a trusted project path.
