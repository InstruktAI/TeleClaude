# Implementation Plan: api-todos-work-stability-hardening

## Overview

Instrument first, then remove redundant prep/sync work with explicit safety
guards. Keep behavior-compatible orchestration semantics while making the
request path deterministic for unchanged slugs.

## Phase 1: Core Changes

### Task 1.1: Add phase timing instrumentation for `/todos/work`

**File(s):** `teleclaude/core/next_machine/core.py`, `teleclaude/api_server.py` (if request correlation is needed)

- [x] Add structured timing logs around major `next_work(...)` phases
      (slug resolution, precondition checks, ensure/prep, sync, gate execution,
      dispatch decision).
- [x] Include slug and stable phase identifiers so operations can grep a single
      `/todos/work` path without stack traces.
- [x] Ensure logs encode decision reason for skip/run outcomes.
- Requirements: `R1`

### Task 1.2: Replace always-prep behavior with conditional prep policy

**File(s):** `teleclaude/core/next_machine/core.py`

- [x] Introduce explicit prep-decision helper(s) for existing worktrees.
- [x] Require prep on new worktree creation and when prep-state/drift checks
      indicate worktree is stale.
- [x] Skip prep when worktree is unchanged and known-good.
- [x] Preserve existing prep failure contract (`WORKTREE_PREP_FAILED` path).
- Requirements: `R2`, `R5`

### Task 1.3: Add per-slug single-flight protection for prep

**File(s):** `teleclaude/core/next_machine/core.py`

- [x] Add per-slug lock/single-flight coordination around ensure/prep execution.
- [x] Ensure only one same-slug call runs prep at a time; followers reuse the
      completed state.
- [x] Avoid cross-slug serialization (no global worktree prep lock).
- Requirements: `R3`, `R5`

### Task 1.4: Make sync operations conditional where safe

**File(s):** `teleclaude/core/next_machine/core.py`

- [x] Add change-detection checks for `sync_main_to_worktree(...)` and
      `sync_slug_todo_from_main_to_worktree(...)`.
- [x] Skip sync when tracked source artifacts are unchanged.
- [x] Preserve state seeding/repair behavior when destination files are missing
      or source has changed.
- Requirements: `R4`, `R5`

### Task 1.5: Update architecture docs for new prep/sync decision contract

**File(s):** `docs/project/design/architecture/next-machine.md`

- [x] Document conditional prep/sync policy and single-flight behavior.
- [x] Document new phase timing log contract for `/todos/work`.
- Requirements: `R1`, `R2`, `R3`, `R4`

---

## Phase 2: Validation

### Task 2.1: Tests

- [x] Update `tests/unit/test_next_machine_worktree_prep.py` to replace
      "always prep" assertions with conditional decision assertions.
- [x] Add/extend tests for concurrent same-slug calls to verify single-flight
      prep behavior.
- [x] Add/extend sync tests to verify safe skip on unchanged inputs and re-sync
      on changes.
- [x] Validate no regression in build gate/reset and dispatch behavior.
- Requirements: `R2`, `R3`, `R4`, `R5`, `R6`

### Task 2.2: Quality Checks

- [x] Run targeted unit tests for next-machine modules touched in this todo.
- [x] Run repo quality gates (`make lint`, `make test`) before completion.
- [x] Verify no unchecked implementation tasks remain.
- Requirements: `R5`, `R6`

### Task 2.3: Operational validation

- [x] Run repeated same-slug `/todos/work` calls in a controlled scenario and
      verify logs show prep/sync skip decisions after initial ready state.
- [x] Verify phase timing logs are grep-friendly via:
      `instrukt-ai-logs teleclaude --since <window> --grep <phase-pattern>`.
- Note (2026-02-26): runtime `/todos/work` invocation is denied in worker
  sessions (`permission denied — role 'worker' is not permitted`), so this
  worktree cannot execute the end-to-end command directly. Behavior is covered
  by targeted single-flight/prep/sync tests plus full lint/test gates.
- Requirements: `R1`, `R2`, `R4`

---

## Phase 3: Review Readiness

- [x] Confirm every task traces to one or more requirements (`R1`-`R6`).
- [x] Confirm implementation tasks are all marked `[x]`.
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable).
- Requirements: `R6`

## Potential follow-up (separate todo if needed; not part of this delivery scope)

- Evaluate moving heavyweight checks out of synchronous request path.
- Tune watchdog thresholds using measured phase timings, not guesswork.
