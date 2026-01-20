---
id: architecture/event-model
description: Typed event contract between adapters and the daemon (commands, lifecycle, agent events, errors).
type: architecture
scope: project
requires: []
---

# Event Model

## Purpose
- Defines the canonical event types that adapters emit and the daemon handles.
- Normalizes command parsing and agent hook payloads into typed contexts.

## Inputs/Outputs
- Inputs: raw command strings from transports, adapter-origin events, agent hook payloads.
- Outputs: typed contexts for command, session lifecycle, agent event, and error handling.

## Invariants
- Command parsing uses shell-like splitting (shlex) to preserve quoted args.
- Event types are a fixed set: command, session_started, session_closed, session_updated, agent_event, error.
- Agent hook event types are normalized before routing (per-agent mapping).

## Primary Flows
- parse_command_string turns raw command text into (command, args).
- Adapters emit typed contexts; daemon dispatches based on event type.

## Failure Modes
- Invalid command strings fall back to simple splitting.
- Unknown event types are ignored by typed handlers.
