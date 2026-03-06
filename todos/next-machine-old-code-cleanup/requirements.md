# Requirements: next-machine-old-code-cleanup

## Goal

Update documentation to reflect the integrator-owned merge model after
`integration-event-chain-phase2` removes the finalize lock mechanism,
`caller_session_id` coupling, and inline `telec todo integrate` from production code.

Phase 2 delivers the code changes. This todo delivers the documentation alignment.

## Scope

### In scope

- Update `docs/global/software-development/procedure/lifecycle/finalize.md` to describe
  integrator handoff instead of orchestrator-owned apply
- Update `docs/project/design/architecture/next-machine.md` to:
  - Remove the "Finalize Lock" section and its invariant
  - Add integrator to the worker dispatch table
  - Remove "Finalize Lock Contention" and "Stale Finalize Lock" failure modes
- Update `docs/global/software-development/concept/finalizer.md` to reference integrator
  instead of orchestrator apply
- Update `docs/project/design/architecture/session-lifecycle.md` to remove
  "Release finalize lock (if held)" from the resource cleanup step

### Out of scope

- Code changes (finalize lock removal, `caller_session_id` removal, POST_COMPLETION rewrite)
  — delivered by `integration-event-chain-phase2`
- Test changes — delivered by `integration-event-chain-phase2`
- Event chain wiring — delivered by `integration-event-chain-phase2`

## Context: Scope Overlap Resolution

The original `input.md` described both code and documentation changes. The code changes
(lock functions, `caller_session_id`, POST_COMPLETION rewrite, session cleanup, tests) are
fully covered by `integration-event-chain-phase2` (DOR score 9, requirements #6-#8). That
todo's DOR report explicitly recommends absorbing the code cleanup items.

This todo is rescoped to documentation-only: the four doc files that phase 2 declares out
of scope ("Documentation updates — separate cleanup pass").

## Success Criteria

- [ ] `finalize.md` procedure describes integrator handoff (no orchestrator-owned apply)
- [ ] `next-machine.md` has no "Finalize Lock" section or related invariants
- [ ] `next-machine.md` worker dispatch table includes integrator
- [ ] `next-machine.md` failure modes do not reference finalize lock
- [ ] `finalizer.md` concept references integrator-owned merge
- [ ] `session-lifecycle.md` resource cleanup step does not mention finalize lock
- [ ] `telec sync` passes after changes
- [ ] No stale references to finalize lock, `caller_session_id`, or orchestrator-owned
  apply remain in the four target doc files

## Constraints

- Must land AFTER `integration-event-chain-phase2` delivers the code changes
- Documentation must match the actual post-phase-2 code behavior

## Risks

- If phase 2 changes the integration model differently than expected, these doc updates
  would need revision — mitigated by the dependency gate
