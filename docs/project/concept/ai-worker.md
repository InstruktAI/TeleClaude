---
description: 'The role of an AI agent session in the TeleClaude network.'
id: 'project/concept/ai-worker'
scope: 'global'
type: 'concept'
---

# Ai Worker — Concept

## What

Role of an AI agent session in the TeleClaude network.

1. **Execution**: Performs tasks (coding, testing, analysis) in a dedicated tmux session.
2. **Collaboration**: Uses TeleClaude command surfaces (`telec` and daemon APIs) to delegate sub-tasks to other workers or computers.
3. **Communication**:
   - Responds to `caller_session_id` annotations.
   - Provides turn-summaries for the Telegram topic.
   - Emits stop events via the hook system.
4. **Reporting**: Surfaces findings, risks, and next steps in a structured way.

## Why

Operates within the provided `project_dir` and `subdir`, and follows the command pipeline for persistent state changes.
