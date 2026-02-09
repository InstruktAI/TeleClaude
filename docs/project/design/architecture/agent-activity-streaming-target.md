---
id: 'project/design/architecture/agent-activity-streaming-target'
type: 'design'
scope: 'project'
description: 'Target architecture for unified agent activity streaming across Telegram, TUI, and Web clients.'
---

# Agent Activity Streaming Target — Design

## Purpose

Define the intended outbound architecture before building the web interface:

- one canonical agent activity stream contract,
- one fan-out distribution boundary,
- adapter-edge protocol translation,
- clear separation between state snapshots and high-frequency output streaming.

This document is a target-state blueprint, not a description of current implementation.

## Inputs/Outputs

**Inputs:**

- Agent lifecycle events (`user_prompt_submit`, `agent_output_update`, `agent_output_stop`) from hook and polling paths.
- Session metadata needed for routing (session id, origin metadata, ownership/visibility fields).

**Outputs:**

- Routed outbound stream events to UI consumers (Telegram, TUI, Web).
- State/snapshot updates through cache/API websocket for low-frequency UI state.

## Invariants

- **Single canonical outbound event contract** for agent activity.
- **One routing/fan-out boundary** (AdapterClient/distributor layer).
- **No UI formatting in AgentCoordinator**.
- **State channel and stream channel stay separate**.
- **Consumer isolation**: one slow consumer cannot block others.

## Primary flows

### 1. Target dataflow

```text
INPUT (already in place)
UI/API/MCP -> commands -> core handlers -> tmux/agents

OUTPUT (target)
hook + poller events -> AgentCoordinator (activity hub)
                   -> Agent Activity Stream Publisher
                   -> AdapterClient / Output Distributor
                      -> Telegram Adapter
                      -> Stream Gateway Adapter
                         -> TUI stream consumer
                         -> Web stream consumer

STATE (existing pattern)
session updates -> DaemonCache -> API websocket -> UI state views
```

### 2. Event contract

Canonical outbound activity events:

- `user_prompt_submit`
- `agent_output_update`
- `agent_output_stop`

Session/cache updates remain separate (`session_updated`) and are not used as the high-frequency output stream.

### 3. Adapter-edge translation

- Telegram adapter: maps canonical events to message/edit operations.
- TUI stream consumer: consumes stream transport for rich live output.
- Web stream consumer: consumes same stream; optional SSE translation for AI SDK format happens at adapter edge.

## Failure modes

- **Consumer backpressure**: bounded per-consumer queues with drop/coalesce policy for `agent_output_update`.
- **Consumer disconnect**: stream consumer reconnects without affecting other consumers.
- **Distributor overload**: publishing stays non-blocking; slow sinks are isolated and observable.
- **Contract drift**: adapters diverge from canonical event contract; requires contract tests at distributor boundary.
