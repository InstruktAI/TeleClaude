---
id: teleclaude/example/ai-to-ai-delegation
type: example
scope: project
description: Example MCP flow to delegate a task to a remote computer.
requires:
  - ../reference/mcp-tools.md
  - ../concept/session-types.md
---

Example
- List online computers.
- Start a session on a remote computer.
- Send a follow-up message and read the transcript.

Sample
- teleclaude__list_computers()
- teleclaude__start_session(computer="workstation", project="/home/user/app", title="Run tests", message="Run the test suite")
- teleclaude__send_message(computer="workstation", session_id="<id>", message="Report failures")
- teleclaude__get_session_data(computer="workstation", session_id="<id>")
