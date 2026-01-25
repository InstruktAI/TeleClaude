---
description: Mechanism for real-time terminal output capture and streaming.
id: architecture/output-polling
scope: project
type: architecture
---

# Output Polling — Architecture

## Purpose

- Capture and stream real-time output from tmux panes to UI adapters without blocking the main event loop.

- Inputs: tmux pane output.
- Outputs: `OutputEvent` emissions routed to adapters.

1. **OutputPoller**: A per-session worker that reads from the tmux output buffer.
2. **PollingCoordinator**: Manages the collection of pollers and ensures they start/stop with the session lifecycle.
3. **Dual Mode**:
   - **Human Mode**: Raw output streaming for manual sessions.
   - **AI Mode**: Smart output capture for agent-to-agent sessions, detecting turn completion.

4. **Read**: Poller executes `tmux capture-pane`.
5. **Diff**: Only new lines since the last read are captured.
6. **Emit**: `OutputEvent` is sent to the `EventBus`.
7. **Broadcast**: `AdapterClient` routes the event to all active observers (Telegram, WS, MCP).

- Pollers MUST NOT run for closed sessions.
- Polling frequency is dynamically adjusted based on session activity.

- Stuck pollers result in stale UI output until restarted.

- TBD.

- TBD.

- TBD.

- TBD.

## Inputs/Outputs

- TBD.

## Invariants

- TBD.

## Primary flows

- TBD.

## Failure modes

- TBD.
