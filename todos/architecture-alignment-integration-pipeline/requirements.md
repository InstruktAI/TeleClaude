# Requirements: architecture-alignment-integration-pipeline

## Goal

Wire the event-driven integration trigger path end-to-end so that the
post-finalize flow is handled by the state machine (`next_work()`), not by
the orchestrator calling `telec todo integrate` directly. This completes the
event chain wiring that `next-machine-old-code-cleanup` depends on.

## Scope

### In scope

1. **Extend PhaseName to include finalize** — Add `FINALIZE` to the `PhaseName` enum
   (`core.py:42-44`) and update the API validation whitelist (`todo_routes.py:133`) to
   accept `"finalize"` alongside `"build"` and `"review"`. Without this, `mark-phase
   --phase finalize` returns HTTP 400.
2. **mark-phase --cwd flag** — Add `--cwd` argument to the `handle_todo_mark_phase`
   CLI handler so the orchestrator can target the correct `state.yaml` regardless
   of its working directory.
3. **Post-finalize event emission** — Add a detection branch in `next_work()` that
   recognises finalize-complete state, derives branch/sha from the worktree, calls
   `emit_deployment_started()`, and returns COMPLETE.
4. **Orchestrator guidance update** — Rewrite `POST_COMPLETION["next-finalize"]` to
   instruct the orchestrator to mark the finalize phase complete (via mark-phase) and
   call `telec todo work` instead of `telec todo integrate` directly.
5. **Version Control Safety policy** — Change the state-files commit strategy from
   "don't commit orchestrator-managed files unless task requires" to "workers commit
   all dirty files at end of work" (worktree branches never hit main directly).

### Out of scope

- **Old manual path removal** (finalize locks, `caller_session_id`, inline
  `telec todo integrate` call) — belongs to `next-machine-old-code-cleanup`.
- **Auto-commits conversion** in `_step_committed` / `_do_cleanup` — recommend
  a separate todo; this is about the integrator's internal behavior, not the
  trigger wiring.
- **Session auth on integrate** — already resolved; HTTP client middleware
  (`tool_client.py`) sends `X-Caller-Session-ID` automatically.
- **queue.json deprecation** — queue.json is NOT vestigial. It is the durable
  FIFO backing store. Events handle discovery/trigger; queue.json handles
  sequencing/recovery. No changes needed.

## Success Criteria

- [ ] `telec todo mark-phase {slug} --phase finalize --status complete --cwd /path`
      updates `state.yaml` at the specified cwd, not at `os.getcwd()`.
- [ ] When `next_work()` detects finalize is marked complete and a worktree exists
      for the slug, it derives branch and SHA from `git -C {worktree}`, calls
      `emit_deployment_started(slug, branch, sha)`, and returns a COMPLETE response.
- [ ] `IntegrationTriggerCartridge` receives the `deployment.started` event and
      spawns an integrator session (no code changes needed in the cartridge — verify
      the existing wiring works).
- [ ] End-to-end: finalize worker completes -> orchestrator marks phase ->
      `next_work()` emits event -> cartridge spawns integrator. No direct
      `telec todo integrate` call required.
- [ ] Version Control Safety policy doc reflects the new state-files commit strategy.
- [ ] All existing tests pass; new tests cover the --cwd flag and the post-finalize
      event emission branch.

## Constraints

- The old manual path (`telec todo integrate` from guidance) MUST remain functional
  as a fallback. The cleanup todo removes it after this todo is verified.
- `emit_deployment_started()` already exists in `integration_bridge.py` — reuse it.
- `IntegrationTriggerCartridge` already watches `deployment.started` — no changes.
- SHA validation: `emit_deployment_started` or its downstream (`auto_enqueue`) already
  validates 40-char hex SHA (recent commit `e2f6b7984`). Ensure the derived SHA passes.
- The guidance rewrite must preserve all non-integration instructions (error handling,
  session management, no-op suppression).

## Risks

- **Worktree availability**: `next_work()` assumes the worktree still exists when it
  runs post-finalize. If the worktree was cleaned up prematurely, branch/sha derivation
  fails. Add a guard.
- **VCS policy change is cross-project**: All workers across all projects will start
  committing state files. This is safe because workers operate in worktree branches
  that only reach main through the integrator, but verify no edge case exists where
  a worker pushes directly.

## Corrections from Codebase Evidence

The original `input.md` contained several items that codebase research revealed to be
stale or already resolved:

| Input Item | Status | Evidence |
|---|---|---|
| `_step_committed` / `_do_cleanup` auto-commits | **Exists but out of scope** | Found in `integration/state_machine.py:955,1097` (not `next_machine/core.py`). Separate concern. |
| Session auth on integrate | **Already resolved** | `tool_client.py` injects `X-Caller-Session-ID` from `$TMPDIR/teleclaude_session_id` on every API call. |
| queue.json vestigial | **Incorrect** | `IntegrationQueue` in `integration/queue.py` (430 lines) is actively used. Events trigger, queue sequences. |
| Integration flow architecture | **Confirmed** | `IntegrationTriggerCartridge` in `cartridges/integration_trigger.py:31-82` watches `deployment.started`. |
| Finalizer output format | **Confirmed, no change** | FINALIZE_READY carries slug only; state machine derives branch/sha. |
