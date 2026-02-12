# Implementation Plan: telegram-routing-contract-hardening

## Overview

First harden the routing funnel in `AdapterClient`, then normalize Telegram send contracts, then verify behavior and call-site handling.

## Phase 1: Routing Funnel Enforcement

### Task 1.1: Eliminate Telegram UI send bypasses

**File(s):** `teleclaude/core/adapter_client.py`

- [ ] Route Telegram UI-bound sends through `_run_ui_lane()`.
- [ ] Preserve observer behavior while removing direct origin bypass.
- [ ] Add structured logs for lane decision and outcome.

## Phase 2: Delivery Contract Normalization

### Task 2.1: Normalize send result semantics

**File(s):** `teleclaude/adapters/telegram/message_ops.py`, `teleclaude/adapters/telegram_adapter.py`

- [ ] Replace empty-string sentinel usage with explicit success/failure contract.
- [ ] Ensure missing metadata returns explicit failure.
- [ ] Update immediate caller expectations to match the contract.

## Phase 3: Verification

### Task 3.1: Behavior validation

- [ ] Confirm no Telegram origin bypass remains.
- [ ] Confirm missing routing metadata is observable as failure.
- [ ] Confirm logs expose route -> recovery -> final outcome chain.

### Task 3.2: Readiness for review

- [ ] Verify requirements are satisfied by implementation tasks.
- [ ] Verify task checklist is complete.
- [ ] Record any explicit deferrals if discovered.
