# Implementation Plan - ucap-web-adapter-alignment

## Objective

Migrate Web realtime behavior onto canonical adapter output without changing unrelated client lanes.

## Preconditions

- `ucap-truthful-session-status` has completed and canonical status/output surfaces are available.
- Web streaming/runtime surfaces can be exercised via existing unit/integration test harnesses.
- No new third-party SDK adoption is required for this todo; existing AI SDK stream integration is reused.

## Requirement Traceability

- `R1` -> Phase 1
- `R2` -> Phase 2
- `R3` -> Phase 2
- `R4` -> Phase 3

## Phase 1 - Wire Web Lane to Canonical Contract

- [x] [R1] Route Web lane output subscription through canonical contract serializer path.
- [x] [R1] Verify required metadata fields are present for Web consumers.

### Files (expected)

- `teleclaude/api_server.py`
- `teleclaude/api/*`
- `teleclaude/adapters/*`

## Phase 2 - Remove Web Bypass and Preserve Edge Translation

- [x] [R2] Remove direct Web bypass path for core output progression.
- [x] [R3] Keep SSE/UI message framing isolated at Web adapter edge.
- [x] [R2, R3] Confirm snapshot/history endpoints remain read-only helpers, not realtime bypass producers.

### Files (expected)

- `teleclaude/api_server.py`
- Web streaming modules under `teleclaude/api/*` or `teleclaude/adapters/*`

## Phase 3 - Web Validation and Observability

- [x] [R4] Add tests for canonical contract path in Web lane.
- [x] [R4] Add/verify Web lane observability fields (lane, event type, session).

### Files (expected)

- `tests/unit/test_api_server.py`
- `tests/integration/*web*`

## Verification Commands (draft)

- `pytest -q tests/unit/test_api_server.py tests/unit/test_threaded_output_updates.py`
- `instrukt-ai-logs teleclaude --since 5m --grep "web|send_output_update|OUTPUT_ROUTE"`

## Definition of Done

- [x] Web lane uses canonical outbound contract.
- [x] Web bypass path is removed for core output progression.
- [x] Web edge translation boundaries remain intact.

## Research References

- `docs/third-party/ai-sdk/ui-message-stream-status-parts.md`
