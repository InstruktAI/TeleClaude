# Review Findings: Web Interface — Phase 1

## Verdict: REQUEST CHANGES

Findings: 11 (1 Critical, 5 Important, 5 Suggestions)

---

## Critical

### C1: Silent message discard when tmux_session_name is missing

**File:** `teleclaude/api/streaming.py:136-146`

When a user sends a message via the web interface, if the session has no `tmux_session_name`, the message is silently discarded. The SSE stream starts, emits a "streaming" status, but the message was never delivered. The user waits for a response that will never come. Additionally, the `send_keys_existing_tmux` return value (`bool`) is ignored — delivery failures are invisible.

**Fix:** Check `tmux_session_name` presence and `send_keys` return value. Surface failure via SSE status event or log warning.

---

## Important

### I1: HTTPException inside async generator won't propagate as HTTP 404

**File:** `teleclaude/api/streaming.py:124-126`

`HTTPException` is raised inside `_stream_sse` (an async generator). FastAPI wraps the generator in `StreamingResponse` before iteration starts. If the exception fires, `StreamingResponse` may have already sent headers, resulting in a broken stream instead of a proper 404. Validation must happen in the route handler before creating the response.

**Fix:** Move session lookup into `chat_stream()` route handler and pass the validated session to the generator.

### I2: TOCTOU race in live tail file reading

**File:** `teleclaude/api/streaming.py:191-202`

File size is checked via `os.path.getsize()` then `f.seek(file_size)` + `f.read(current_size - file_size)` in a separate operation. If the file grows between the check and the read, partial JSONL lines or partial UTF-8 sequences may be captured.

**Fix:** Read to EOF inside the file context manager and track position via `f.tell()`:

```python
with open(live_file, "rb") as f:
    f.seek(file_size)
    new_bytes = f.read()
    file_size = f.tell()
```

### I3: `session: object` with `getattr` erases known type

**File:** `teleclaude/api/streaming.py:68, 85`

Both `_get_transcript_chain` and `_get_agent_name` accept `session: object` and use `getattr` for every field access. `db.get_session()` returns `Session | None`. After the null check at line 125, the value is `Session`. Using `object` erases this, violates the project's typing policy, and prevents static analysis from catching errors.

**Fix:** Import and use `Session` directly, or define a `Protocol` if decoupling is a goal.

### I4: `ChatStreamMessage.role` is untyped `str` for a closed domain

**File:** `teleclaude/api/streaming.py:49`

`role: str` accepts any arbitrary string. The same codebase uses `Literal["user", "assistant", "system"]` for `MessageDTO.role` in `api_models.py:390`. The filtering logic at line 245 (`if msg.role == "user"`) proves the domain is finite.

**Fix:** `role: Literal["user", "assistant", "system"]`

### I5: Mixed naming convention in `ChatStreamRequest`

**File:** `teleclaude/api/streaming.py:53-60`

`sessionId` (camelCase) coexists with `since_timestamp` (snake_case) in the same model. Use Pydantic field aliases for wire compatibility while keeping Python-side naming consistent:

```python
session_id: str = Field(..., min_length=1, alias="sessionId")
```

---

## Suggestions

### S1: Add logging to silent fallback paths

**Files:** `streaming.py:73-78, 85-91, 99-101, 209-212`

Several fallback paths produce correct degradation but leave no trace in logs:

- Corrupt `transcript_files` JSON returns empty chain (line 78)
- Unknown agent name falls back to Claude (line 91)
- Missing transcript file returns empty list (line 101)
- Malformed JSONL lines in live tail silently skipped (line 212)

Add `logger.warning` or `logger.debug` to each catch/fallback path.

### S2: Use `errors="replace"` instead of `errors="ignore"` for UTF-8 decode

**File:** `teleclaude/api/streaming.py:204`

`errors="ignore"` silently drops non-UTF-8 bytes. `errors="replace"` inserts the Unicode replacement character, making encoding issues visible rather than silently losing data.

### S3: TCP server crash handler has no restart mechanism

**File:** `teleclaude/api_server.py:1600-1617`

When the TCP server crashes at runtime, the error is logged but no restart is attempted. The Unix socket server has lifecycle callbacks; the TCP server does not. Consider adding a restart with backoff for resilience.

### S4: Duplicate transcript chain parsing logic

**File:** `teleclaude/api_server.py:681-687` vs `teleclaude/api/streaming.py:68-82`

The transcript chain building logic (JSON parse of `transcript_files`, dedup of `native_log_file`) is duplicated between the `get_session_messages` endpoint and the `_get_transcript_chain` helper. Both have the same silent catch. Consolidate into the shared helper.

### S5: Test coverage gaps

Only 1 of 5 requirements has unit tests (the transcript converter — 22 tests, well-written). The SSE streaming endpoint, message ingestion, people endpoint, and helper functions have zero automated tests. The converter tests are thorough and follow good patterns. Missing tests for the streaming generator and message ingestion are the most impactful gaps.

---

## Review Gates Assessment

- [x] Code follows existing codebase patterns — overall yes, with noted type and naming deviations
- [ ] No security vulnerabilities introduced — C1 (silent message discard is a UX/reliability issue)
- [x] SSE wire protocol matches AI SDK v5 spec — converter output format is correct
- [ ] Error handling is appropriate — C1 (silent discard), I1 (exception in generator)
- [x] No connection leaks in streaming — idle timeout and session close detection are correct

---

## Positive Observations

1. The transcript converter is well-designed: stateless, clean dispatch, correct SSE format.
2. Converter tests are thorough — behavioral assertions, ID correlation, empty/missing field handling.
3. TCP server lifecycle mirrors the Unix socket pattern — proper startup guards, graceful shutdown with timeout.
4. PersonDTO correctly excludes sensitive fields (no credentials exposed).
5. The `# guard: loose-dict` convention for JSONL boundaries is pragmatic and consistent with the codebase.

---

## Fixes Applied

All Critical and Important issues have been addressed in commit `e7809ac4`.

### C1: Silent message discard when tmux_session_name is missing

**Fixed:** Added validation for `tmux_session_name` presence and `send_keys` return value. Failures now log warnings and emit SSE error status events. Users receive immediate feedback when message delivery fails.

### I1: HTTPException inside async generator won't propagate as HTTP 404

**Fixed:** Moved session validation from `_stream_sse` generator to `chat_stream` route handler. Session existence is verified before `StreamingResponse` is created, ensuring proper HTTP 404 responses.

### I2: TOCTOU race in live tail file reading

**Fixed:** Replaced size calculation with `f.tell()` to track file position atomically within the file read context. Eliminates race condition between size check and read operation.

### I3: `session: object` with `getattr` erases known type

**Fixed:** Imported `Session` from `teleclaude.core.db_models` and replaced `object` type annotation with `Session`. All `getattr` calls replaced with direct attribute access, enabling static type checking.

### I4: `ChatStreamMessage.role` is untyped `str` for a closed domain

**Fixed:** Changed `role: str` to `role: Literal["user", "assistant", "system"]`, matching the type used in `MessageDTO` and reflecting the finite domain of valid roles.

### I5: Mixed naming convention in `ChatStreamRequest`

**Fixed:** Used Pydantic `Field` with `alias="sessionId"` to maintain wire compatibility while using Python snake_case convention internally (`session_id`).

**Tests:** All 1756 unit tests pass. Pre-commit hooks (format, lint) pass.
**Ready for re-review.**
