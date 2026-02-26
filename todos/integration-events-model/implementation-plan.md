# Implementation Plan: integration-events-model

## Overview

Introduce a durable event model and readiness projection that mirrors the
integration orchestrator spec while keeping integration execution behavior
unchanged. This slice is data-model + signal-ingestion only; queue/lease runtime
comes later in `integrator-shadow-mode`.

## Phase 1: Event Model Foundation

### Task 1.1: Add durable integration event/projection storage

**File(s):** `teleclaude/core/schema.sql`, `teleclaude/core/migrations/024_add_integration_events.py`, `teleclaude/core/db.py`

- [ ] Add tables/indexes for append-only integration events and current readiness projection
- [ ] Define event identity keys to enforce replay/idempotency semantics
- [ ] Add Db APIs to append canonical events and query projection by slug/candidate
- [ ] Keep storage in canonical `teleclaude.db` (single-database policy)

### Task 1.2: Implement readiness projection evaluator

**File(s):** `teleclaude/core/integration_events.py` (new), `teleclaude/core/db.py`

- [ ] Implement predicate evaluation from `docs/project/spec/integration-orchestrator.md`
- [ ] Evaluate `review_approved` + `finalize_ready` + `branch_pushed` field alignment
- [ ] Include remote reachability and "already integrated to origin/main" checks
- [ ] Implement supersession logic for newer `finalize_ready` events on same slug
- [ ] Return machine-readable missing predicates/reasons for diagnostics/tests

---

## Phase 2: Workflow Wiring

### Task 2.1: Emit `review_approved` at review phase approval seam

**File(s):** `teleclaude/api/todo_routes.py`, `teleclaude/core/next_machine/core.py`, `teleclaude/core/db.py`

- [ ] Record `review_approved` when `telec todo mark-phase --phase review --status approved` succeeds
- [ ] Ensure emission is idempotent for retries/replays of same approval
- [ ] Preserve existing phase-mark guardrails and error responses

### Task 2.2: Emit `finalize_ready` and `branch_pushed` from finalize orchestration seam

**File(s):** `teleclaude/core/next_machine/core.py`, `teleclaude/cli/telec.py`, `teleclaude/cli/tool_commands.py`, `teleclaude/api/todo_routes.py`

- [ ] Add deterministic event recording calls in finalize post-completion flow: - after `FINALIZE_READY` evidence is verified (`finalize_ready`) - after candidate branch push succeeds (`branch_pushed`)
- [ ] Capture branch/sha/session/remote fields required by spec
- [ ] Keep finalize safety-gate ordering intact (no bypass of existing checks)

### Task 2.3: Quality Checks

- [ ] Confirm plan task to requirement mapping has no contradictions
- [ ] Verify no unchecked required tasks remain before build completion

---

## Phase 3: Validation

### Task 3.1: Unit tests for event model and projection

**File(s):** `tests/unit/test_integration_events.py` (new), `tests/unit/test_todo_routes.py`, `tests/unit/test_next_machine_hitl.py`, `tests/unit/test_next_machine_state_deps.py`

- [ ] Cover event validation and idempotent inserts for all three canonical events
- [ ] Cover readiness transitions `NOT_READY -> READY`, missing-field cases, and superseded candidates
- [ ] Cover review-approved emission on phase mark success path
- [ ] Cover finalize instruction/event recording sequencing in post-completion text

### Task 3.2: Execution checks

- [ ] Run targeted tests for integration event model and next-machine finalize flow
- [ ] Run `make test`
- [ ] Run `make lint`

## Requirement Traceability

- Task 1.1 -> FR1, FR4
- Task 1.2 -> FR3, FR4
- Task 2.1 -> FR2, FR5
- Task 2.2 -> FR2, FR5
- Task 3.1 / 3.2 -> Success Criteria verification for FR1-FR5
