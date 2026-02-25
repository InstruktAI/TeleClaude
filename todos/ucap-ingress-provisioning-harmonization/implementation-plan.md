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

- [x] Enumerate all interactive input paths that produce `ProcessMessageCommand` or adjacent command types.
- [x] Document where `origin`, actor attribution, and `last_input_origin` are set/updated.
- [x] Mark any duplicated or conflicting origin/provenance mutations.

**Audit notes:**

- `CommandMapper.map_telegram_input("message", ...)` → `ProcessMessageCommand` with `origin=metadata.origin or TELEGRAM`; actor extracted via `_extract_actor_from_channel_metadata` using `telegram_user_id` fallback.
- `CommandMapper.map_redis_input("message", ...)` → `ProcessMessageCommand` with `origin` from parameter; actor extracted similarly. MCP origin gets a synthetic `system:<computer>` actor_id.
- `CommandMapper.map_api_input("message", ...)` → `ProcessMessageCommand` with `origin=metadata.origin or API`; actor from payload fields with channel_metadata fallback.
- `process_message()` (command_handlers.py:899-904): updates `last_input_origin=cmd.origin` in DB **before** `broadcast_user_input()` at line 906. Ordering is correct.
- `handle_voice()` (command_handlers.py:763-764): updates `last_input_origin=cmd.origin` **before** feedback status at lines 768+. Comment explicitly documents this. Ordering is correct.
- `create_session()` sets `last_input_origin=origin` from the command at creation time. No inheritance from parent (documented as intentional).
- `run_agent_command()` updates `last_input_origin=cmd.origin` in DB.
- No duplicated or conflicting provenance mutations found. Each handler owns exactly one provenance write per call.

### Task 0.2: Inventory provisioning call sites

**File(s):** `teleclaude/core/adapter_client.py`, `teleclaude/adapters/ui_adapter.py`, `teleclaude/adapters/telegram_adapter.py`, `teleclaude/adapters/discord_adapter.py`

- [x] Confirm all UI message paths pass through `ensure_ui_channels()` before delivery.
- [x] Identify direct/duplicate channel creation patterns that bypass shared orchestration intent.
- [x] Record adapter-specific exceptions that are intentional (for example customer skip behavior).

**Audit notes:**

- `_route_to_ui()` (adapter_client.py:265) calls `ensure_ui_channels(session)` as first action before any fanout. All output paths (`send_message`, `send_threaded_output`, `send_output_update`, `edit_message`, `delete_message`, `send_file`, `update_channel_title`) route through `_route_to_ui()`.
- `delete_channel()` deliberately bypasses `ensure_ui_channels()` to avoid creating channels during teardown. This is intentional.
- `broadcast_user_input()` uses `_fanout_excluding()` directly (not `_route_to_ui()`), bypassing channel provisioning for reflections. This is intentional: reflections are sent to already-provisioned adapters.
- `ensure_ui_channels()` uses a per-session asyncio.Lock to prevent concurrent provisioning races.
- `UiAdapter.ensure_channel()` is a no-op base implementation; subclasses override for platform-specific provisioning.
- No direct channel creation that bypasses `ensure_ui_channels()` was found in the output path.
- Telegram customer-session skip: TelegramAdapter's `ensure_channel()` in `ChannelOperationsMixin` handles the customer skip behavior as an adapter-specific exception within the shared funnel.

---

## Phase 1: Ingress Semantics Harmonization

### Task 1.1: Normalize command ingress semantics

**File(s):** `teleclaude/core/command_mapper.py`, `teleclaude/api_server.py`

- [x] Ensure interactive entry points produce consistent `origin` and actor attribution values.
- [x] Keep adapter-specific extraction at mapper edges, not in downstream core branches.

**Notes:** All mapper paths (`map_telegram_input`, `map_redis_input`, `map_api_input`) already produce consistent `origin` and actor fields. Adapter-specific extraction (Telegram `telegram_user_id`, Discord `discord_user_id`) is confined to `_extract_actor_from_channel_metadata`. No downstream core branching on adapter type. Tests added in Task 3.1.

### Task 1.2: Normalize provenance write timing

**File(s):** `teleclaude/core/command_handlers.py`, `teleclaude/adapters/ui_adapter.py`

- [x] Ensure `last_input_origin` updates occur before feedback/fanout operations that depend on it.
- [x] Remove or reconcile duplicated provenance mutation points where they can drift.
- [x] Preserve current behavior for headless/session-adoption flows.

**Notes:** `process_message()` updates provenance before broadcast; `handle_voice()` updates provenance before feedback. No duplicated mutations. Tests added in Task 3.1.

---

## Phase 2: Provisioning Orchestration Tightening

### Task 2.1: Enforce single provisioning funnel usage

**File(s):** `teleclaude/core/adapter_client.py`

- [x] Verify UI delivery paths depend on `ensure_ui_channels()` and per-session provisioning lock behavior.
- [x] Tighten call-site behavior where provisioning can be skipped incorrectly or repeated unnecessarily.

**Notes:** All output paths go through `_route_to_ui()` which calls `ensure_ui_channels()` first. Lock prevents concurrent provisioning races. `delete_channel()` intentionally bypasses provisioning. No tightening needed. Tests added in Task 3.1.

### Task 2.2: Align adapter ensure-channel implementations with orchestration contract

**File(s):** `teleclaude/adapters/telegram_adapter.py`, `teleclaude/adapters/discord_adapter.py`, `teleclaude/adapters/ui_adapter.py`

- [x] Keep adapter-specific channel rules explicit and minimal.
- [x] Ensure channel ID persistence and recovery logic remain compatible with shared orchestration.
- [x] Avoid introducing new adapter-to-core coupling.

**Notes:** `UiAdapter.ensure_channel()` is a clean no-op base. Subclass overrides stay adapter-specific. No new coupling introduced. Tests added in Task 3.1.

---

## Phase 3: Validation and Readiness Evidence

### Task 3.1: Unit and integration coverage updates

**File(s):** `tests/unit/test_command_mapper.py`, `tests/unit/test_command_handlers.py`, `tests/unit/test_adapter_client.py`, `tests/unit/test_adapter_client_handlers.py`, `tests/unit/test_telegram_adapter.py`, `tests/unit/test_discord_adapter.py`, `tests/integration/test_multi_adapter_broadcasting.py`

- [x] Add/update tests for command mapping parity, provenance updates, and provisioning orchestration paths.
- [x] Verify adapter-specific exceptions remain intentional and covered.

### Task 3.2: Validation commands

- [ ] Run targeted test commands listed in `demo.md`.
- [ ] Run `make lint`.
- [ ] Verify no unchecked implementation tasks remain.

---

## Phase 4: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
