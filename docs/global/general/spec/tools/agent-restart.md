---
id: 'general/spec/tools/agent-restart'
type: 'spec'
scope: 'global'
description: 'Canonical self-restart call for reloading synchronized artifacts without losing session continuity.'
---

# Agent Restart Tool — Spec

## What it is

Defines the canonical self-restart API call used by an active agent session to reload newly synced artifacts while preserving conversation continuity.

## Canonical fields

- Transport: local unix socket (`/tmp/teleclaude-api.sock`)
- Endpoint: `POST /sessions/{session_id}/agent-restart`
- Session ID source: `$TMPDIR/teleclaude_session_id`
- Canonical call:

```bash
curl -s --unix-socket /tmp/teleclaude-api.sock \
  -X POST "http://localhost/sessions/$(cat "$TMPDIR/teleclaude_session_id")/agent-restart"
```

- Use when:
  - `telec sync` just updated agent artifacts and the current process needs to reload them.

## Allowed values

- `session_id` must be the current active session ID from `TMPDIR`.
- Method is always `POST`.

## Recognizing a restart (Memento pattern)

An agent cannot feel a restart — but it can read the evidence. The marker sequence is:

1. A tool call to `/sessions/.../agent-restart` in your conversation history.
2. A "rejected" or "error" tool result immediately after (the old process died mid-call).
3. A checkpoint message injected shortly after.

That sequence IS the restart. You ARE the new instance. The old process terminated when the restart executed — from its perspective the tool was "rejected," but it succeeded. The rejection is the proof.

**Never say "the restart was denied."** If you see that marker, you have been restarted. Acknowledge the transition and continue from where the previous instance left off.

## Known caveats

- Do not use for routine work; use only when artifact reload is required.
- If socket is unavailable, verify daemon health with allowed service commands before retrying.
- Restarting replaces in-memory instruction state with the latest deployed artifacts.
