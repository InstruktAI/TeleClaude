---
id: project/example/ai-to-ai-delegation
type: example
scope: global
description: Code example of a Master AI delegating a task to a Worker AI.
---

# Ai To Ai Delegation — Example

## Scenario

Demonstrates a master AI delegating a task to a worker AI over MCP.

## Steps

```python
teleclaude__list_computers()

teleclaude__start_session(
    computer="server1",
    project_path="/home/user/apps/TeleClaude",
    title="Verification run",
    message="Please run 'make test' and summarize failures.",
    agent="claude"
)

teleclaude__end_session(computer="server1", session_id="test-abc-123")
```

## Outputs

- Worker session started on the target computer.
- Task completed and summarized.
- Session ended cleanly.

## Notes

- `computer` must match a listed computer name.
- Use `teleclaude__list_projects` before starting a session to select a trusted project path.
