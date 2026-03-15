# Review Findings: chartest-core-agent-coord

## Scope

Lane: scope

All 4 source files have corresponding test files (1:1 mapping). No production code modified.
No unrequested features. Implementation plan tasks all checked. No deferrals.

No findings.

## Code Review

Lane: code

Test code follows project conventions: `@pytest.mark.unit` markers, class-based grouping,
`_make_*` factory helpers, correct mock patch targets (patching at usage site).

### Resolved During Review

**Deprecated `asyncio.get_event_loop().run_until_complete()` pattern** (32 occurrences across
`test__coordinator.py`, `test__fanout.py`, `test__incremental.py`). The project has
`asyncio_mode = "auto"` with `pytest-asyncio` and established `async def test_*` pattern
(e.g., `test_tmux_delivery.py`). The deprecated API emitted `DeprecationWarning` at runtime.
**Remediated:** Converted all 32 sync tests to `async def` with `await`. Zero deprecation
warnings after fix.

## Paradigm Fit

Lane: paradigm

Test structure follows established codebase patterns: class-based test organization, `_make_*`
factory helpers, `@pytest.mark.unit` markers, correct mock target paths. After auto-remediation,
async tests use the standard `async def` pattern consistent with the rest of the suite.

No findings.

## Principle Violation Hunt

Lane: principles

No production code changes. Test code reviewed for SRP (each class covers one function/method),
KISS (minimal factory helpers), DRY (shared `_make_session`/`_make_coordinator` helpers). No
unjustified fallbacks — this is test code.

No findings.

## Security

Lane: security

Test-only delivery. No secrets, no user input paths, no injection surfaces, no auth changes.

No findings.

## Test Coverage

Lane: tests

**Important: Significant coverage gaps for key public methods in `_coordinator.py`**

`_coordinator.py` has 14 public/protected methods. Only 6 are tested (43%). The untested methods
include the three main event handlers that contain the core business logic:

- `handle_session_start` — session initialization, DB persistence, status emission, headless
  snapshot, TTS. No tests.
- `handle_user_prompt_submit` — the most complex method (~170 lines) with checkpoint detection,
  Codex deduplication, echo guard, linked-output tracking. No tests.
- `handle_agent_stop` — full stop sequence orchestration. No tests.
- `handle_tool_use` — first-tool-use-per-turn deduplication for checkpoint timing. No tests.
- `_queue_background_task` — async task lifecycle with error handling. No tests.
- `_record_agent_stop_input`, `_record_agent_stop_output` — input backfill and output
  normalization. No tests.
- `_speak_agent_stop_summary` — TTS with exception swallowing contract. No tests.

`_fanout.py` has partial gaps: `_extract_agent_output`, `_forward_stop_to_initiator`,
`_maybe_inject_checkpoint` untested. `_update_session_title_async` tested for guard paths only,
not the happy path.

The requirements state "Tests pin actual behavior at public boundaries." The test files exist
(1:1 mapping satisfied), and what IS tested is well-tested. But the safety net has significant
holes at the most complex coordinator methods.

Coverage by file:

| Source File       | Methods | Tested | Coverage |
| ----------------- | ------- | ------ | -------- |
| `_helpers.py`     | 15      | 15     | 100%     |
| `_coordinator.py` | 14      | 6      | 43%      |
| `_fanout.py`      | 10      | 6      | 60%      |
| `_incremental.py` | 8       | 6      | 75%      |

Severity: **Important**

## Silent Failures

Lane: errors

No Critical findings. The error-swallowing tests (`test_serializer_failure_does_not_raise`,
`test_summarize_exception_returns_none`, `test_tts_exception_does_not_propagate`) verify the
contract that exceptions don't propagate. Verifying that logging also occurs would strengthen
these tests but is not required for characterization.

Severity: **Suggestion** — Strengthen "no raise" tests by also asserting that `logger.error`
or `logger.warning` was called, preventing silent removal of diagnostic logging.

## Type Design

Lane: types

No types added or modified. Not triggered.

## Comments

Lane: comments

One inaccurate comment found and remediated during the asyncio fix:
`test__coordinator.py:271` — "handle_session_end only logs" replaced with
"Should complete without raising — characterization of current behavior."

Module docstrings are accurate and consistent. Factory docstrings are precise.

No remaining findings.

## Logging

Lane: logging

Test-only delivery. No logging policy concerns.

No findings.

## Demo

Lane: demo

`demos/chartest-core-agent-coord/demo.md` contains two executable bash blocks:

1. `python -m pytest tests/unit/core/agent_coordinator/ -v --tb=short -q 2>&1 | tail -20` — valid,
   runs the test suite.
2. `python -m pytest tests/unit/core/agent_coordinator/ --co -q 2>&1 | grep "test session" | head -5` —
   valid, lists collected tests.

The guided presentation accurately describes the 4 test files and their coverage areas.
No nonexistent flags or commands. No no-demo marker needed (tests are user-visible behavior).

No findings.

## Documentation

Lane: docs

No CLI, config, or API changes. Not triggered.

---

## Verdict

| Severity   | Count (Unresolved)                         |
| ---------- | ------------------------------------------ |
| Critical   | 0                                          |
| Important  | 1 (coverage gaps)                          |
| Suggestion | 1 (strengthen error-swallowing assertions) |

**Verdict: REQUEST CHANGES**

The test files exist for all 4 source files (1:1 mapping satisfied), and the tested functions
are well-characterized. However, the requirements state "Tests pin actual behavior at public
boundaries" and the three main event handlers (`handle_session_start`, `handle_user_prompt_submit`,
`handle_agent_stop`) — which contain the core business logic — have no characterization tests.
These are the primary public boundaries that other modules call via `handle_event`.

### Resolved During Review

- Converted 32 deprecated `asyncio.get_event_loop().run_until_complete()` calls to idiomatic
  `async def` tests with `await`, eliminating all deprecation warnings.
- Fixed inaccurate comment about `handle_session_end` behavior.

### Why No Issues (Lanes with Zero Findings)

- **Scope**: All 4 files mapped, no gold-plating, no production changes.
- **Paradigm**: Test structure matches established patterns (after async fix).
- **Principles**: No SRP/DIP/KISS violations in test code.
- **Security**: Test-only delivery, no attack surface.
- **Demo**: Executable blocks reference real commands and paths.
