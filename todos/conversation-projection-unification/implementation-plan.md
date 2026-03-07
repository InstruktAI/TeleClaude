# Implementation Plan: conversation-projection-unification

## Overview

Implement one transcript normalization + assembly path that produces the narrow public stream in [schema.md](./schema.md), then move every transcript-derived consumer onto it.

This plan has three layers:

1. internal normalization
2. public assembly
3. consumer serializers/renderers

The internal normalization layer may keep enough detail to normalize all agent formats correctly.
The public layer must stay narrow.

## Phase 1: Normalization And Assembly Core

### Task 1.1: Add the unified transcript entry point

**File(s):**

- `teleclaude/utils/transcript.py`
- `teleclaude/output_stream/` or equivalent new package

- [ ] Add one canonical function/module that is the only semantic entry point for transcript-derived output.
- [ ] Make all transcript-derived callers consume that entry point instead of raw transcript files.
- [ ] Keep any helper normalization internal to that entry point.
- [ ] Preserve enough internal detail inside that entry point to normalize:
  - Claude user-role tool results
  - Codex standalone `reasoning` / `function_call` / `function_call_output` / `custom_tool_call`
  - Gemini `thoughts[]` / `toolCalls[]`

### Task 1.2: Add public assembly models

**File(s):**

- `teleclaude/api_models.py`
- `frontend/lib/api/types.ts`

- [ ] Add DTO/type models for the narrow public stream:
  - `UnifiedEventStream`
  - `UnifiedMessage`
  - `UnifiedPart`
- [ ] Remove `type + text` as the architecture-owner representation for transcript-derived web history.
- [ ] Keep `call_id` stable in both backend and frontend types.

### Task 1.3: Add assembly-time sanitization

**File(s):**

- `teleclaude/utils/transcript.py`
- `teleclaude/constants.py`

- [ ] Add a dedicated user-input sanitization step before public assembly.
- [ ] Strip user text that starts with `TELECLAUDE_SYSTEM_PREFIX`.
- [ ] Strip user wrapper payloads:
  - `<task-notification> ... </task-notification>`
  - pure `<system-reminder> ... </system-reminder>`
- [ ] Drop user messages that become empty after sanitization.
- [ ] Add a rich module-level docstring explaining:
  - included parts
  - stripped input rules
  - intentionally dropped fields/data

## Phase 2: Agent-Specific Mapping

### Task 2.1: Claude assembly

**File(s):**

- `teleclaude/utils/transcript.py`

- [ ] Assemble Claude user string content as user `text`.
- [ ] Assemble Claude assistant `text`, `thinking`, and `tool_use`.
- [ ] Assemble Claude user-role `tool_result`-only messages as assistant `tool_result`.
- [ ] Ensure TeleClaude-prefixed injected user content is stripped before assembly.
- [ ] Do not emit compaction/system entries into the public stream.

### Task 2.2: Codex assembly

**File(s):**

- `teleclaude/utils/transcript.py`

- [ ] Assemble `response_item.payload.type == "message"` user `input_text` and assistant `output_text`.
- [ ] Assemble `payload.type == "reasoning"` as assistant `thinking`.
- [ ] Assemble `payload.type == "function_call"` as assistant `tool_call`.
- [ ] Assemble `payload.type == "function_call_output"` as assistant `tool_result`.
- [ ] Assemble `payload.type == "custom_tool_call"` as assistant `tool_call` plus `tool_result` when output/error exists.
- [ ] Ensure TeleClaude-prefixed injected user content is stripped before assembly.

### Task 2.3: Gemini assembly

**File(s):**

- `teleclaude/utils/transcript.py`

- [ ] Assemble Gemini user `content` as user `text`.
- [ ] Assemble Gemini assistant `content` as assistant `text`.
- [ ] Assemble each `thoughts[]` item as assistant `thinking`.
- [ ] Assemble each `toolCalls[]` item as assistant `tool_call`.
- [ ] Assemble each nested tool result item as assistant `tool_result`.
- [ ] Ensure multiple Gemini tool results are not collapsed into one display string.

## Phase 3: Consumer Cutover

### Task 3.1: Session history API

**File(s):**

- `teleclaude/api_server.py`
- `teleclaude/api_models.py`
- `frontend/app/api/sessions/[id]/messages/route.ts`
- `frontend/lib/api/client.ts`
- `frontend/lib/api/types.ts`

- [ ] Replace `MessageDTO`/`SessionMessagesDTO` history output with the unified assembled stream DTOs.
- [ ] Stop exposing history as flattened `role/type/text` rows.
- [ ] Keep endpoint path stable if possible; change payload shape to the new contract.

### Task 3.2: Live web stream

**File(s):**

- `teleclaude/api/streaming.py`
- `teleclaude/api/transcript_converter.py`
- `frontend/app/api/chat/route.ts`

