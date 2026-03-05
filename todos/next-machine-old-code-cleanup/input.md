# Input: next-machine-old-code-cleanup

## Context

The integrator-wiring delivery introduced event-driven integration (readiness projection,
integration queue, integration state machine, IntegrationTriggerCartridge). The old manual
path — finalize lock + POST_COMPLETION `telec todo integrate` — was kept as a working
fallback during the transition. Phase 1 (event chain wiring) completes the automated path.
This todo is Phase 2: strip the old manual path once the automated path is verified.

## What to remove from `teleclaude/core/next_machine/core.py`

1. **Finalize lock functions**: `acquire_finalize_lock` (line ~2165), `release_finalize_lock`
   (line ~2221), `get_finalize_lock_holder` — and all call sites in `next_work()` step 9.
2. **`caller_session_id` parameter**: Remove from `next_work()` signature (line ~2648) and
   all downstream usage (lines ~2675-2684, ~3080-3092).
3. **POST_COMPLETION rewrite**: `POST_COMPLETION["next-finalize"]` (lines ~224-248) still
   says `telec todo integrate {args}`. Replace with: orchestrator emits event and moves on.
4. **Session cleanup**: Any code in session lifecycle that releases finalize locks on session
   death — find and remove.
5. **Stale comment**: Line ~2154 says "serializes merges to main" — finalize lock now
   serializes finalize dispatches, not merges.

## API route update

`teleclaude/api/todo_routes.py` passes `identity.session_id` as `caller_session_id` to
`next_work()`. Remove that parameter from the route.

## Documentation to update

1. `docs/global/software-development/procedure/lifecycle/finalize.md` — Stage B still
   describes orchestrator-owned merge to main. Should describe integrator handoff.
2. `docs/project/design/architecture/next-machine.md` — No mention of integrator. Add
   integrator to state diagram and worker dispatch table. Remove "apply is orchestrator-owned".
3. `docs/global/software-development/concept/finalizer.md` — Still says "Finalize apply
   (orchestrator)". Should reference integrator.

## Tests to update

Find and update tests that exercise finalize lock acquisition, `caller_session_id` plumbing,
or the old POST_COMPLETION flow. Exact test files to be discovered during build.

## Dependency

This todo MUST NOT land before the event chain wiring is verified working. The manual path
is the only working integration trigger right now.
