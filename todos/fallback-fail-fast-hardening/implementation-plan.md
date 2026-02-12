# Implementation Plan: fallback-fail-fast-hardening

## Plan Objective

Remove contract-breaking fallback behavior one concern at a time while preserving operational stability and observability.

## Phase 1: Ingress Contract Tightening

### Task 1.1: Remove sentinel coercion for required session creation fields

**File(s):** `teleclaude/core/command_mapper.py`, related command DTO creation paths

- [ ] Stop coercing missing required `project_path` to empty string.
- [ ] Surface explicit validation failure at ingress boundary.

### Task 1.2: Restrict `help-desk` routing to explicit role-based jail only

**File(s):** `teleclaude/core/command_handlers.py`

- [ ] Preserve existing jail path only when explicit non-admin role is resolved.
- [ ] Remove broad missing-path reroute behavior that is not role-based.
- [ ] Keep log messages explicit and policy-aligned.

Verification:

- [ ] Update/align unit + integration tests for fail-fast ingress behavior.

## Phase 2: Session Data Response Contract

### Task 2.1: Make transcript availability explicit

**File(s):** `teleclaude/core/command_handlers.py`, caller tests

- [ ] Add explicit availability state in payload.
- [ ] Ensure pending transcript state is distinguishable from empty output.
- [ ] Remove ambiguous empty-success semantics for unavailable transcript scenarios.

Verification:

- [ ] Targeted tests for transcript-present, tmux-fallback, and pending states.

## Phase 3: Telegram Parse/Footer Hardening

### Task 3.1: Parse-entities failure handling audit and consolidation

**File(s):** `teleclaude/adapters/telegram/message_ops.py`, `teleclaude/adapters/ui_adapter.py`, related tests

- [ ] Confirm single footer mechanism in runtime path.
- [ ] Remove/replace any parse-entities fallback that can emit duplicate footer state.
- [ ] Add reason-coded logs for parse fallback branches.

Verification:

- [ ] Regression test for parse error path with no duplicate footer artifact.

## Phase 4: Invalid-Topic Cleanup Suppression

### Task 4.1: Add bounded suppression/backoff for repeated invalid-topic cleanup attempts

**File(s):** `teleclaude/adapters/telegram/input_handlers.py`, `teleclaude/adapters/telegram_adapter.py`, `teleclaude/adapters/telegram/channel_ops.py`

- [ ] Add short-lived suppression memory for non-retryable invalid-topic outcomes.
- [ ] Prevent repeated delete attempts on same invalid topic in tight loop.
- [ ] Preserve ownership safeguards while reducing hammer/noise behavior.

Verification:

- [ ] Tests for repeated invalid-topic events resulting in bounded cleanup attempts.

## Phase 5: Fallback Governance and Closure

### Task 5.1: Final pass on touched fallback paths

**File(s):** paths touched in phases 1-4

- [ ] Ensure no hidden fail-open/sentinel-success behavior remains in scope.
- [ ] Ensure structured logs include route, fallback reason, and outcome.
- [ ] Update `todos/telegram-fallback-audit-2026-02-12.md` with closure notes per item addressed.

Verification:

- [ ] `make lint`
- [ ] `make test`

## Execution Notes

1. Execute phases serially; do not merge half-contract state between phases.
2. Keep commits atomic per phase to simplify rollback and review.
3. If scope exceeds one build session, split into dependent child todos by phase.
