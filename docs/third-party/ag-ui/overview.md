# AG-UI Protocol Overview

## What it is

AG-UI (Agent-User Interaction Protocol) is an open, lightweight, event-based protocol by CopilotKit that standardizes how AI agents connect to user-facing applications. It defines a bidirectional event stream over HTTP/SSE/WebSocket for real-time agent-frontend communication.

## Core Concepts

| Concept           | Description                                                                           |
| ----------------- | ------------------------------------------------------------------------------------- |
| **Events**        | 24 typed events covering lifecycle, messages, tool calls, thinking, state, and custom |
| **Shared State**  | Bidirectional state sync between agent and app via snapshots and JSON Patch deltas    |
| **Tool Calls**    | Backend-rendered (visualize tool output) and frontend-executed (typed handoffs)       |
| **Custom Events** | Open-ended extension point for domain-specific data                                   |
| **Runs**          | Scoped execution units with lifecycle (started, finished, error)                      |
| **Steps**         | Sub-divisions within runs for granular progress tracking                              |

## Event Types (24 standard)

### Lifecycle

- `RUN_STARTED`, `RUN_FINISHED`, `RUN_ERROR`
- `STEP_STARTED`, `STEP_FINISHED`

### Text Messages (streaming)

- `TEXT_MESSAGE_START`, `TEXT_MESSAGE_CONTENT`, `TEXT_MESSAGE_END`
- `TEXT_MESSAGE_CHUNK`

### Thinking (agent reasoning visibility)

- `THINKING_START`, `THINKING_END`
- `THINKING_TEXT_MESSAGE_START`, `THINKING_TEXT_MESSAGE_CONTENT`, `THINKING_TEXT_MESSAGE_END`

### Tool Calls

- `TOOL_CALL_START`, `TOOL_CALL_ARGS`, `TOOL_CALL_END`
- `TOOL_CALL_CHUNK`, `TOOL_CALL_RESULT`

### State Management

- `STATE_SNAPSHOT`, `STATE_DELTA`
- `MESSAGES_SNAPSHOT`, `ACTIVITY_SNAPSHOT`, `ACTIVITY_DELTA`

### Extension

- `RAW`, `CUSTOM`

## Transport

Built on HTTP, SSE, and WebSocket. The protocol is transport-agnostic — events are JSON objects that can flow over any bidirectional channel.

## SDKs

- TypeScript (client + server)
- Python (server)
- Kotlin (client + server)

## Ecosystem

- Integrates with Open Agent Specification (Oracle)
- CopilotKit provides React components that consume AG-UI events
- Compatible with LangGraph, WayFlow, and other agent runtimes

## Sources

- https://docs.ag-ui.com/introduction
- https://github.com/ag-ui-protocol/ag-ui
- https://www.copilotkit.ai/ag-ui
- /ag-ui-protocol/ag-ui
- /websites/ag-ui
