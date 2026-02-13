---
id: 'general/spec/tools/agent-restart'
type: 'spec'
scope: 'global'
description: 'Canonical self-restart call for reloading synchronized artifacts without losing session continuity.'
---

# Agent Restart Tool — Spec

## What it is

Reload agent artifacts in the current session after `telec sync`. Use only when artifact reload is required.

## Canonical fields

```bash
curl -s --unix-socket /tmp/teleclaude-api.sock \
  -X POST "http://localhost/sessions/$(cat "$TMPDIR/teleclaude_session_id")/agent-restart"
```

## See Also

- ~/.teleclaude/docs/general/principle/continuity.md — recognizing a restart from forensic markers.
