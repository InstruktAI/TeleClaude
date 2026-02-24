# Implementation Plan: ucap-ingress-provisioning-harmonization

## Overview

Align ingress and provisioning behavior around existing shared boundaries rather than introducing new pathways.
This phase should tighten and verify behavior across `CommandMapper`, command handlers, and `AdapterClient`
so adapter differences remain edge concerns only.

## Requirement Traceability

- Phase 0 -> R1, R2, R3, R4
- Phase 1 -> R1, R2
- Phase 2 -> R3, R4
- Phase 3 -> R5 + Success Criteria 1-4

## Preconditions

- `ucap-canonical-contract` is complete enough to reference stable ingress/provenance contract expectations.
- Scope decisions are explicit:
  - interactive ingress boundary (Web/TUI/Telegram/Discord)
  - provisioning boundary (UI adapters vs broader transport behavior)

## Phase 0: Baseline Audit and Boundary Lock

### Task 0.1: Inventory ingress and provenance update points

**File(s):** `teleclaude/core/command_mapper.py`, `teleclaude/core/command_handlers.py`, `teleclaude/api_server.py`

- [ ] Enumerate all interactive input paths that produce `ProcessMessageCommand` or adjacent command types.
- [ ] Document where `origin`, actor attribution, and `last_input_origin` are set/updated.
- [ ] Mark any duplicated or conflicting origin/provenance mutations.

### Task 0.2: Inventory provisioning call sites

**File(s):** `teleclaude/core/adapter_client.py`, `teleclaude/adapters/ui_adapter.py`, `teleclaude/adapters/telegram_adapter.py`, `teleclaude/adapters/discord_adapter.py`

- [ ] Confirm all UI message paths pass through `ensure_ui_channels()` before delivery.
- [ ] Identify direct/duplicate channel creation patterns that bypass shared orchestration intent.
- [ ] Record adapter-specific exceptions that are intentional (for example customer skip behavior).

---

## Phase 1: Ingress Semantics Harmonization

### Task 1.1: Normalize command ingress semantics

**File(s):** `teleclaude/core/command_mapper.py`, `teleclaude/api_server.py`

- [ ] Ensure interactive entry points produce consistent `origin` and actor attribution values.
- [ ] Keep adapter-specific extraction at mapper edges, not in downstream core branches.

### Task 1.2: Normalize provenance write timing

**File(s):** `teleclaude/core/command_handlers.py`, `teleclaude/adapters/ui_adapter.py`

- [ ] Ensure `last_input_origin` updates occur before feedback/fanout operations that depend on it.
- [ ] Remove or reconcile duplicated provenance mutation points where they can drift.
- [ ] Preserve current behavior for headless/session-adoption flows.

---

## Phase 2: Provisioning Orchestration Tightening

### Task 2.1: Enforce single provisioning funnel usage

**File(s):** `teleclaude/core/adapter_client.py`

- [ ] Verify UI delivery paths depend on `ensure_ui_channels()` and per-session provisioning lock behavior.
- [ ] Tighten call-site behavior where provisioning can be skipped incorrectly or repeated unnecessarily.

### Task 2.2: Align adapter ensure-channel implementations with orchestration contract

**File(s):** `teleclaude/adapters/telegram_adapter.py`, `teleclaude/adapters/discord_adapter.py`, `teleclaude/adapters/ui_adapter.py`

- [ ] Keep adapter-specific channel rules explicit and minimal.
- [ ] Ensure channel ID persistence and recovery logic remain compatible with shared orchestration.
- [ ] Avoid introducing new adapter-to-core coupling.

---

## Phase 3: Validation and Readiness Evidence

### Task 3.1: Unit and integration coverage updates

**File(s):** `tests/unit/test_command_mapper.py`, `tests/unit/test_command_handlers.py`, `tests/unit/test_adapter_client.py`, `tests/unit/test_adapter_client_handlers.py`, `tests/unit/test_telegram_adapter.py`, `tests/unit/test_discord_adapter.py`, `tests/integration/test_multi_adapter_broadcasting.py`

- [ ] Add/update tests for command mapping parity, provenance updates, and provisioning orchestration paths.
- [ ] Verify adapter-specific exceptions remain intentional and covered.

### Task 3.2: Validation commands

- [ ] Run targeted test commands listed in `demo.md`.
- [ ] Run `make lint`.
- [ ] Verify no unchecked implementation tasks remain.

---

## Phase 4: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
