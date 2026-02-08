---
id: 'general/procedure/checkpoint'
type: 'procedure'
scope: 'global'
description: 'Concrete steps for responding to a checkpoint message: validate work, then capture artifacts.'
---

# Checkpoint — Procedure

## Required reads

@~/.teleclaude/docs/general/policy/checkpoint.md

## Goal

Work through the Validate → Capture protocol when a checkpoint message arrives, producing concrete actions rather than passive reports.

## Preconditions

- A checkpoint message has been injected by the system.
- The agent's current turn has paused (agent_stop or agent restart).

## Steps

### Phase 1: Validate (if you performed any work this turn)

> **Note:** Running validation commands (tests, logs) counts as "producing work" and will trigger a subsequent checkpoint. This is expected. Validate thoroughly first; go silent on the _subsequent_ checkpoint once you confirm clean results.

1. Check logs for errors from your changes (`instrukt-ai-logs <service> --since <window> --grep <pattern>`).
2. Run tests if you changed code (`.venv/bin/python -m pytest tests/unit/ -x -q`).
3. Verify services are healthy after restarts or config changes (`make status`).
4. Check for loose ends: untested paths, forgotten steps, incomplete implementations.
5. Verify related doc snippets are up to date if you changed architecture or behavior.
6. If anything needs fixing or finishing — do it now. The checkpoint response IS the work, not a report about the work.

### Phase 2: Capture (always)

Route each item to its proper destination. Only act where relevant:

1. Bug discovered → fix it inline, right where you are. If too large, promote to `todos/` as a work item. There is no bugs backlog.
2. Work items beyond this session's scope → `todos/`
3. Patterns, lessons, or gotchas worth remembering → auto memory
4. Ideas, friction, or evolution opportunities → `ideas/`

### Exit

- If both phases produced no actionable work, do not respond. Silence is correct.
- If either phase produced work, do it. The next checkpoint will arrive when this work pauses.

## Outputs

- Verified, working code (Phase 1).
- Captured artifacts in their proper locations (Phase 2).
- Or silence, if everything is clean.

## Recovery

- If you lose context after a checkpoint, check recent logs and git status to re-orient.
- If unsure whether work was verified, assume it wasn't — run the validation steps.
