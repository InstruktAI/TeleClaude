# Implementation Plan: integration-safety-gates

## Overview

Add narrow guardrails to the existing finalize path in `next_machine` and keep
changes surgical: one path-level precondition check used at dispatch and apply,
with deterministic error surfaces and focused regression tests.

## Phase 1: Core Changes

### Task 1.1: Define canonical finalize precondition checks

**File(s):** `teleclaude/core/next_machine/core.py`

- [x] Add helper(s) that validate canonical `main` finalize safety preconditions
      (including dirty working tree and invalid integration state).
- [x] Return explicit machine-readable failure code/message when preconditions
      fail (no ambiguous free-form errors).

### Task 1.2: Enforce gates in finalize dispatch and apply instruction path

**File(s):** `teleclaude/core/next_machine/core.py`

- [x] Gate finalize dispatch in `next_work` before emitting `/next-finalize`.
- [x] Gate finalize-apply instruction generation so orchestrator apply cannot
      proceed when canonical preconditions are invalid.
- [x] Preserve current happy-path output/instructions when checks pass.

### Task 1.3: Document the new guardrail contract where finalize behavior is described

**File(s):** `docs/project/design/architecture/next-machine.md`

- [x] Update finalize/failure-mode section to include the new safety gate
      behavior and operator-visible outcomes.

---

## Phase 2: Validation

### Task 2.1: Tests

- [x] Add/adjust tests for blocked finalize dispatch when canonical `main` is unsafe
- [x] Add/adjust tests for allowed finalize flow when conditions are satisfied
- [x] Add/adjust tests for deterministic failure messaging/error code surface
- [x] Run `make test`

### Task 2.2: Quality Checks

- [x] Run `make lint`
- [x] Verify no unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [x] Confirm requirements are reflected in code changes
- [x] Confirm implementation tasks are all marked `[x]`
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable)
