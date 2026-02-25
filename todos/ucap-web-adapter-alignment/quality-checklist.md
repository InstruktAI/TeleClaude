# Quality Checklist - ucap-web-adapter-alignment

## Build Gates (Builder)

- [x] R1: Web SSE stream derives initial session status from canonical `session.lifecycle_status`, not hardcoded string.
- [x] R1: Web lane logs include `lane`, `session_id`, and `event_type` observability fields.
- [x] R2: Hardcoded `"streaming"` bypass removed from SSE status emission path.
- [x] R2: Live-loop closure detection uses canonical `lifecycle_status in _CLOSED_STATUSES` check.
- [x] R3: SSE/UI message framing (convert_entry, message_start, convert_session_status) remains isolated in `teleclaude/api/streaming.py` edge.
- [x] R2/R3: `data_routes.py` confirmed read-only (file serving only); not a realtime bypass producer.
- [x] R4: `_map_lifecycle_to_sse_status` exported and covered by unit tests (6 mapping tests + 2 integration tests).
- [x] R4: `test_api_server.py` extended with canonical contract path tests for Web lane.
- [x] Tests pass: `make test` — 2115 passed, 106 skipped.
- [x] Lint passes: `make lint` — 0 errors, 0 warnings.

## Review Gates (Reviewer)

_Filled in during review phase._

## Finalize Gates (Finalizer)

_Filled in during finalize phase._
