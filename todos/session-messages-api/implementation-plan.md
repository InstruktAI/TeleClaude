# Implementation Plan: Session Messages API

## Overview

Add a structured messages API backed by native session transcript files. Two changes: (1) accumulate transcript file paths instead of replacing, (2) new endpoint that extracts structured messages from the file chain. Builds on existing `_iter_*_entries()` parsers in `transcript.py`.

## Task 1: Transcript file chain storage

**File(s):** `teleclaude/core/db_models.py`, `teleclaude/core/schema.sql`, `teleclaude/hooks/receiver.py`

- [x] Add `transcript_files` column to sessions table (TEXT, JSON array of file paths, default `"[]"`).
- [x] Add migration to add column to existing databases.
- [x] In `_update_session_native_fields`: when `native_log_file` changes and the previous value is non-empty, append old path to `transcript_files` before replacing `native_log_file`.
- [x] `native_log_file` continues to hold the latest path (backward compat).

**Verification:** Unit test: simulate two successive `native_log_file` updates, verify chain contains both paths.

## Task 2: Structured message extraction

**File(s):** `teleclaude/utils/transcript.py`

- [x] New function `extract_structured_messages(transcript_path, agent_name, *, since, include_tools, include_thinking)` → `list[dict]`.
- [x] Uses existing `_iter_*_entries()` + `_get_entries_for_agent()`.
- [x] Each message dict: `role`, `type`, `text`, `timestamp`, `entry_index`.
- [x] Classify Claude `system` entries with `parentUuid` (after first) as `type: "compaction"`.
- [x] Respect `since` timestamp filter.
- [x] Filter tool/thinking entries based on flags.

**Verification:** Unit test with sample JSONL fixture containing user, assistant, system (compaction), and tool entries.

## Task 3: Multi-file stitching

**File(s):** `teleclaude/utils/transcript.py`

- [x] New function `extract_messages_from_chain(file_paths, agent_name, **kwargs)` that calls `extract_structured_messages` for each file, adds `file_index`, and concatenates results.
- [x] Files are read in order (oldest first — chain order).

**Verification:** Unit test with two JSONL fixtures simulating a file rotation, verify messages stitch correctly.

## Task 4: Messages API endpoint

**File(s):** `teleclaude/api_server.py`

- [x] `GET /sessions/{session_id}/messages` route.
- [x] Query params: `since` (optional ISO 8601), `include_tools` (bool), `include_thinking` (bool).
- [x] Reads session from DB, builds file chain (`transcript_files` + `native_log_file`).
- [x] Calls `extract_messages_from_chain`.
- [x] Returns JSON response with `session_id`, `agent`, `messages` array.
- [x] Handles missing session (404), missing files (empty messages array with warning).

**Verification:** Integration test: create session with known transcript, hit endpoint, verify JSON structure.

---

## Validation

- [x] Add or update tests for the changed behavior.
- [x] Run `make test`.
- [x] Run `make lint`.
- [x] Verify existing `get_session_data` still works (no regression).
- [ ] Manual verification: hit `/sessions/{id}/messages` for an active session, confirm structured output.

---

## Files Changed

| File                                                     | Change                                                       |
| -------------------------------------------------------- | ------------------------------------------------------------ |
| `teleclaude/core/db_models.py`                           | Add `transcript_files` field                                 |
| `teleclaude/core/schema.sql`                             | Add column                                                   |
| `teleclaude/core/migrations/011_add_transcript_files.py` | New migration                                                |
| `teleclaude/hooks/receiver.py`                           | Chain accumulation in `_update_session_native_fields`        |
| `teleclaude/utils/transcript.py`                         | `extract_structured_messages`, `extract_messages_from_chain` |
| `teleclaude/api_server.py`                               | New messages endpoint                                        |
| `tests/unit/test_structured_messages.py`                 | New — message extraction tests                               |

## Risks

1. Large JSONL files could be slow to parse fully. Mitigated by `since` filter and lazy iteration.
2. Transcript file chain has no production data yet (file rotation not observed). Chain logic is safe as single-element no-op.
