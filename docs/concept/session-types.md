---
id: concept/session-types
type: concept
scope: global
description: Classification of terminal sessions in TeleClaude.
---

## Purpose

- Classify the session categories used in TeleClaude.

## Inputs/Outputs

- Inputs: session creation commands and launch intents.
- Outputs: human, AI-to-AI, or worktree session behavior.

## Primary flows

### 1. Human Session

- **Initiator**: A human user via Telegram or `telec` CLI.
- **Interaction**: Direct command input, live terminal output.
- **Clutter Control**: Active cleanup of inputs and feedback messages.

### 2. AI-to-AI Session

- **Initiator**: An AI agent via MCP tools (`teleclaude__start_session`).
- **Interaction**: Programmatic message passing, stop events with summaries.
- **Identification**: Annotated in Telegram (e.g., `macbook/claude -> workstation/claude`).
- **Clutter Control**: Skips feedback messages (listeners receive summaries directly).

### 3. Worktree Session

- **Initiator**: Agents working on specific todos using git worktrees.
- **Isolation**: Uses a separate `teleclaude.db` and dedicated project directory to avoid polluting main state.

## Invariants

- Session type is determined at creation and remains stable.

## Failure modes

- Misclassified sessions cause incorrect UX cleanup and routing.
