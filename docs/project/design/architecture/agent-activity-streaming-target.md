---
description: 'Target architecture for unified agent activity streaming across Telegram and TUI clients.'
visibility: 'public'
---

# Agent Activity Streaming Target — Design

## Purpose

<!-- planned-change:strip-dead-web-remnants -->
Define the intended outbound architecture before building the web interface:
<!-- change:strip-dead-web-remnants -->
Define the intended outbound architecture for agent activity streaming:
<!-- /planned-change:strip-dead-web-remnants -->

- one canonical agent activity stream contract,
- one fan-out distribution boundary,
- adapter-edge protocol translation,
- clear separation between state snapshots and high-frequency output streaming.

This document is a target-state blueprint, not a description of current implementation.

## Inputs/Outputs

**Inputs:**

- Agent lifecycle events (`user_prompt_submit`, `agent_output_update`, `agent_stop`) from hook and polling paths.
- Session metadata needed for routing (session id, origin metadata, ownership/visibility fields).

**Outputs:**

<!-- planned-change:strip-dead-web-remnants -->
- Routed outbound stream events to UI consumers (Telegram, TUI, Web).
<!-- change:strip-dead-web-remnants -->
- Routed outbound stream events to UI consumers (Telegram, TUI).
<!-- /planned-change:strip-dead-web-remnants -->
- State/snapshot updates through cache/API websocket for low-frequency UI state.

## Invariants

- **Single canonical outbound event contract** for agent activity.
- **One routing/fan-out boundary** (AdapterClient/distributor layer).
- **No UI formatting in AgentCoordinator**.
- **State channel and stream channel stay separate**.
- **Consumer isolation**: one slow consumer cannot block others.

## Primary flows

### 1. Target dataflow

<!-- planned-change:strip-dead-web-remnants -->
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
<!-- change:strip-dead-web-remnants -->
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

STATE (existing pattern)
session updates -> DaemonCache -> API websocket -> UI state views
```
<!-- /planned-change:strip-dead-web-remnants -->

### 2. Event contract

Canonical outbound activity events (defined in `teleclaude/core/activity_contract.py`):

- `user_prompt_submit` — user turn start signal
- `agent_output_update` — agent working (tool initiated or completed)
- `agent_stop` — agent turn complete

These map from agent hook events via `HOOK_TO_CANONICAL` in the contract module.
All canonical events carry `message_intent: ctrl_activity` and `delivery_scope: CTRL`.
The hook-level event type is preserved in `hook_event_type` for consumer compatibility.

Session/cache updates remain separate (`session_updated`) and are not used as the high-frequency output stream.

### 3. Adapter-edge translation

- Telegram adapter: maps canonical events to message/edit operations.
- TUI stream consumer: consumes stream transport for rich live output.

## Failure modes

- **Consumer backpressure**: bounded per-consumer queues with drop/coalesce policy for `agent_output_update`.
- **Consumer disconnect**: stream consumer reconnects without affecting other consumers.
- **Distributor overload**: publishing stays non-blocking; slow sinks are isolated and observable.
- **Contract drift**: adapters diverge from canonical event contract; requires contract tests at distributor boundary.
