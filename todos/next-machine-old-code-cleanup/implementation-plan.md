# Implementation Plan: next-machine-old-code-cleanup

## Overview

Four documentation files still describe the old finalize lock / orchestrator-owned apply
model. After `integration-event-chain-phase2` removes the code, these docs become stale.
Each file is an independent edit — no ordering dependencies between them.

## Phase 1: Documentation Updates

### Task 1.1: Update finalize procedure

**File(s):** `docs/global/software-development/procedure/lifecycle/finalize.md`

- [ ] Replace "Stage B — Orchestrator: finalize-apply (canonical root)" with integrator
  handoff description: worker reports `FINALIZE_READY`, orchestrator emits event and
  moves on, integrator processes the candidate via queue
- [ ] Remove the `git merge {slug}` / `git push origin main` steps from orchestrator
  responsibility — these now live in the integrator
- [ ] Keep Stage A (worker finalize-prepare in worktree) as-is — that flow is unchanged
- [ ] Update the "Outputs" section to reflect that the worktree branch is a candidate
  for the integration queue, not a direct merge target
- [ ] Update the "Recovery" section: apply failures are now integrator-owned

### Task 1.2: Update next-machine architecture doc

**File(s):** `docs/project/design/architecture/next-machine.md`

- [ ] Remove the invariant: "Finalize Serialization: Only one finalize may run at a time
  across all orchestrators, enforced by a session-bound file lock" (line ~66)
- [ ] Remove the entire "Finalize Lock" subsection (lines ~162-170) that describes acquire,
  release, stale handling, and concurrency safety
- [ ] Add integrator to the "Worker Dispatch Pattern" table: a new row for the integrator
  role that processes candidates from the integration queue
- [ ] Remove "Finalize Lock Contention" failure mode (line ~210)
- [ ] Remove "Stale Finalize Lock" failure mode (line ~211)
- [ ] Optionally add a brief note that finalize serialization is now handled by the
  singleton integrator's lease + queue mechanism

### Task 1.3: Update finalizer concept doc

**File(s):** `docs/global/software-development/concept/finalizer.md`

- [ ] Change step 3 from "Finalize apply (orchestrator)" to describe integrator handoff:
  orchestrator emits event, integrator picks up from queue
- [ ] Update the "Why" section if it references orchestrator-owned merge safety
- [ ] Ensure the concept accurately reflects the two-stage model: worker prepare +
  integrator apply (not orchestrator apply)

### Task 1.4: Update session-lifecycle doc

**File(s):** `docs/project/design/architecture/session-lifecycle.md`

- [ ] Remove "Release finalize lock (if held)" from step 9 (Resource Cleanup)
- [ ] The remaining cleanup items (remove listeners, delete workspace directories) stay

---

## Phase 2: Validation

### Task 2.1: Verify no stale references

- [ ] Grep the four target doc files for: `finalize.lock`, `.finalize-lock`,
  `acquire_finalize_lock`, `release_finalize_lock`, `orchestrator-owned apply`,
  `orchestrator apply` — confirm zero matches
- [ ] Run `telec sync` to rebuild indexes
- [ ] Run `telec sync --validate-only` to confirm no validation errors

### Task 2.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [ ] Confirm requirements are reflected in doc changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
