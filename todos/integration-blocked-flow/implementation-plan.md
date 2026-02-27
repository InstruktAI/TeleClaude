# Implementation Plan: integration-blocked-flow

## Plan Objective

Convert blocked integration outcomes into explicit, resumable operational flows.

## Phase 1: Blocked Event Contract

### Task 1.1: Define blocked payload and diagnostics

**File(s):** `teleclaude/core/integration/events.py`, `teleclaude/core/integration/runtime.py`

- [x] Add `integration_blocked` payload contract with required evidence fields.
- [x] Emit actionable diagnostics for remediation.

### Task 1.2: Implement follow-up todo linkage

**File(s):** `teleclaude/core/integration/blocked_followup.py`

- [x] Create/link follow-up todo for blocked candidate.
- [x] Ensure idempotent follow-up creation.

## Phase 2: Resume Mechanics and Validation

### Task 2.1: Implement resume path

**File(s):** `teleclaude/core/integration/runtime.py`

- [x] Re-queue remediated candidates only after readiness re-check.
- [x] Preserve audit history across blocked/resumed transitions.

### Task 2.2: Add coverage and run gates

**File(s):** `tests/integration/test_integration_blocked_flow.py`

- [x] Cover blocked emission, follow-up creation, and resume behavior.
- [x] Run `make test`.
- [x] Run `make lint`.

## Phase 3: Review Readiness

- [x] Confirm blocked flow remains deterministic and resumable.
- [x] Confirm no silent-failure fallback path remains.
