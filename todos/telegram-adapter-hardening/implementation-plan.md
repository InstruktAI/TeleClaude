# Implementation Plan: telegram-adapter-hardening

## Overview

Apply hardening in small, verifiable phases: unify routing first, then contract cleanup, then bounded cleanup behavior and ownership hardening, followed by layering cleanup.

## Phase 1: Single Delivery Funnel

### Task 1.1: Route all Telegram UI sends through one lane

**File(s):** `teleclaude/core/adapter_client.py`

- [x] Remove origin-path bypass for Telegram UI delivery.
- [x] Keep observer broadcast behavior explicit.
- [x] Emit structured routing outcome logs.

## Phase 2: Contract Normalization

### Task 2.1: Normalize delivery return contract

**File(s):** `teleclaude/adapters/telegram/message_ops.py`, `teleclaude/adapters/telegram_adapter.py`

- [ ] Replace empty-string/ambiguous success sentinels with explicit typed outcomes.
- [ ] Ensure missing routing metadata propagates as explicit failure.

## Phase 3: Invalid Topic Suppression + Cleanup Safety

### Task 3.1: Suppress repeated invalid-topic deletes

**File(s):** `teleclaude/adapters/telegram/channel_ops.py`, `teleclaude/adapters/telegram/input_handlers.py`, `teleclaude/adapters/telegram_adapter.py`

- [ ] Add cooldown/backoff for repeated `Topic_id_invalid` delete attempts.
- [ ] Centralize orphan-topic delete invocation semantics.

## Phase 4: Ownership Hardening

### Task 4.1: Require stronger ownership evidence for deletes

**File(s):** `teleclaude/adapters/telegram_adapter.py`, `teleclaude/adapters/telegram/channel_ops.py`

- [ ] Replace weak title-only ownership checks as authoritative signal.
- [ ] Fail safe (no delete) on uncertain ownership with diagnostics.

## Phase 5: Layering Cleanup

### Task 5.1: Reduce fallback-policy duplication across layers

**File(s):** `teleclaude/core/adapter_client.py`, `teleclaude/adapters/telegram_adapter.py`, `teleclaude/adapters/telegram/*.py`

- [ ] Keep AdapterClient as orchestration boundary.
- [ ] Move Telegram-specific fallback policy into Telegram adapter internals.

## Verification

### Task V.1: Behavior validation

- [ ] Verify no direct Telegram UI-send bypass remains.
- [ ] Verify repeated invalid-topic triggers are bounded by cooldown.
- [ ] Verify failure outcomes are explicit and observable.

### Task V.2: Quality checks

- [ ] Run targeted validation for touched behavior.
- [ ] Confirm implementation tasks are fully checked before review.