- [ ] Stop calling `convert_entry(entry)` on raw transcript entries.
- [ ] Serialize live events from assembled messages/parts.
- [ ] Keep transport framing stable, but make the payload semantics come from assembly.
- [ ] Ensure the live stream applies the same input-sanitization/assembly rules as history.

### Task 3.3: Frontend history loader

**File(s):**

- `frontend/components/assistant/MyRuntimeProvider.tsx`
- `frontend/lib/api/types.ts`

- [ ] Replace the current `toUIMessages()` logic that only understands `text` and `thinking`.
- [ ] Map assembled `tool_call` and `tool_result` parts into assistant-ui message parts.
- [ ] Remove client-side assumptions that history is a flattened row list.

### Task 3.4: Frontend thread rendering

**File(s):**

- `frontend/components/assistant/ThreadView.tsx`

- [ ] Verify the thread renderer consumes the unified part set from both history and live.
- [ ] Keep client-side presentation choices in the frontend, not in the parser.
- [ ] Ensure tool calls and thinking remain visible to the web client.

### Task 3.5: Threaded transcript output consumer

**File(s):**

- `teleclaude/core/agent_coordinator.py`
- `teleclaude/utils/transcript.py`
- `teleclaude/core/adapter_client.py`

- [ ] Replace threaded transcript rendering’s custom raw-transcript interpretation with rendering from the assembled stream.
- [ ] Preserve current delivery mechanics.
- [ ] Keep formatting decisions in the threaded consumer layer.

### Task 3.6: Transcript-backed search/mirror consumers

**File(s):**

- `teleclaude/utils/transcript.py`
- `teleclaude/history/`
- `teleclaude/history/search.py`
- summarizer/transcript-text consumers using `collect_transcript_messages()`
- `todos/history-search-upgrade/`

- [ ] Identify every transcript-backed search/mirror extractor that still uses raw/lossy parsing.
- [ ] Move them to the same shared assembly path used by web history/live.
- [ ] Keep any extra internal-only transcript heuristics out of this caller contract and out of the public stream.

### Task 3.7: Internal transcript helper cutover

**File(s):**

- `teleclaude/utils/transcript.py`
- `teleclaude/api/transcript_converter.py`
- `teleclaude/hooks/checkpoint.py`

- [ ] Convert the current transcript helper entry points into wrappers over the unified entry point or remove them.
- [ ] Explicitly eliminate independent semantic transcript parsing from:
  - `extract_structured_messages()`
  - `extract_messages_from_chain()`
  - `collect_transcript_messages()`
  - `extract_tool_calls_current_turn()`
  - `render_agent_output()`
  - `render_clean_agent_output()`
  - `convert_entry()`
- [ ] Confirm no transcript-derived caller keeps its own under-the-hood path to raw source files.

## Phase 4: Documentation

### Task 4.1: Code-level contract doc

**File(s):**

- assembly/parser module chosen in implementation

- [ ] Add a rich module-level documentation block that explains:
  - what is assembled
  - what is stripped
  - what is dropped
  - why the public stream is intentionally narrower than internal normalization

### Task 4.2: Architecture docs

**File(s):**

- `docs/project/spec/messaging.md`
- `docs/project/design/architecture/web-interface.md`
- `docs/project/design/architecture/checkpoint-system.md`
- `docs/project/design/architecture/unified-event-stream.md` (new, recommended)

- [ ] Add/update architecture docs so they match the code contract.
- [ ] Document the TeleClaude input-stripping rules explicitly.
- [ ] Document the drop list explicitly.
- [ ] Document the affected consumers and their relationship to the assembled stream.

## Phase 5: Verification

### Task 5.1: Backend tests

**File(s):**

- `tests/unit/test_structured_messages.py`
- `tests/unit/test_transcript.py`
- `tests/unit/test_transcript_converter.py`
- `tests/unit/test_api_server.py`
- new assembly tests

- [ ] Add tests for public assembly shape.
- [ ] Add tests for TeleClaude-prefix stripping.
- [ ] Add tests for wrapper stripping:
  - `<task-notification>`
  - `<system-reminder>`
- [ ] Add tests for Claude user-role tool-result correction.
- [ ] Add tests for Codex standalone tool payload assembly.
- [ ] Add tests for Gemini nested thought/tool assembly.
- [ ] Add history/live parity tests from the same transcript source.

### Task 5.2: Frontend tests

**File(s):**

- frontend test files covering `MyRuntimeProvider` / thread rendering

- [ ] Add tests proving history and live consume the same part model.
- [ ] Add tests proving tool calls/results and thinking render from history as well as live.

### Task 5.3: Non-regression checks

- [ ] Run targeted parser/stream/history/threaded tests
- [ ] Run `make test`
- [ ] Run `make lint`
