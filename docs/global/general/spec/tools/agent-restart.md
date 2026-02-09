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

## Known caveats

- Do not use for routine work; use only when artifact reload is required.
- If socket is unavailable, verify daemon health with allowed service commands before retrying.
- Restarting replaces in-memory instruction state with the latest deployed artifacts.

## See also

- general/principle/continuity — recognizing a restart from forensic markers.
