---
id: teleclaude/concept/command-modes
type: concept
scope: project
description:
  Sync, async, and hybrid command response modes used across TeleClaude
  interfaces.
---

# Command Modes — Concept

## Purpose

- Capture the command response modes used by API and transport workflows.

- Inputs: command requests over API, MCP, or adapters.
- Outputs: synchronous responses or asynchronous event signals.

- Sync: returns full result immediately within SLA.
- Async: returns acceptance immediately; completion signaled via events.
- Hybrid: returns identifiers immediately; completion signaled via events.

Signals

- session_started, session_updated, and session_closed are the primary completion signals.

- Asynchronous modes always publish a completion signal.

- Missing completion signals leave callers waiting indefinitely.

## Inputs/Outputs

- **Inputs**: command requests over API, MCP, or adapters.
- **Outputs**: synchronous responses or asynchronous event signals.

## Invariants

- Each async command must emit at least one completion signal.
- Sync commands must not exceed configured SLA timeouts.

## Primary flows

- API request → immediate response (sync) or acceptance token (async).
- Event bus publishes completion → adapters notify clients.

## Failure modes

- Missing events cause clients to wait or poll indefinitely.
- Misclassified mode causes timeouts or duplicated responses.
