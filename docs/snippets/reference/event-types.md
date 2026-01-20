---
id: teleclaude/reference/event-types
type: reference
scope: project
description: TeleClaude event names used between adapters, daemon, and clients.
requires: []
---

Reference
- command: adapter command ingress for daemon handling.
- session_started: session created and ready.
- session_updated: session metadata updated.
- session_closed: session closed and cleaned up.
- agent_event: agent lifecycle wrapper with payload types (session_start, prompt, stop, notification, session_end, error).
- error: command or system failure.
