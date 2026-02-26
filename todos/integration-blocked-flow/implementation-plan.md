# Implementation Plan: integration-blocked-flow

## Overview

Implement a deterministic blocked-integration pipeline that records
`integration_blocked` evidence, creates or reuses a follow-up todo, and returns
clear resume guidance. Reuse existing todo scaffolding and roadmap/data-layer
patterns to avoid introducing new operational surfaces.

---

## Phase 1: Core Changes

### Task 1.1: Add blocked-flow persistence model and DB APIs

**File(s):** `teleclaude/core/schema.sql`, `teleclaude/core/migrations/024_add_integration_blocked_flow.py` (new), `teleclaude/core/db_models.py`, `teleclaude/core/db.py`

- [ ] Add persistent storage for blocked outcomes keyed by candidate identity.
- [ ] Persist blocked reason, evidence metadata, and linked follow-up slug.
- [ ] Add DB methods for idempotent insert/update so repeated blocked events do
      not create duplicate records.
- Requirements: `R1`, `R3`, `R6`

### Task 1.2: Implement follow-up todo creation/reuse service

**File(s):** `teleclaude/core/integration/blocked_flow.py` (new), `teleclaude/todo_scaffold.py`, `teleclaude/core/next_machine/core.py` (roadmap helper reuse only)

- [ ] Add a blocked-flow service that materializes or reuses a deterministic
      follow-up slug for a blocked candidate.
- [ ] Reuse todo scaffold + roadmap mutation helpers (no ad-hoc file writes).
- [ ] Seed follow-up context with candidate identity, blocked reason, and resume
      intent in todo artifacts.
- [ ] Preserve idempotency for repeated blocked events.
- [ ] If follow-up creation fails, persist blocked evidence and return explicit
      manual resume instructions instead of dropping blocked context.
- Requirements: `R2`, `R3`, `R4`, `R5`, `R6`

### Task 1.3: Wire blocked-flow at the integration apply seam

**File(s):** cutover-owned integration apply module(s), `teleclaude/core/integration/blocked_flow.py`, `teleclaude/core/next_machine/core.py` (only if fallback finalize path still routes blocked outcomes)

- [ ] Invoke blocked-flow service whenever integration apply resolves to blocked.
- [ ] Ensure blocked path records evidence and links to follow-up before return.
- [ ] Keep canonical `main` untouched on blocked outcomes.
- [ ] Keep queue/candidate state explicitly `blocked` until remediation and retry.
- Requirements: `R1`, `R2`, `R5`, `R6`

### Task 1.4: Add deterministic resume UX output and documentation updates

**File(s):** `teleclaude/core/next_machine/core.py` (or cutover-owned orchestrator response surface), `docs/project/spec/integration-orchestrator.md`, `docs/project/procedure/troubleshooting.md`

- [ ] Standardize blocked response text to include reason, follow-up slug, and
      explicit resume commands.
- [ ] Document operator flow for blocked -> follow-up -> retry integration.
- [ ] Keep message contract stable for tests and adapter display parity.
- Requirements: `R4`, `R6`

---

## Phase 2: Validation

### Task 2.1: Tests

**File(s):** `tests/unit/test_integration_blocked_flow.py` (new), `tests/unit/test_next_machine_state_deps.py`, `tests/unit/test_next_machine_hitl.py`, `tests/unit/test_todo_scaffold.py`

- [ ] Add tests for blocked payload validation and persisted evidence.
- [ ] Add tests that first blocked event creates follow-up todo and replay reuses it.
- [ ] Add tests for deterministic resume guidance content.
- [ ] Add regression tests proving blocked flow cannot push canonical `main`.
- Requirements: `R1`, `R2`, `R3`, `R4`, `R5`, `R7`

### Task 2.2: Operational verification

- [ ] Validate log observability with `instrukt-ai-logs teleclaude --since <window> --grep <pattern>`.
- [ ] Verify follow-up todo appears in roadmap/todos with source linkage.
- [ ] Verify repeat blocked events append evidence without creating extra follow-up todos.
- Requirements: `R2`, `R3`, `R6`, `R7`

### Task 2.3: Quality checks

- [ ] Run targeted blocked-flow tests.
- [ ] Run `make lint`.
- [ ] Run `make test`.
- [ ] Verify no unchecked implementation tasks remain.
- Requirements: `R7`

---

## Phase 3: Review Readiness

- [ ] Confirm each task traces to requirements `R1`-`R7`.
- [ ] Confirm implementation tasks are all marked `[x]`.
- [ ] Document any explicit deferrals in `deferrals.md` (if needed).
- Requirements: `R7`

## Requirement Traceability

- Task 1.1 -> `R1`, `R3`, `R6`
- Task 1.2 -> `R2`, `R3`, `R4`, `R5`, `R6`
- Task 1.3 -> `R1`, `R2`, `R5`, `R6`
- Task 1.4 -> `R4`, `R6`
- Task 2.1-2.3 -> `R7` and verification of `R1`-`R6`

## Potential Follow-up (separate todo)

- If blocked-volume analytics or escalations become necessary, split a separate
  observability/reporting todo instead of expanding this slice.
