# Implementation Plan - unified-client-adapter-pipeline

## Objective

Unify Web and TUI with the same adapter pipeline and realtime contract used by other adapters, eliminating bypass paths for core output delivery.

## Requirement Traceability

- Phase 1 -> R1, R5
- Phase 2 -> R2, R4
- Phase 3 -> R2
- Phase 4 -> R3, R4
- Phase 5 -> non-functional compatibility requirements, risks
- Phase 6 -> acceptance criteria 1-5

## Phase 0 - Baseline Inventory

- [ ] Inventory current Web/TUI output and input paths, including all live-output bypass call sites.
- [ ] Map each bypass path to the target adapter/distributor route before code changes.
- [ ] Confirm no new third-party integrations are required for this todo.

### Files (expected)

- `teleclaude/api/streaming.py`
- `teleclaude/core/adapter_client.py`
- `teleclaude/core/polling_coordinator.py`
- `teleclaude/core/agent_coordinator.py`
- architecture/spec docs referenced by requirements

## Phase 1 - Canonical Realtime Contract

- [ ] Define canonical event payload schema for client-facing realtime updates.
- [ ] Align event naming with target activity contract (`user_prompt_submit`, `agent_output_update`, `agent_output_stop`).
- [ ] Document required fields and compatibility rules.
- [ ] Add contract validation helpers and shared serializers.

### Files (expected)

- adapter client contract/schema modules in `teleclaude/core/*` and/or `teleclaude/api/*`
- project/spec docs for realtime payloads

## Phase 2 - Web Adapter Alignment

- [ ] Introduce or align a dedicated Web adapter lane to consume canonical contract events.
- [ ] Replace direct web bypass output path with adapter-driven updates.
- [ ] Keep protocol translation (SSE/UIMessage stream formatting) at the adapter edge only.
- [ ] Keep snapshot/history endpoints as read APIs, not realtime bypass producers.

### Files (expected)

- `teleclaude/api_server.py`
- web adapter/session streaming modules under `teleclaude/adapters/*` and/or `teleclaude/api/*`

## Phase 3 - TUI Alignment

- [ ] Ensure TUI realtime updates consume the same canonical contract as Web.
- [ ] Remove TUI-specific bypasses for core output progression.
- [ ] Keep TUI-specific presentation logic local to TUI components only.

### Files (expected)

- `teleclaude/cli/*`
- adapter/realtime transport modules shared with Web lane

## Phase 4 - Ingress and Provisioning Harmonization

- [ ] Standardize input mapping for Web/TUI/Telegram/Discord through one command ingress contract.
- [ ] Centralize channel/provisioning decisions in adapter orchestration.
- [ ] Remove duplicate per-client routing logic where contract already covers it.

### Files (expected)

- `teleclaude/core/command_handlers.py`
- `teleclaude/core/adapter_client.py`
- adapter-specific ingress glue where necessary

## Phase 5 - Migration and Cutover

- [ ] Add migration toggle/shadow mode to compare legacy and unified paths.
- [ ] Capture parity metrics and verify no duplicate sends.
- [ ] Document compatibility window and explicit rollback trigger.
- [ ] Remove legacy bypass paths after parity criteria pass.

### Files (expected)

- runtime config/feature-flag modules
- relevant API/adapter glue modules

## Phase 6 - Validation

- [ ] Unit tests for canonical payload schema and serialization.
- [ ] Integration tests for Web and TUI parity on the same session updates.
- [ ] Regression tests for input provenance and delivery consistency.
- [ ] Observability assertions for per-adapter delivery traceability.

### Files (expected)

- `tests/unit/*` contract tests
- `tests/integration/*` web/tui parity tests

## Rollout Notes

- This todo must start only after `transcript-first-output-and-hook-backpressure` is complete.
- Prefer progressive cutover with explicit parity checks before legacy path removal.

## Definition of Done

- [ ] One canonical realtime contract is used across Web/TUI and adapter lanes.
- [ ] Core output progression no longer uses bypass paths.
- [ ] Delivery and provenance behavior is consistent across all clients.
