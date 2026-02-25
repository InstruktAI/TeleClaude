# Review Findings: ucap-truthful-session-status

**Reviewer:** Claude (automated)
**Review round:** 2
**Baseline commit:** 3162c65f
**Verdict:** APPROVE

---

## Round 1 Fix Verification

All 7 findings from round 1 have been verified as correctly resolved:

| Finding                                 | Fix                                                                                        | Commit   | Verified |
| --------------------------------------- | ------------------------------------------------------------------------------------------ | -------- | -------- |
| C1. Stall task leak on session close    | `_cancel_stall_task` in `daemon.py:_handle_session_closed` before `terminate_session`      | 545f5ecf | Yes      |
| C2. Stall task leak on agent error      | `_cancel_stall_task` + `_emit_status_event("error")` in AGENT_ERROR branch                 | 39719a52 | Yes      |
| C3. `status_message_id` deserialization | `raw_status_msg` read and passed to `DiscordAdapterMetadata` constructor                   | cb2cc0a0 | Yes      |
| I1. Closed bypasses contract validation | `serialize_status_event()` gate before DTO construction; `datetime` import at module level | c6179953 | Yes      |
| I2. No adapter tests                    | 4 Discord tests (send/edit/fallback/skip) + 2 Telegram tests (footer/skip)                 | 824bde68 | Yes      |
| I3. No coordinator tests                | 5 tests: accepted, active_output+cancel, completed+cancel, stall transitions, cancellation | 2e01e2f3 | Yes      |
| I4. Stall watcher exception handling    | Broad `except Exception` with `logger.error` inside `_stall_watcher`                       | c4379ac0 | Yes      |

---

## Round 2 New Findings

### None Critical

### None Important

---

## Suggestions

### S1. Closed status DTO omits routing metadata

**File:** `teleclaude/api_server.py:280-286`

`_handle_session_closed_event` constructs the DTO without `message_intent`/`delivery_scope`, while `_handle_session_status_event` passes them from the `SessionStatusContext`. The `canonical` result from `serialize_status_event()` carries these fields but they're not forwarded to the DTO. Minor inconsistency — `closed` is terminal and unlikely to affect routing decisions in practice.

### S2. `next()` without default in test assertions (carried from round 1)

**File:** `tests/unit/test_agent_activity_events.py:217,258,292,372`

Four `next(c[0][1] for c in ... if ...)` calls without a default. `StopIteration` instead of descriptive assertion failure on mismatch. Low risk since tests pass.

### S3. Inconsistent assertion style in `test_handle_tool_done` (carried from round 1)

**File:** `tests/unit/test_agent_activity_events.py:139`

Uses `assert_called_once()` while sibling tests filter by event type. Correct but fragile if `tool_done` later emits status events.

---

## Paradigm-Fit Assessment

1. **Data flow:** Core-owned status transitions route through `status_contract.serialize_status_event()` for validation, emit via `event_bus`, and fan out to adapters. The close/error paths now properly cancel stall tasks and emit canonical status events (C1/C2 fixes). The closed status in `api_server` uses contract validation as a gate. **Pass.**

2. **Component reuse:** `_format_lifecycle_status` defined once in `UiAdapter` base, inherited by Discord/Telegram. `_handle_session_status` is a no-op base with per-adapter overrides. No copy-paste duplication. **Pass.**

3. **Pattern consistency:** `SessionStatusContext` follows frozen-dataclass event context pattern. DTO follows existing Pydantic model pattern. Stall watcher follows async task pattern with proper exception handling (I4 fix). Event subscription follows `event_bus.subscribe` pattern. **Pass.**

---

## Requirements Traceability

| Req                                    | Status | Evidence                                                                                                       |
| -------------------------------------- | ------ | -------------------------------------------------------------------------------------------------------------- |
| R1. Core-owned status truth            | Pass   | Core computes all status transitions; close/error paths now use coordinator (C1/C2 fixes)                      |
| R2. Canonical status contract          | Pass   | `status_contract.py` defines vocabulary, validation, required fields; all paths validated                      |
| R3. Capability-aware adapter rendering | Pass   | Discord send/edit/fallback, Telegram footer, WS broadcast; tested (I2 fix); deserialization fixed (C3)         |
| R4. Truthful inactivity behavior       | Pass   | Stall detection transitions tested (I3); tasks cancelled on close/error (C1/C2); exception handling added (I4) |
| R5. Observability and validation       | Pass   | Contract tests (test_status_contract.py), adapter tests, coordinator tests; debug logging at transitions       |

---

## Summary

All 3 critical and 4 important findings from round 1 have been correctly resolved with minimal, targeted fixes. Each fix has a dedicated commit with clear intent. The test suite passes (2107 passed, 106 skipped) and lint is clean.

The implementation now satisfies all five requirements:

- Core is the single source of truth for lifecycle status semantics (R1)
- Canonical contract validates all outbound status events (R2)
- Adapters render truthfully from the canonical stream with tests covering key paths (R3)
- Stall detection transitions correctly and cleans up on session close/error (R4)
- Contract, adapter, and coordinator tests cover vocabulary, transitions, and rendering behavior (R5)

Three suggestions remain (routing metadata gap in closed DTO, `next()` without default in tests, assertion style inconsistency). None block approval.

**Tests:** 2107 passed, 106 skipped
**Lint:** PASSING
