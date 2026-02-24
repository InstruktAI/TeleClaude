# Implementation Plan - finalize-push-guardrails

## Objective

Close all known paths where worktree-context agents can advance `origin/main` directly, while preserving normal feature-branch workflows.

## Preconditions

- Slug `finalize-push-guardrails` remains active in `todos/roadmap.yaml`.
- Existing finalize lock behavior in `teleclaude/core/next_machine/core.py` is retained and extended, not removed.
- No new third-party dependencies are introduced.

## Requirement Traceability

- `R1` -> Phase 1
- `R2` -> Phase 1
- `R3` -> Phase 2
- `R4` -> Phase 2
- `R5` -> Phase 2
- `R6` -> Phases 2, 3
- `R7` -> Phases 1, 4
- `R8` -> Phase 2

## Phase 1 - Finalize Split (R1, R2, R7)

- [x] Convert [`next-finalize`](../../agents/commands/next-finalize.md) to prepare-only behavior:
  - integrate `origin/main` into the worktree branch,
  - run required verification guidance,
  - emit `FINALIZE_READY: {slug}` and stop.
- [x] Update finalize lifecycle procedure doc to explicit two-stage model in [`finalize.md`](../../docs/global/software-development/procedure/lifecycle/finalize.md):
  - worker `finalize-prepare`,
  - orchestrator `finalize-apply`.
- [x] Update next-machine finalize orchestration in [`core.py`](../../teleclaude/core/next_machine/core.py):
  - keep worker dispatch in `trees/{slug}` for prepare stage,
  - change post-completion contract to require `FINALIZE_READY` before apply,
  - run apply instructions from canonical repo root,
  - keep lock held through apply completion and release only after completion signal.
- [x] Ensure bookkeeping references `todos/delivered.yaml` and `todos/roadmap.yaml` (not legacy `delivered.md` paths).

## Phase 2 - Main-Branch Guardrail Layers (R3, R4, R5, R6, R8)

- [x] Add `.githooks/pre-push` guard to reject non-canonical pushes targeting `refs/heads/main`.
- [x] Ensure `telec init` configures `core.hooksPath=.githooks` idempotently.
- [x] Harden git wrapper behavior for push-to-main:
  - detect main-targeting push refspecs,
  - block from non-canonical context even with `--no-verify`,
  - preserve non-main push behavior.
- [x] Add `gh` wrapper guard for `gh pr merge` to base `main` from non-canonical contexts.
- [ ] Keep wrapper scope limited to agent sessions via PATH injection in [`tmux_bridge.py`](../../teleclaude/core/tmux_bridge.py).
- [ ] Emit structured rejection logs with cwd, branch, target, command, and session context (when present).

## Phase 3 - Auditability and Operator UX (R6)

- [ ] Standardize rejection message text so agents are instructed to stop and report `FINALIZE_READY`.
- [ ] Add log-grep friendly marker strings for blocked push/merge events.
- [ ] Update docs/policy references where wording still implies single-stage finalize or `delivered.md`.

## Phase 4 - Validation and Safety Checks (R7)

- [ ] Extend next-machine tests for finalize flow and post-completion expectations:
  - [`test_next_machine_state_deps.py`](../../tests/unit/test_next_machine_state_deps.py)
  - [`test_next_machine_hitl.py`](../../tests/unit/test_next_machine_hitl.py)
  - [`test_next_machine_deferral.py`](../../tests/unit/core/test_next_machine_deferral.py)
- [ ] Add unit tests for guardrail enforcement logic (pre-push/git/gh wrappers).
- [ ] Verify no regressions in feature-branch workflows.
- [ ] Run:
  - `make test`
  - `make lint`
  - `telec todo validate finalize-push-guardrails`
  - `telec todo demo validate finalize-push-guardrails`

## Rollout Notes

- Land in this order:
  1. finalize split contract and docs,
  2. guardrail layers,
  3. tests and demo validation updates.
- If any guardrail is temporarily disabled during debugging, do not dispatch finalize work until all layers are re-enabled.

## Definition of Done

- [ ] Finalize is two-stage and `FINALIZE_READY`-gated.
- [ ] Worktree-originated main advancement paths are blocked for both git and gh flows.
- [ ] Delivery bookkeeping remains correct in `delivered.yaml` + roadmap removal.
- [ ] Regression tests and lint pass.
