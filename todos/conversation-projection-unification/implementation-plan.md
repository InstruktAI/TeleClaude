# Implementation Plan: conversation-projection-unification

## Overview

Build a reusable core output projection route, wire every current producer/consumer through it in phases, and lock current adapter-visible behavior in place with regression tests. This todo does not modify adapter implementations.

## Phase 1: Canonical Output Projection Route

### Task 1.1: Define canonical projection models and route

**File(s):**
- `teleclaude/output_projection/` (new package)
- `teleclaude/utils/transcript.py` (existing shared utilities)

**Existing foundation to reuse:**
- `StructuredMessage` dataclass (`transcript.py:2024`) — role, type, text, timestamp, entry_index, file_index
- `normalize_transcript_entry_message()` (`transcript.py:170`) — single normalization entry point for Claude/Codex/Gemini
- `iter_assistant_blocks()` (`transcript.py:207`) — yields (block, entry_timestamp) for assistant blocks
- `MessageDTO` (`api_models.py:498`) — current API output model

- [x] Define canonical projection models for:
  - `terminal_live` — wraps poller tmux snapshot output
  - `conversation` — extends or composes `StructuredMessage` with visibility annotations
- [x] Define one core route/service interface for requesting projected output from producers/consumers
- [x] Encode visibility policy centrally instead of per-consumer (replacing the scattered `include_tools`/`include_thinking` boolean flags)
- [x] Make user-visible tool/widget allowance explicit rather than inferred by the web serializer
- [x] Support transcript-chain traversal and incremental projection from a cursor/since marker (reusing `_parse_timestamp()` at `transcript.py:670` and `_should_skip_entry()` at `transcript.py:235`)

### Task 1.2: Add serializers/adapters on top of the canonical route

**File(s):**
- `teleclaude/output_projection/serializers.py` (new)
- `teleclaude/api/transcript_converter.py` (refactor from classifier to serializer)

**Current state of `convert_entry()` (`transcript_converter.py:159`):** dispatches on block_type to `convert_text_block`, `convert_thinking_block`, `convert_tool_use_block`, `convert_tool_result_block` — all without visibility filtering. These converters produce AI SDK v5 UIMessage Stream SSE events. After this task, they accept already-projected blocks instead of raw transcript entries.

- [x] Add serializer for structured message API output (replacing direct `StructuredMessage.to_dict()` → `MessageDTO` conversion in `api_server.py:1228-1238`)
- [x] Add serializer for AI SDK / web SSE output (refactoring `convert_entry()` to accept projected blocks)
- [x] Add serializer/adapter for existing standard `send_output_update()` payload production (thin — poller output is already a string)
- [x] Add serializer/adapter for existing threaded `send_threaded_output()` payload production (replacing `render_agent_output`/`render_clean_agent_output` markdown formatting)
- [x] Define a stable consumer contract so future mirror/search adoption reuses the same route (currently `history/search.py:collect_transcript_messages()` has its own extraction)
- [x] Ensure `transcript_converter.py` becomes a serializer over projected parts, not a raw transcript classifier

---

## Phase 2: Producer Cutover

### Task 2.1: Cut over poller-driven standard output producer

**File(s):**
- `teleclaude/core/polling_coordinator.py` (`poll_and_send_output()` at line 800)
- `teleclaude/output_projection/`

**Current flow:** `poll_and_send_output()` strips ANSI codes from tmux snapshot → calls `adapter_client.send_output_update(session, clean_output, started_at, last_changed_at)` directly.

- [x] Route poller output through the shared `terminal_live` projection
- [x] Preserve existing `AdapterClient.send_output_update()` call shape (signature at `adapter_client.py:545`)
- [x] Keep adapter behavior unchanged; only the core-produced payload path changes

### Task 2.2: Cut over transcript-driven threaded producer

**File(s):**
- `teleclaude/core/agent_coordinator.py` (`trigger_incremental_output()` at line 1307)
- `teleclaude/output_projection/`

**Current flow:** `trigger_incremental_output()` calls `render_clean_agent_output()` (hardcoded: no tool results, tools hidden) or `render_agent_output()` (configurable flags) → passes markdown string to `send_threaded_output(session, text)`.

- [x] Route incremental threaded rendering through the shared `conversation` projection
- [x] Preserve existing `send_threaded_output()` behavior and adapter-facing contract (signature at `adapter_client.py:461`)
- [x] Do not change threaded pagination/presentation semantics in this todo

### Task 2.3: Cut over session history API

**File(s):**
- `teleclaude/api_server.py` (`get_session_messages()` at line 1182)

**Current flow:** `get_session_messages()` calls `extract_messages_from_chain(file_paths, agent_name, since=..., include_tools=False, include_thinking=...)` → wraps results in `MessageDTO` → returns `SessionMessagesDTO`. Fallback at line 1242 uses `get_command_service().get_session_data()` for sessions without transcript content.

- [x] Replace `extract_messages_from_chain()` call with the shared conversation projector → serializer chain
- [x] Preserve current external API shape for `/sessions/{id}/messages` (`SessionMessagesDTO`/`MessageDTO` at `api_models.py:498-518`)
- [x] Keep the existing tmux/session-data fallback behavior unchanged for sessions without transcript content

