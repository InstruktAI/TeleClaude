---
id: example/ai-to-ai-delegation
type: example
scope: global
description: Code example of a Master AI delegating a task to a Worker AI.
---

# Example: AI-to-AI Delegation

## Scenario
A Master AI on a laptop wants a Worker AI on a server to run a test suite.

## Tool Calls
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