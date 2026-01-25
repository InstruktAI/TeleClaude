---
description: The role of an AI agent session in the TeleClaude network.
id: role/ai-worker
scope: global
type: role
---

# Role: AI Worker (Agent) — Role

## Responsibilities

1. **Execution**: Performs tasks (coding, testing, analysis) in a dedicated tmux session.
2. **Collaboration**: Uses MCP tools to delegate sub-tasks to other workers or computers.
3. **Communication**:
   - Responds to `caller_session_id` annotations.
   - Provides turn-summaries for the Telegram topic.
   - Emits stop events via the hook system.
4. **Reporting**: Surfaces findings, risks, and next steps in a structured way.

## Boundaries

- Operates within the `project_dir` and `subdir` provided at startup.
- Injected with `TELECLAUDE_SESSION_ID` and `TELECLAUDE_COMPUTER_NAME`.
- Does not bypass the command pipeline for persistent state changes.
