# Implementation Plan: integration-blocked-flow

## Plan Objective

Convert blocked integration outcomes into explicit, resumable operational flows.

## Phase 1: Blocked Event Contract

### Task 1.1: Define blocked payload and diagnostics

**File(s):** `teleclaude/core/integration/events.py`, `teleclaude/core/integration/runtime.py`

- [ ] Add `integration_blocked` payload contract with required evidence fields.
- [ ] Emit actionable diagnostics for remediation.

### Task 1.2: Implement follow-up todo linkage

**File(s):** `teleclaude/core/integration/blocked_followup.py`

- [ ] Create/link follow-up todo for blocked candidate.
- [ ] Ensure idempotent follow-up creation.

## Phase 2: Resume Mechanics and Validation

### Task 2.1: Implement resume path

**File(s):** `teleclaude/core/integration/runtime.py`

- [ ] Re-queue remediated candidates only after readiness re-check.
- [ ] Preserve audit history across blocked/resumed transitions.

### Task 2.2: Add coverage and run gates

**File(s):** `tests/integration/test_integration_blocked_flow.py`

- [ ] Cover blocked emission, follow-up creation, and resume behavior.
- [ ] Run `make test`.
- [ ] Run `make lint`.

## Phase 3: Review Readiness

- [ ] Confirm blocked flow remains deterministic and resumable.
- [ ] Confirm no silent-failure fallback path remains.
