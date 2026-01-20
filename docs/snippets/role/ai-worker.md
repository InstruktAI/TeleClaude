---
id: role/ai-worker
type: role
scope: global
description: The role of an AI agent session in the TeleClaude network.
---

# Role: AI Worker (Agent)

## Responsibilities
1. **Execution**: Performs tasks (coding, testing, analysis) in a dedicated tmux session.
2. **Collaboration**: Uses MCP tools to delegate sub-tasks to other workers or computers.
3. **Communication**:
   - Responds to `caller_session_id` annotations.
   - Provides turn-summaries for the Telegram topic.
   - Emits stop events via the hook system.

## Boundaries
- Operates within the `project_dir` and `subdir` provided at startup.
- Injected with `TELECLAUDE_SESSION_ID` and `TELECLAUDE_COMPUTER_NAME`.
