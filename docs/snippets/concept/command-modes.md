---
id: teleclaude/concept/command-modes
type: concept
scope: project
description: Sync, async, and hybrid command response modes used across TeleClaude interfaces.
requires: []
---

## Purpose

- Capture the command response modes used by API and transport workflows.

## Inputs/Outputs

- Inputs: command requests over API, MCP, or adapters.
- Outputs: synchronous responses or asynchronous event signals.

## Primary flows

- Sync: returns full result immediately within SLA.
- Async: returns acceptance immediately; completion signaled via events.
- Hybrid: returns identifiers immediately; completion signaled via events.

Signals

- session_started, session_updated, session_closed, and agent_event are the primary completion signals.

## Invariants

- Asynchronous modes always publish a completion signal.

## Failure modes

- Missing completion signals leave callers waiting indefinitely.
