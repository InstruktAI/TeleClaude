# Review Findings: Web Interface — Phase 1

## Round 2 Verdict: APPROVE

All Critical and Important findings from round 1 have been verified fixed. No new blocking issues found. Suggestions carried forward for follow-up.

---

## Round 1 Fix Verification

All 6 fixes applied in commit `e7809ac4` are confirmed correct:

| Finding                            | Status | Verification                                                                                              |
| ---------------------------------- | ------ | --------------------------------------------------------------------------------------------------------- |
| C1: Silent message discard         | FIXED  | `streaming.py:132-151` — checks `tmux_session_name`, checks `send_keys` return, logs + emits error status |
| I1: HTTPException in generator     | FIXED  | `streaming.py:246-248` — session validation in route handler before `StreamingResponse`                   |
| I2: TOCTOU race in live tail       | FIXED  | `streaming.py:204-207` — `f.seek()` + `f.read()` + `f.tell()` in same context manager                     |
| I3: `session: object` type erasure | FIXED  | `streaming.py:29,69,84,115` — imports and uses `Session` directly, direct attribute access                |
| I4: Untyped role field             | FIXED  | `streaming.py:50` — `role: Literal["user", "assistant", "system"]`                                        |
| I5: Mixed naming convention        | FIXED  | `streaming.py:59` — `session_id: str = Field(..., min_length=1, alias="sessionId")`                       |

---

## New Suggestions (Round 2)

### S6: Add top-level exception handler in SSE generator

**File:** `teleclaude/api/streaming.py:114-234`

The `_stream_sse` async generator has no top-level try-except. If an unhandled exception occurs during live tailing (e.g., `db.get_session` raises a transient DB error at line 187), the SSE stream terminates abruptly with no `message_finish` or `stream_done` events. The client receives a broken stream with no clean termination signal.

FastAPI handles this gracefully (no server crash), and clients can reconnect. However, wrapping the generator body in a try-except that emits error status + finish + done events before exiting would provide clean client-side recovery.

```python
async def _stream_sse(...) -> AsyncIterator[str]:
    message_id = f"msg-{session_id[:8]}"
    try:
        # ... existing body ...
    except Exception:
        logger.exception("Unhandled error in SSE stream for session %s", session_id)
        yield convert_session_status("error", session_id)
        yield message_finish(message_id)
        yield stream_done()
```

### S7: Gemini agent falls through to Claude JSONL parser

**File:** `teleclaude/api/streaming.py:101-106`

The comment says "Gemini uses JSON, not JSONL -- skip for live tailing" but the code applies the Claude JSONL parser to Gemini files. This is out of scope for Phase 1 (requirements don't mention Gemini) but should return an empty list with a debug log instead of applying an incompatible parser.

---

## Carryover Suggestions (from Round 1, unchanged)

- **S1**: Add logging to silent fallback paths (`streaming.py:78,91,100,217`)
- **S2**: Use `errors="replace"` instead of `errors="ignore"` for UTF-8 decode (`streaming.py:209`)
- **S3**: TCP server crash handler has no restart mechanism (`api_server.py`)
- **S4**: Duplicate transcript chain parsing logic (`api_server.py` vs `streaming.py`)
- **S5**: Test coverage gaps — converter well-tested (22 tests), streaming/helpers/people untested

---

## Review Gates Assessment

- [x] Code follows existing codebase patterns
- [x] No security vulnerabilities introduced
- [x] SSE wire protocol matches AI SDK v5 spec
- [x] Error handling is appropriate — all round 1 C/I issues resolved
- [x] No connection leaks in streaming — idle timeout and session close detection correct

---

## Positive Observations

1. The transcript converter is well-designed: stateless, clean dispatch, correct SSE format.
2. Converter tests are thorough (22 tests) — behavioral assertions, ID correlation, empty/missing field handling, no anti-patterns.
3. TCP server lifecycle mirrors the Unix socket pattern — proper startup guards, graceful shutdown with timeout.
4. PersonDTO correctly excludes sensitive fields (no credentials exposed).
5. The `# guard: loose-dict` convention for JSONL boundaries is pragmatic and consistent with the codebase.
6. All round 1 fixes are clean and minimal — no scope creep, each fix addresses exactly the reported issue.
7. Message ingestion properly validates tmux presence and delivery success with user-visible error feedback.
