---
id: teleclaude/concept/command-modes
type: concept
scope: project
description: Sync, async, and hybrid command response modes used across TeleClaude interfaces.
requires: []
---

Purpose
- Capture the command response modes used by API and transport workflows.

Modes
- Sync: returns full result immediately within SLA.
- Async: returns acceptance immediately; completion signaled via events.
- Hybrid: returns identifiers immediately; completion signaled via events.

Signals
- session_started, session_updated, session_closed, and agent_event are the primary completion signals.
