# Implementation Plan: integration-events-model

## Plan Objective

Introduce a durable event/projection layer that computes integration readiness
from canonical signals only.

## Phase 1: Event Contract and Persistence

### Task 1.1: Implement canonical event validation and storage

**File(s):** `teleclaude/core/integration/events.py`, `teleclaude/core/integration/event_store.py`

- [x] Define typed event models and required field validation.
- [x] Persist accepted events in append-only storage with idempotency keys.

### Task 1.2: Build readiness projection and supersession rules

**File(s):** `teleclaude/core/integration/readiness_projection.py`

- [x] Compute readiness for `(slug, branch, sha)` from canonical events.
- [x] Implement supersession for older slug candidates.

## Phase 2: Integration and Diagnostics

### Task 2.1: Wire projection updates to event ingestion

**File(s):** `teleclaude/core/integration/service.py`

- [x] Update projection on event append/replay.
- [x] Emit diagnostics for rejected or superseded candidates.

### Task 2.2: Add tests and quality checks

**File(s):** `tests/unit/test_integration_events_model.py`, `tests/integration/test_integration_readiness_projection.py`

- [ ] Add coverage for validation, idempotency, readiness, and supersession.
- [ ] Run `make test`.
- [ ] Run `make lint`.

## Phase 3: Review Readiness

- [ ] Confirm every task traces to FR1-FR4.
- [ ] Confirm no non-canonical trigger path affects readiness.
