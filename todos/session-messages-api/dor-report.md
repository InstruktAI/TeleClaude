# DOR Report: session-messages-api

## Draft Assessment

### Gate 1: Intent & Success — PASS

- Problem statement is explicit: single `native_log_file` field loses history on rotation; markdown-only output blocks structured frontend rendering.
- Success criteria are concrete and testable (7 checkboxes in requirements.md).
- "What" and "why" are clear: structured messages endpoint for web frontend consumption.

### Gate 2: Scope & Size — PASS

- 4 implementation tasks, ~7 files changed. Fits a single AI session.
- No cross-cutting changes — additive column, additive endpoint, new extraction functions.
- Not split into phases; the work is atomic.

### Gate 3: Verification — PASS

- Each task has a verification step (unit test or integration test).
- Edge cases identified: missing files (empty array with warning), large JSONL (mitigated by `since` filter).
- Error paths: missing session → 404, missing transcript files → empty messages with warning.

### Gate 4: Approach Known — PASS

- Uses existing `_iter_*_entries()` and `_get_entries_for_agent()` from `transcript.py`.
- Migration follows established pattern (async up/down with PRAGMA guard, matching `010_add_session_listeners.py`).
- API endpoint follows existing `/sessions/{session_id}/*` route structure in `api_server.py`.
- Hook receiver modification is a small delta to `_update_session_native_fields()`.

### Gate 5: Research Complete — AUTO-PASS

- No third-party dependencies introduced. Pure internal plumbing.

### Gate 6: Dependencies & Preconditions — PASS

- No prerequisites. This todo IS the prerequisite for `web-interface-1`.
- All required infrastructure exists: iterators, DB models, API server, migration framework.

### Gate 7: Integration Safety — PASS

- All changes are additive: new column (default `"[]"`), new functions, new endpoint.
- `native_log_file` continues to hold the latest path — backward compatible.
- Existing `get_session_data` and checkpoint logic are untouched.

### Gate 8: Tooling Impact — AUTO-PASS

- No tooling or scaffolding changes.

## Codebase Verification

Confirmed against codebase (2026-02-15):

| Plan Reference                                                              | Codebase Reality                                              | Status    |
| --------------------------------------------------------------------------- | ------------------------------------------------------------- | --------- |
| `_iter_claude_entries()`, `_iter_codex_entries()`, `_iter_gemini_entries()` | All exist in `transcript.py` (lines 704-853)                  | Confirmed |
| `_get_entries_for_agent()`                                                  | Exists at line 1166, returns `Optional[list[dict]]`           | Confirmed |
| `_update_session_native_fields()`                                           | Exists in `receiver.py` (line 286), uses synchronous SQLModel | Confirmed |
| `native_log_file` field in Session model                                    | Exists in `db_models.py` (line 40)                            | Confirmed |
| No `transcript_files` field yet                                             | Confirmed — field does not exist                              | Confirmed |
| Migration pattern (async up/down, PRAGMA guard)                             | Matches `010_add_session_listeners.py`                        | Confirmed |
| API route pattern `/sessions/{session_id}/*`                                | All session endpoints follow this                             | Confirmed |

## Assumptions

1. Claude Code `--resume` within the same tmux session produces a new `native_log_file` value in hooks. If not, the chain is a single-element no-op (harmless).
2. Gemini transcript iterator loads the full JSON file (no tail support). For the messages endpoint this is acceptable since full parsing is the goal.
3. The `since` filter compares against entry timestamps. Claude JSONL entries have `timestamp` fields; Codex and Gemini entries need timestamp extraction verified during implementation.

## Open Questions

None blocking. All assumptions are low-risk with safe fallbacks.
