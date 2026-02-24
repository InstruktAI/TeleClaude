# Implementation Plan: adapter-output-delivery

## Overview

This delivery establishes the routing contract across origin UX, dual output, and reflection lanes, with actor-attributed cross-adapter reflection and Discord webhook rendering support.

---

## Phase 1: Delivery Scope Contract

### Task 1.1: Enforce message-intent scope behavior

**File(s):** `teleclaude/core/adapter_client.py`, `teleclaude/core/ui_adapter.py`, `teleclaude/core/command_handlers.py`

- [x] Keep `feedback_notice_error_status` as `ORIGIN_ONLY`.
- [x] Keep `last_output_summary` as `ORIGIN_ONLY` and non-threaded/in-edit UX only.
- [x] Keep stream output delivery as `DUAL`.

### Task 1.2: Reflection lane fanout

**File(s):** `teleclaude/core/adapter_client.py`, `teleclaude/core/command_handlers.py`

- [x] Reflect input to all provisioned non-source adapters.
- [x] Keep reflection lane semantics independent from cleanup trigger semantics.
- [x] Apply reflection lane behavior for text, voice, and MCP origins.

---

## Phase 2: Actor Attribution Pipeline

### Task 2.1: Command/model actor fields

**File(s):** `teleclaude/types/commands.py`, `teleclaude/core/models.py`

- [x] Add actor identity/display/avatar fields to command/message metadata.
- [x] Preserve fallback behavior when adapter-provided identity is unavailable.

### Task 2.2: Metadata propagation through core paths

**File(s):** `teleclaude/core/command_mapper.py`, `teleclaude/transport/redis_transport.py`, `teleclaude/mcp/handlers.py`, `teleclaude/core/agent_coordinator.py`, `teleclaude/core/command_handlers.py`

- [x] Propagate actor metadata through mapper, transport, and handler layers.
- [x] Ensure reflection rendering receives normalized actor metadata.

---

## Phase 3: Adapter Rendering

### Task 3.1: Discord reflection presentation

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [x] Use webhook-based reflection rendering when available.
- [x] Keep safe fallback to normal adapter send path.

### Task 3.2: Telegram/Discord input metadata capture

**File(s):** `teleclaude/adapters/telegram/input_handlers.py`, `teleclaude/adapters/telegram_adapter.py`, `teleclaude/adapters/discord_adapter.py`

- [x] Capture best-effort actor identity at adapter boundaries.
- [x] Feed captured metadata into reflection pipeline.

---

## Phase 4: Validation and Build Gates

### Task 4.1: Tests and lint

- [x] Validate updated routing/attribution paths with targeted unit coverage.
- [x] Run `make test` and `make lint` for build-gate validation.

### Task 4.2: Demo and artifacts

- [x] Validate `telec todo demo adapter-output-delivery`.
- [x] Keep todo artifacts synchronized with the implemented routing contract.

---

## Review Handoff

- [x] Requirements and implementation plan aligned with the lane model used by the code.
- [x] Routing behavior is documented in `docs/project/spec/session-output-routing.md`.
- [x] Reviewer context should use this plan and requirements as canonical for this todo.
