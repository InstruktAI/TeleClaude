---
description: Mechanism for real-time terminal output capture and streaming.
id: architecture/output-polling
scope: project
type: architecture
---

# Output Polling Architecture — Architecture

## Purpose

- Capture and stream real-time output from tmux panes to UI adapters without blocking the main event loop.

## Inputs/Outputs

- Inputs: tmux pane output.
- Outputs: `OutputEvent` emissions routed to adapters.

## Components

1. **OutputPoller**: A per-session worker that reads from the tmux output buffer.
2. **PollingCoordinator**: Manages the collection of pollers and ensures they start/stop with the session lifecycle.
3. **Dual Mode**:
   - **Human Mode**: Raw output streaming for manual sessions.
   - **AI Mode**: Smart output capture for agent-to-agent sessions, detecting turn completion.

## Primary flows

1. **Read**: Poller executes `tmux capture-pane`.
2. **Diff**: Only new lines since the last read are captured.
3. **Emit**: `OutputEvent` is sent to the `EventBus`.
4. **Broadcast**: `AdapterClient` routes the event to all active observers (Telegram, WS, MCP).

## Invariants

- Pollers MUST NOT run for closed sessions.
- Polling frequency is dynamically adjusted based on session activity.

## Failure modes

- Stuck pollers result in stale UI output until restarted.
