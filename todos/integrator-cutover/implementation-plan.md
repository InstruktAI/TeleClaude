# Implementation Plan: integrator-cutover

## Plan Objective

Enforce integrator-exclusive canonical main integration after shadow parity signoff.

## Phase 1: Authority Enforcement

### Task 1.1: Add canonical main authorization checks

**File(s):** `teleclaude/core/integration/authorization.py`, `teleclaude/core/integration/runtime.py`, `teleclaude/install/wrappers/git`, `teleclaude/install/wrappers/gh`, `.githooks/pre-push`

- [x] Enforce integrator-only merge/push for canonical `main`.
- [x] Return clear rejection errors for non-integrator callers.

### Task 1.2: Wire cutover toggles and safety controls

**File(s):** `teleclaude/core/integration/runtime.py`, `teleclaude/core/integration/authorization.py`, `teleclaude/config/schema.py`

- [x] Add cutover enablement control gated by parity evidence.
- [x] Add documented rollback path for incomplete readiness evidence.

## Phase 2: Verification

### Task 2.1: Add acceptance and regression coverage

**File(s):** `tests/integration/test_integrator_cutover.py`

- [ ] Verify non-integrator canonical main push is blocked.
- [ ] Verify integrator canonical main push still succeeds.
- [ ] Verify feature-branch pushes remain allowed.

### Task 2.2: Run quality gates

- [ ] Run `make test`.
- [ ] Run `make lint`.

## Phase 3: Review Readiness

- [ ] Confirm all legacy non-integrator canonical main paths are blocked.
- [ ] Confirm rollback path is documented and test-backed.
