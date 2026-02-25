# Review Findings: ucap-truthful-session-status

**Reviewer:** Claude Opus 4.6 (independent review)
**Review round:** 3
**Baseline commit:** 5a5aa1e7
**Verdict:** APPROVE

---

## Round 1 Fix Verification (confirmed in round 2, re-verified round 3)

All 7 findings from round 1 are correctly resolved. Each fix is present in the codebase with a dedicated commit.

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

## Round 3 New Findings

### None Critical

### None Important

---

## Suggestions (carried forward)

### S1. Closed status DTO omits routing metadata

**File:** `teleclaude/api_server.py:280-286`

`_handle_session_closed_event` constructs the DTO without `message_intent`/`delivery_scope`, while `_handle_session_status_event` passes them from the `SessionStatusContext`. The `canonical` result from `serialize_status_event()` carries these fields but they're not forwarded to the DTO. Minor inconsistency — `closed` is terminal and unlikely to affect routing decisions in practice.

### S2. `next()` without default in test assertions

**File:** `tests/unit/test_agent_activity_events.py:217,258,292,372`

Four `next(c[0][1] for c in ... if ...)` calls without a default. `StopIteration` instead of descriptive assertion failure on mismatch. Low risk since tests pass.

### S3. Inconsistent assertion style in `test_handle_tool_done`

**File:** `tests/unit/test_agent_activity_events.py:139`

Uses `assert_called_once()` while sibling tests filter by event type. Correct but fragile if `tool_done` later emits status events.

### S4. Implementation plan task checkboxes remain unchecked

**File:** `todos/ucap-truthful-session-status/implementation-plan.md`

All Phase 1-4 task items show `[ ]` despite the code being fully implemented and the quality checklist confirming completion. Clerical inconsistency only — the implementation is verified present.

---

## Paradigm-Fit Assessment

1. **Data flow:** Core-owned status transitions route through `status_contract.serialize_status_event()` for validation, emit via `event_bus`, and fan out to adapters via subscription. Close/error paths cancel stall tasks and emit canonical status events. The closed status in `api_server` uses contract validation as a gate. No adapter invents status independently. **Pass.**

2. **Component reuse:** `_format_lifecycle_status` defined once as a `@staticmethod` on `UiAdapter` base, reused by Discord and Telegram. `_handle_session_status` is a no-op base with per-adapter overrides. `_emit_status_event` in coordinator parallels the existing `_emit_activity_event` pattern. No copy-paste duplication found. **Pass.**

3. **Pattern consistency:** `SessionStatusContext` follows the frozen-dataclass event context pattern used by all other event contexts. `SessionLifecycleStatusEventDTO` follows the existing Pydantic DTO pattern. Stall watcher uses `asyncio.Task` with cancellation — consistent with `_background_tasks` pattern. Event subscription follows `event_bus.subscribe` pattern. `_stall_tasks` dict follows the same lifecycle tracking pattern as `_background_tasks`. **Pass.**

---

## Requirements Traceability

| Req                                    | Status | Evidence                                                                                                                |
| -------------------------------------- | ------ | ----------------------------------------------------------------------------------------------------------------------- |
| R1. Core-owned status truth            | Pass   | `agent_coordinator._emit_status_event` is the sole producer; close/error paths in `daemon.py` use coordinator methods   |
| R2. Canonical status contract          | Pass   | `status_contract.py` defines vocabulary, validation, `CanonicalStatusEvent`, timing thresholds; all paths validated     |
| R3. Capability-aware adapter rendering | Pass   | Discord: send/edit/fallback status message; Telegram: footer line; WS: broadcast DTO; TUI: notification for stall/error |
| R4. Truthful inactivity behavior       | Pass   | `_schedule_stall_detection`: accepted→awaiting_output→stalled; cancelled on tool_use, agent_stop, close, error          |
| R5. Observability and validation       | Pass   | 12 contract tests, 6 adapter tests, 5 coordinator tests; debug logging at all transitions with session/status/reason    |

---

## Why No New Issues

1. **Paradigm-fit verified:** Traced data flow from core through event_bus to all adapters. Confirmed no adapter invents status — all consume `SessionStatusContext` from event_bus subscription. Checked `_format_lifecycle_status` reuse across Discord/Telegram (single staticmethod, no duplication).
2. **Requirements validated:** Each R1-R5 requirement traced to specific code paths. R4 stall detection verified by reading `_schedule_stall_detection` with `_cancel_stall_task` calls at all exit points (tool_use, agent_stop, session_closed, agent_error).
3. **Copy-paste duplication checked:** No duplicated logic across adapters. Discord and Telegram each have distinct rendering strategies (status message vs footer) while sharing the formatting utility. The `_emit_status_event` pattern mirrors `_emit_activity_event` but is not a copy — it uses the status contract serializer instead of the activity contract.

---

## Summary

Independent round 3 review confirms the implementation is sound. All 7 round 1 findings remain correctly resolved. No new critical or important issues found.

The implementation satisfies all five requirements:

- Core is the single source of truth for lifecycle status semantics (R1)
- Canonical contract validates all outbound status events with explicit vocabulary and required fields (R2)
- Adapters render truthfully from the canonical stream — Discord edit-in-place, Telegram footer, WS broadcast, TUI notification (R3)
- Stall detection transitions correctly (accepted → awaiting_output → stalled) and cleans up at all exit points (R4)
- 23 new tests cover contract, adapter, and coordinator behavior; debug logging at all transitions (R5)

Four suggestions remain (routing metadata gap in closed DTO, test assertion style, implementation plan checkboxes). None block approval.

**Tests:** 2107 passed, 106 skipped
**Lint:** ruff + pyright clean
