---
description: 'How AI agents coordinate using sub-sessions, listeners, and terminal notifications.'
id: 'software-development/concept/ai-to-ai-coordination'
scope: 'domain'
type: 'concept'
---

# AI-to-AI Coordination — Concept

## What

AI-to-AI coordination is the mechanism by which one AI agent (the Initiator) can spawn and control another AI agent (the Worker) to perform a sub-task.

**How it works**

1.  **Dispatch:** The Initiator AI calls the `teleclaude__run_agent_command` tool.
2.  **Creation:** The TeleClaude daemon creates a new sub-session (local or remote) and stores the `initiator_session_id`.
3.  **Registration:** The daemon automatically registers the Initiator as a **Session Listener** for the Worker session.
4.  **Execution:** The Worker agent starts in its own tmux session and executes the requested command.
5.  **Monitoring:** The Initiator AI can monitor the Worker's progress using `teleclaude__get_session_data`.
6.  **Notification:** When the Worker agent stops (e.g., waiting for input or finished), it triggers an `agent_stop` hook.
7.  **Delivery:** The `AgentCoordinator` detects the stop and notifies all listeners by injecting a status message directly into their terminal (via `deliver_listener_message`).

**Key Components**

- **`run_agent_command`:** The tool used to start a Worker.
- **`SessionListener`:** An in-memory registration of an Initiator session watching a Worker session.
- **`AgentCoordinator`:** Orchestrates the flow of events and notifications.
- **`deliver_listener_message`:** Injects `[TeleClaude: Worker Stopped]` notifications into the Initiator's tmux pane.

## Why

This allows for high-fidelity orchestration where the Initiator can "fire and forget" a task and be proactively notified when results are ready, without blocking its own terminal or polluting its own conversation history with sub-task details. It maintains clean context boundaries and enables parallel autonomous execution.
