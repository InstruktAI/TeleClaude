# Implementation Plan: integrator-shadow-mode

## Overview

Implement an additive shadow integrator runtime that exercises the lease+queue
contract against canonical readiness data while guaranteeing zero canonical
`main` writes. Keep existing finalize apply path intact until cutover.

---

## Phase 1: Core Changes

### Task 1.1: Add explicit shadow-mode activation boundary

**File(s):** `teleclaude/config.py`, `config.sample.yml`, `teleclaude.yml`, `docs/project/spec/integration-orchestrator.md`

- [ ] Add explicit integrator mode/config that can enable shadow runtime without cutover.
- [ ] Default to non-cutover behavior; shadow must be opt-in.
- [ ] Document that shadow mode cannot own canonical `main` merge/push authority.
- Requirements: `R1`, `R4`, `R6`

### Task 1.2: Add durable persistence for lease, queue, and shadow outcomes

**File(s):** `teleclaude/core/schema.sql`, `teleclaude/core/migrations/024_add_integration_shadow_tables.py` (new), `teleclaude/core/db_models.py`, `teleclaude/core/db.py`

- [ ] Add tables/models for: - singleton lease state (`integration/main`), - durable queue items with status transitions, - shadow outcome records.
- [ ] Add DB methods for atomic lease acquire/renew/release and FIFO dequeue.
- [ ] Enforce candidate deduplication by `(slug, branch, sha)` and track supersession.
- Requirements: `R2`, `R4`, `R5`

### Task 1.3: Implement shadow integrator runtime loop

**File(s):** `teleclaude/core/integration/shadow_runtime.py` (new), `teleclaude/core/integration/__init__.py` (new), `teleclaude/daemon.py`

- [ ] Start background integrator runtime when shadow mode is enabled.
- [ ] Attempt lease acquisition when READY work exists; renew while active.
- [ ] Drain queue serially; re-check readiness before each item.
- [ ] Persist per-item shadow outcomes: `would_integrate`, `would_block`, `superseded`.
- [ ] Release lease and write checkpoint when queue drains and grace window closes.
- Requirements: `R1`, `R2`, `R3`, `R4`, `R5`

### Task 1.4: Wire readiness ingestion from integration-events-model

**File(s):** `teleclaude/core/integration/shadow_runtime.py`, integration-events-model-owned projection/event module(s), `teleclaude/core/next_machine/core.py` (only if needed for bridge hooks)

- [ ] Consume canonical readiness projection from `integration-events-model`; do not parse ad-hoc transcript text.
- [ ] Enqueue only on `NOT_READY -> READY` transitions.
- [ ] Mark stale candidates superseded when newer `finalize_ready` exists for a slug.
- Requirements: `R3`, `R5`

### Task 1.5: Preserve live finalize behavior during shadow phase

**File(s):** `teleclaude/core/next_machine/core.py`, `tests/unit/test_next_machine_hitl.py`, `tests/unit/test_next_machine_state_deps.py`

- [ ] Keep existing finalize apply path unchanged for canonical merge/push in this slice.
- [ ] Ensure shadow runtime is additive and observational only.
- Requirements: `R6`

---

## Phase 2: Validation

### Task 2.1: Tests

- [ ] Add unit tests for lease exclusivity and stale-lease recovery behavior.
- [ ] Add unit tests for queue ordering, deduplication, and supersession transitions.
- [ ] Add tests proving shadow runtime never performs canonical `main` mutation.
- [ ] Add tests for restart/resume (durable queue + lease state recovery).
- [ ] Keep regression coverage proving current finalize apply behavior remains intact pre-cutover.
- Requirements: `R2`, `R3`, `R4`, `R6`, `R7`

### Task 2.2: Operational verification

- [ ] Validate shadow logs are grep-friendly and include candidate identity + outcome.
- [ ] Validate persisted shadow outcomes are queryable and complete enough for cutover parity analysis.
- [ ] Validate no canonical `main` writes occur from the shadow runtime path.
- Requirements: `R4`, `R5`, `R7`

### Task 2.3: Quality checks

- [ ] Run targeted tests for shadow runtime and related next-machine regression coverage.
- [ ] Run `make lint`.
- [ ] Run `make test`.
- [ ] Verify no unchecked implementation tasks remain.
- Requirements: `R7`

---

## Phase 3: Review Readiness

- [ ] Confirm every implementation task maps to requirements `R1`-`R7`.
- [ ] Confirm implementation tasks are all marked `[x]`.
- [ ] Document any explicit deferrals in `deferrals.md` (if needed).
- Requirements: `R7`

## Potential Follow-up (separate todo)

- Define numeric parity threshold and acceptance window for shadow-to-cutover promotion (`integrator-cutover`).
