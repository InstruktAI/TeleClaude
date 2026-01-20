---
id: architecture/adapter-client
description: Unified adapter router for UI and transport components, plus event bus for daemon communication.
type: architecture
scope: project
requires:
  - event-model.md
  - ux-message-cleanup.md
---

# Adapter Client

## Purpose
- Provides a single interface for daemon/MCP to talk to UI adapters and transports.
- Owns adapter lifecycle and emits typed events through the event bus.

## Inputs/Outputs
- Inputs: adapter start/stop, UI events, transport messages.
- Outputs: send/edit/delete UI messages, create/update/delete channels, broadcast output updates, remote requests.

## Invariants
- Adapters are registered only after successful start; registry contains only healthy adapters.
- Origin UI adapter is preferred for session-scoped actions; observers receive best-effort broadcasts.
- Missing Telegram thread errors trigger an automatic channel recovery attempt.

## Primary Flows
- Start: conditionally start Telegram (env-based) and Redis transport (config-based).
- Routing: map session origin to the correct UI adapter; broadcast to observers when enabled.
- Messaging: send_message can track ephemerals; feedback messages clean old feedback first.

## Failure Modes
- Adapter failures are logged per adapter; origin failures are surfaced to callers.
- Broadcast failures do not block origin success; missing Telegram thread triggers retry.
