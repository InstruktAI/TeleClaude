# Implementation Plan: integrator-cutover

## Overview

Move canonical `main` integration ownership from orchestrator finalize-apply
steps to the singleton integrator runtime. This cutover builds on
`integration-events-model` and `integrator-shadow-mode`, preserving queue/lease
determinism while removing all non-integrator canonical write paths.

---

## Phase 1: Authority Cutover

### Task 1.1: Define cutover mode and operator control boundary

**File(s):** `teleclaude/config.py`, `config.sample.yml`, `teleclaude.yml`, `docs/project/spec/integration-orchestrator.md`

- [ ] Add/confirm explicit integrator mode values that distinguish
      shadow (non-writing) from cutover (write-enabled) behavior.
- [ ] Document operator control for pausing cutover writes while preserving
      queued candidates.
- Requirements: `R1`, `R7`

### Task 1.2: Retire legacy orchestrator finalize apply writes

**File(s):** `teleclaude/core/next_machine/core.py`, `docs/global/software-development/procedure/lifecycle/finalize.md`, `docs/project/design/architecture/next-machine.md`

- [ ] Remove canonical merge/push apply steps from `next-finalize`
      post-completion instructions.
- [ ] Keep `FINALIZE_READY` evidence contract intact so candidate readiness
      still enters integration workflow.
- [ ] Update orchestration docs to reflect integrator-only canonical write
      authority.
- Requirements: `R1`, `R2`, `R8`

### Task 1.3: Enable write-capable integrator apply path

**File(s):** integrator runtime module(s) delivered by `integrator-shadow-mode` (for example `teleclaude/core/integration/shadow_runtime.py`), `teleclaude/daemon.py`, `teleclaude/core/db.py`

- [ ] Promote per-candidate execution from `would_*` outcomes to real
      integration apply behavior in cutover mode.
- [ ] Preserve lease singleton semantics (`integration/main`) and FIFO queue
      processing.
- [ ] Emit durable `integration_completed` / `integration_blocked` outcomes
      with candidate identity (`slug`, `branch`, `sha`).
- Requirements: `R1`, `R3`, `R5`, `R6`

---

## Phase 2: Safety And Containment

### Task 2.1: Enforce apply safety checks at integrator boundary

**File(s):** integrator runtime apply module(s), `teleclaude/core/next_machine/core.py`, `tests/unit/test_next_machine_hitl.py`

- [ ] Enforce dirty/diverged/unknown-git-state safety checks in integrator apply
      flow before canonical writes.
- [ ] Remove duplicate safety logic from legacy finalize apply path once
      ownership shifts.
- [ ] Ensure failed safety checks resolve to blocked outcomes with no partial
      push.
- Requirements: `R4`, `R5`, `R8`

### Task 2.2: Implement blocked-path persistence and containment semantics

**File(s):** integrator runtime module(s), `teleclaude/core/db_models.py`, `teleclaude/core/db.py`

- [ ] Persist blocked reason/evidence for merge conflicts and failed
      preconditions.
- [ ] Keep queue status transitions deterministic
      (`in_progress -> integrated|blocked|superseded`) without partial mainline
      writes.
- [ ] Defer follow-up todo creation/resume UX to `integration-blocked-flow`.
- Requirements: `R5`, `R6`

### Task 2.3: Add pause/resume containment behavior

**File(s):** `teleclaude/daemon.py`, `teleclaude/config.py`, integrator runtime module(s), operator docs

- [ ] Ensure cutover mode can be paused without dropping durable queue state.
- [ ] Ensure resume behavior continues from persisted lease/queue data.
- Requirements: `R7`, `R6`

---

## Phase 3: Validation

### Task 3.1: Tests

**File(s):** `tests/unit/test_next_machine_hitl.py`, integrator runtime test module(s) (for example `tests/unit/test_integration_shadow_runtime.py`), `tests/unit/test_next_machine_state_deps.py`

- [ ] Add regression tests proving `next-finalize` no longer performs canonical
      merge/push apply.
- [ ] Add tests for cutover success path (`READY` candidate integrates and emits
      `integration_completed`).
- [ ] Add tests for blocked path (conflicts/precondition failures emit
      `integration_blocked` and do not push canonical `main`).
- [ ] Add tests for containment toggle pause/resume behavior.
- Requirements: `R1`, `R2`, `R3`, `R4`, `R5`, `R7`, `R8`

### Task 3.2: Operational verification

- [ ] Validate logs include lease owner, candidate tuple, outcome, and reason.
- [ ] Validate canonical pushes occur only from integrator-owned cutover flow.
- [ ] Validate queue/lease state remains recoverable after daemon restart.
- Requirements: `R6`, `R7`, `R8`

### Task 3.3: Quality checks

- [ ] Run targeted cutover/integrator/finalize regression tests.
- [ ] Run `make lint`.
- [ ] Run `make test`.
- [ ] Verify no unchecked implementation tasks remain.
- Requirements: `R8`

---

## Phase 4: Review Readiness

- [ ] Confirm each implementation task maps to requirements `R1`-`R8`.
- [ ] Confirm implementation tasks are all marked `[x]`.
- [ ] Document any explicit deferrals in `deferrals.md` (if needed).
- Requirements: `R8`

## Potential Follow-up (separate todo)

- Implement blocked follow-up todo creation and resume UX (`integration-blocked-flow`).
