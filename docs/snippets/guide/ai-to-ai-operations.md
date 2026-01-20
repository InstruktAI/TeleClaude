---
description: Recommended flow for delegating work using TeleClaude MCP tools.
id: teleclaude/guide/ai-to-ai-operations
requires:
- reference/mcp-tools
- concept/session-types
scope: project
type: guide
---

Guide
- List computers to confirm the target is online before delegating.
- List projects to choose a trusted project path on the target.
- Start a session with a clear title and initial instruction.
- Use send_message for follow-ups and get_session_data for status checks.
- Stop notifications when you no longer need updates; end sessions when work completes.
- If a worker nears context limits, ask for a summary, then end and restart a fresh session.