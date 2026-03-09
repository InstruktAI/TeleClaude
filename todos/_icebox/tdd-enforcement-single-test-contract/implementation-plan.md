# Implementation Plan: Strict TDD via Single Test Contract

## Overview

Introduce one contract-driven mechanism that governs test intent, approval, lock, and immutability across Next Machine phases. Build/fix workers become code-only lanes.

## Phase 1: Contract Artifact + State Schema

### Task 1.1: Add contract artifact template

**File(s):** `templates/todos/test-contract.md`, `teleclaude/todo_scaffold.py`, `teleclaude/cli/telec.py`

- [ ] Add canonical `test-contract.md` template with required sections and metadata block.
- [ ] Update todo scaffolding to create the contract for new todos.
- [ ] Update CLI messages/docs that list scaffolded artifacts.

### Task 1.2: Extend state schema for contract lifecycle

**File(s):** `teleclaude/todo_scaffold.py`, `teleclaude/core/next_machine/core.py`

- [ ] Add `state.json.test_contract` structure (status, hash, approved_at, approved_by, lock_version).
- [ ] Define allowed states: `draft`, `approved`, `locked`, `needs_regate`.
- [ ] Add helper functions for reading/updating contract state.

---

## Phase 2: Prepare/Gate Integration

### Task 2.1: Draft phase owns contract authoring

**File(s):** `teleclaude/core/next_machine/core.py`, `docs/global/general/procedure/maintenance/next-prepare-draft.md`, `docs/project/spec/jobs/next-prepare-draft.md`

- [ ] Ensure prepare draft includes `test-contract.md` generation/refinement.
- [ ] Require explicit mapping from requirements -> test cases in draft output.
- [ ] Persist draft hash in state metadata.

### Task 2.2: Gate phase approves and locks contract

**File(s):** `teleclaude/core/next_machine/core.py`, `docs/global/general/procedure/maintenance/next-prepare-gate.md`, `docs/project/spec/jobs/next-prepare-gate.md`

- [ ] Gate validates contract quality and requirement coverage.
- [ ] Gate sets status to approved/locked and stores lock hash.
- [ ] If quality insufficient, set `needs_work`/`needs_decision` with explicit blockers.

---

## Phase 3: Build/Fix Enforcement (Single Mechanism)

### Task 3.1: Central role-scoped file mutation guard

**File(s):** `teleclaude/core/next_machine/core.py`, `teleclaude/core/command_handlers.py` (if needed for shared guard entrypoint)

- [ ] Implement shared guard that inspects changed files for builder/fixer lanes.
- [ ] Block when locked test paths are modified.
- [ ] Emit deterministic error with offending paths.

### Task 3.2: Enforce preconditions before dispatch

**File(s):** `teleclaude/core/next_machine/core.py`

- [ ] `next_work` refuses dispatch if contract not approved/locked.
- [ ] Contract hash mismatch after lock sets `needs_regate` and blocks.
- [ ] Re-gate path is explicit (`next_prepare`/gate), not silent fallback.

---

## Phase 4: Reviewer/Finalize and Policy Alignment

### Task 4.1: Review/finalize integrity checks

**File(s):** `docs/global/software-development/procedure/lifecycle/review.md`, `docs/global/software-development/procedure/lifecycle/fix-review.md`, `docs/global/software-development/procedure/lifecycle/build.md`, `docs/global/software-development/procedure/lifecycle-overview.md`

- [ ] Update build/fix policy to code-only lanes (no test edits after lock).
- [ ] Add reviewer checks for contract coverage + hash integrity.
- [ ] Add finalize gate verifying no post-lock contract drift.

### Task 4.2: Quality checklist updates

**File(s):** `templates/todos/quality-checklist.md`

- [ ] Add explicit TDD gates (contract approved before build, hash unchanged, no builder/fixer test edits).
- [ ] Keep ownership boundaries explicit per section.

---

## Phase 5: Guardrails and Rollout

### Task 5.1: Pre-commit/CI guard

**File(s):** `.pre-commit-config.yaml`, `tools/*` (guard script if needed), `Makefile`

- [ ] Add guard that fails when builder/fixer role modifies locked tests.
- [ ] Ensure message explains remediation: revert test edits, fix code, or re-enter prepare gate.

### Task 5.2: Transitional mode and telemetry

**File(s):** `teleclaude/core/next_machine/core.py`, relevant docs under `docs/global/software-development/policy/*`

- [ ] Define temporary opt-out for legacy todos with explicit marker.
- [ ] Log every opt-out use for cleanup tracking.
- [ ] Document sunset criteria and removal plan.

---

## Phase 6: Validation

### Task 6.1: Unit tests for state machine and guards

**File(s):** `tests/unit/test_next_machine_*.py` (new/updated), `tests/unit/test_command_handlers*.py` (if needed)

- [ ] Missing contract blocks `next_work`.
- [ ] Unapproved contract blocks `next_work`.
- [ ] Hash mismatch triggers `needs_regate` block.
- [ ] Builder/fixer test edits are rejected.

### Task 6.2: Integration tests for end-to-end flow

**File(s):** `tests/integration/*next_machine*` (new/updated)

- [ ] Draft -> gate approve -> build/fix code-only flow passes.
- [ ] Attempted policy violation is blocked with clear guidance.

### Task 6.3: Runtime checks

- [ ] Run `make lint`.
- [ ] Run targeted tests for next-machine and guardrails.
- [ ] Run `make status` to confirm daemon health after changed behavior.

---

## Definition of Done

- [ ] New todos scaffold with `test-contract.md` and test-contract state fields.
- [ ] Prepare/gate enforce contract creation + approval before build.
- [ ] Build/fix cannot modify locked tests.
- [ ] Reviewer/finalize verify contract integrity.
- [ ] Guardrails fail deterministically on violations.
- [ ] Docs, templates, and runtime behavior are aligned.
