# Input: fix-integration-queue-ghost

## Problem Statement

The integrator is spawned correctly by the event chain but finds zero candidates to merge.
This is a regression introduced by the incomplete refactor in `0a60e90b0` (March 14).

## Root Cause

Two disconnected candidate discovery paths exist:

1. **Daemon event chain** (still alive): `work.py` emits `branch_pushed` + `deployment_started`
   → `IntegrationTriggerCartridge` feeds `ReadinessProjection` → enqueues into `queue.json`
   → spawns integrator via `spawn_integrator_session`. This path works correctly.

2. **Integrator state machine** (refactored): `_step_idle` in `step_functions.py` calls
   `_scan_finalize_ready_candidates` which scans worktree `state.yaml` files. It finds
   `finalize.status: handed_off` with `handed_off_at` < 120 seconds → skips as "fresh
   handoff, not yet recoverable" → returns empty → integrator reports "queue empty".

The refactor `0a60e90b0` replaced queue consumption in the state machine with worktree
scanning but never removed the daemon-side event chain that writes to `queue.json` and
spawns the integrator. The work machine's `_dispatch_finalize_handoff` transitions
`finalize.status` from `ready` → `handed_off` before the integrator can scan, making
the candidate invisible to the scanner.

## Timeline

| Commit | What |
|--------|------|
| `0a60e90b0` Mar 14 00:44 | Replaced queue consumption with worktree scanner. Left daemon wiring untouched. |
| `526790d1f` Mar 14 12:48 | Refactored `daemon_event_platform.py` — preserved queue wiring verbatim as `_build_integration_trigger()`. |
| `45c272b29` Mar 15 20:54 | Added zombie wake-by-message to `spawn_integrator_session`. |

## Required Changes

### 1. Remove queue.json enqueue from daemon wiring

In `daemon_event_platform.py` `_build_integration_trigger()`: remove `IntegrationQueue`
import and enqueue call. The `_ingest_callback` should still feed the projection (for
observability) but not enqueue. The `spawn_callback` stays — it correctly spawns/wakes
the integrator.

### 2. Fix the scanner's handed_off guard

In `step_functions.py` `_scan_finalize_ready_candidates()` and `_verify_slug_ready()`:
the `handed_off` status with < 120s guard assumes another integrator is processing.
But the integrator IS the scanner. Two options:

- **Option A**: Accept `handed_off` unconditionally (the integrator is always the intended
  consumer; the lease prevents concurrent processing).
- **Option B**: Have the work machine stop transitioning `ready` → `handed_off` and let
  the integrator do that transition after dequeue.

Option A is simpler and preserves the existing handoff semantics.

### 3. Clean up queue.json residue

- `~/.teleclaude/integration/queue.json` can be deleted or ignored.
- The `IntegrationQueue` class can be preserved for now (shadow runtime tests reference it)
  but should be marked as deprecated.

## Key Files

- `teleclaude/daemon_event_platform.py` — `_build_integration_trigger()` (lines 207-234)
- `teleclaude/core/integration/step_functions.py` — `_scan_finalize_ready_candidates()` (line 250), `_verify_slug_ready()` (line 340)
- `teleclaude/core/next_machine/work.py` — `_dispatch_finalize_handoff()` (line 796)
- `teleclaude/events/cartridges/integration_trigger.py` — cartridge still wired
- `teleclaude/core/integration_bridge.py` — `spawn_integrator_session()` (keep)