### Task 2.4: Cut over live SSE stream

**File(s):**
- `teleclaude/api/streaming.py` (`_stream_sse()` at line 146)
- `teleclaude/api/transcript_converter.py` (`convert_entry()` at line 159)

**Current flow:** `_stream_sse()` iterates transcript JSONL files via `_iter_entries_for_file()`, calls `convert_entry(entry)` for each entry (no visibility filtering), yields SSE events. Live tail at line 211 parses new JSONL lines incrementally and also calls `convert_entry()` unfiltered. **This is the confirmed leak point.**

- [x] Replace raw `convert_entry(entry)` replay with projection → SSE serializer chain
- [x] Use the same visibility policy as the history API (tools/thinking hidden by default)
- [x] Ensure live transcript tailing emits only projected web-visible conversation parts
- [x] Keep the existing request/response transport contract unchanged for the Next.js proxy

### Task 2.5: Protect explicitly user-visible tools/widgets

**File(s):**
- `teleclaude/output_projection/`
- web serialization tests

- [x] Define an explicit allowlist/mechanism for tools that are intentionally rendered in web chat
- [x] Suppress internal tools by default
- [x] Add tests covering both allowlisted and suppressed tool cases

### Task 2.6: Prepare mirror/search adoption

**File(s):**
- `teleclaude/history/search.py` (`collect_transcript_messages()` — has its own extraction via `normalize_transcript_entry_message()` + `_extract_text_from_content()`)

- [x] Define the handoff point for mirror/search consumers to use the shared conversation projection route
- [x] Do not implement full mirror/search cutover here unless it is cheap and low risk

---

## Phase 3: Regression Bar

### Task 3.1: Web parity tests

**File(s):**
- `tests/unit/test_transcript_converter.py`
- new projection tests under `tests/unit/`

- [x] Add fixture-based tests showing that the same transcript yields matching visible content for:
  - history API projection
  - web live SSE projection
- [x] Add regression test for the current leak: internal tools must not surface in web chat

### Task 3.2: Threaded-mode protection tests

**File(s):**
- `tests/unit/test_threaded_output_updates.py`
- `tests/unit/test_agent_coordinator.py`

- [x] Add explicit non-regression coverage for current threaded-mode behavior
- [x] Confirm this todo does not change threaded-mode adapter-facing behavior
- [x] Confirm threaded-mode producer cutover preserves current visible behavior

### Task 3.3: Standard adapter push protection tests

**File(s):**
- `tests/unit/test_polling_coordinator.py`
- `tests/unit/test_adapter_client.py`

- [x] Add non-regression coverage for poller-driven `send_output_update()` payload production
- [x] Confirm core-route cutover does not change existing adapter-visible standard output behavior

---

## Phase 4: Roadmap and Docs Alignment

### Task 4.1: Update owning todo/bug references

**File(s):**
- `todos/web-frontend-test-bugs/bug.md`
- roadmap artifacts as needed

- [x] Record the web symptom and root cause under the web bug bucket
- [x] Reference this todo as the architectural owner for the visible web stream/history mismatch

### Task 4.2: Update architecture docs

**File(s):**
- `docs/project/design/architecture/web-interface.md`
- `docs/project/design/architecture/web-api-facade.md`
- any projection-specific design note added during implementation

- [x] Document that web history and live stream share the same conversation projection contract
- [x] Remove stale language that implies web live streaming is already "cleaned" if the implementation still diverges

---

## Phase 5: Validation

### Task 5.1: Tests

- [x] Run focused unit tests for projection, streaming, and threaded regressions
- [x] Run `make test`

### Task 5.2: Quality Checks

- [x] Run `make lint`
- [x] Verify no unchecked implementation tasks remain

### Builder Notes

- 2026-03-07: `pytest -n 0 tests/unit/test_output_projection.py tests/unit/test_transcript_converter.py tests/unit/test_threaded_output_updates.py tests/unit/test_polling_coordinator.py tests/unit/test_api_server.py -q` passed (`215 passed`).
- 2026-03-07: Hardened `read_phase_state()` to treat empty/non-mapping YAML as empty state after `test_next_work_concurrent_same_slug_single_flight_prep` exposed a concurrent prep read of `None`.
- 2026-03-07: Updated `tests/integration/test_multi_adapter_broadcasting.py` to use per-test `tmp_path` SQLite files after repeated/parallel `make test` runs hit stale `/tmp/*.db-wal`/`-shm` state.
- 2026-03-07: `make test` passed on current HEAD (`3252 passed, 5 skipped`).
- 2026-03-07: `telec todo demo validate conversation-projection-unification` passed on current HEAD.
- 2026-03-07: `make lint` cleared guardrails, markdown/resource validation, ruff, and pyright on current HEAD, then failed at repository-wide `pylint teleclaude` findings outside this todo's scope.

---

## Phase 6: Review Readiness

- [x] Confirm requirements are reflected in code changes
- [x] Confirm implementation tasks are all marked `[x]`
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable)
