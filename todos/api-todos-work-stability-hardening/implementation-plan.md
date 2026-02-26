# Implementation Plan: api-todos-work-stability-hardening

## Overview

- Instrument first, then optimize with safety-preserving guards. The implementation should prove where time is spent, remove redundant prep/sync work, and keep existing state-machine behavior intact.

## Phase 1: Core Changes

### Task 1.1: Add phase timing instrumentation for `/todos/work`

**File(s):** `teleclaude/core/next_machine/core.py`, `teleclaude/api_server.py` (if request correlation is needed)

- [ ] Add structured timing logs around major `next_work(...)` phases.
- [ ] Include slug and request correlation where available.
- [ ] Ensure logs are high-signal and grep-friendly.

### Task 1.2: Replace always-prep behavior with conditional prep policy

**File(s):** `teleclaude/core/next_machine/core.py`

- [ ] Add explicit prep decision logic for existing worktrees.
- [ ] Keep always-prep only for first worktree creation or explicit refresh paths.
- [ ] Preserve failure reporting when prep is required and fails.

### Task 1.3: Add per-slug single-flight protection for prep

**File(s):** `teleclaude/core/next_machine/core.py`

- [ ] Ensure concurrent `/todos/work` calls for the same slug do not duplicate prep subprocess execution.
- [ ] Avoid global serialization across different slugs.

### Task 1.4: Make sync operations conditional where safe

**File(s):** `teleclaude/core/next_machine/core.py`

- [ ] Skip `sync_main_to_worktree(...)` and todo sync when refs/content are unchanged.
- [ ] Keep sync mandatory when change detection indicates drift or newer main commits.

---

## Phase 2: Validation

### Task 2.1: Tests

- [ ] Update `tests/unit/test_next_machine_worktree_prep.py` for conditional prep behavior.
- [ ] Add/extend tests for concurrent prep calls and per-slug single-flight behavior.
- [ ] Update tests that currently encode "always prep" assumptions.
- [ ] Run targeted tests for next-machine prep/work behavior.

### Task 2.2: Quality Checks

- [ ] Run lint/type checks for touched modules.
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)

## Deferred follow-up (only if Phase 1/2 still leave SLO violations)

- [ ] Evaluate moving heavyweight checks out of synchronous request path.
- [ ] Tune watchdog thresholds using measured phase timings, not guesswork.
