# DOR Report: integration-event-chain-phase2

## Rescope Note

This todo was rescoped on March 6, 2026 after the finalize-handoff regression was
recovered in production code.

Delivered/recovered already:
- finalize lock removal
- `caller_session_id` cleanup
- event-driven `deployment.started` handoff from `next-finalize`

Remaining work now combines:
- the unfinished three-event readiness gate
- the still-open integrator bookkeeping/cleanup ownership alignment

The previous PASS verdict is no longer authoritative for the new scope.

## Current Status

- **Verdict:** needs_work
- **Reason:** requirements and implementation plan were refreshed to match the
  true remaining scope, but the todo has not been re-gated yet.

## What changed

1. Removed already-delivered work from scope so the todo only tracks real leftovers.
2. Absorbed the remaining useful parts of the architecture-alignment discussion:
   integrator bookkeeping/cleanup must become AI-directed, and only the integrator
   may call `telec todo integrate`.
3. Explicitly rejected the stale `finalize`-phase expansion and `mark-phase --cwd`
   detour from the architecture scratchpad.

## Next action

Run a fresh DOR gate against the rescoped requirements and implementation plan before
dispatching build work.
