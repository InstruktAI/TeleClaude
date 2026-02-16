# Implementation Plan: Web Interface — Phase 1: Daemon SSE Plumbing

## Objective

Add daemon-side SSE infrastructure for the web interface.

## [x] Task 1: TCP port binding

**File:** `teleclaude/api_server.py`

Add `localhost:8420` TCP binding alongside Unix socket in `APIServer.start()`.

**Verification:** `curl http://localhost:8420/health` returns OK.

## [x] Task 2: SSE streaming endpoint

**File:** `teleclaude/api/streaming.py` (new)

- `POST /api/chat/stream` route.
- Parse request: `sessionId`, optional `since_timestamp`, optional `messages`.
- Auth check via middleware (identity context required).
- Session access check (person + role + visibility).
- Return `StreamingResponse` with correct headers.
- History replay mode: read JSONL transcript, convert to SSE.
- Live streaming mode: subscribe to output poller events, convert to SSE.

**Verification:** SSE events received via curl.

## [x] Task 3: Transcript-to-SSE converter

**File:** `teleclaude/api/transcript_converter.py` (new)

Mapping functions for each JSONL entry type → SSE events.
Stateless converter — takes JSONL entry, yields SSE event strings.

**Verification:** Unit tests with sample JSONL entries.

## [x] Task 4: People list endpoint

**File:** `teleclaude/api_server.py`

`GET /api/people` — reads from global config, returns `[{name, email, role}]`.

**Verification:** Returns correct list.

## [x] Task 5: Message ingestion

Part of SSE endpoint — when `messages` present, extract user text, call `send_keys`.

**Verification:** Message reaches tmux session.

## Files Changed

| File                                      | Change                       |
| ----------------------------------------- | ---------------------------- |
| `teleclaude/api_server.py`                | TCP binding, people endpoint |
| `teleclaude/api/streaming.py`             | New — SSE endpoint           |
| `teleclaude/api/transcript_converter.py`  | New — JSONL → SSE            |
| `tests/unit/test_transcript_converter.py` | New — converter tests        |

## Risks

1. AI SDK wire protocol must match v5 spec exactly.
2. Live streaming subscription must not leak connections.

## Verification

- All tests pass.
- SSE endpoint works end-to-end with transcript replay and live streaming.
