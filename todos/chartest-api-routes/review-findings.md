# Review Findings: chartest-api-routes

## Verdict: APPROVE

Unresolved Important: 0 | Resolved During Review: 2 | Suggestions: 4

---

## Scope Verification

All 19 source files have a corresponding test file. No production code was modified. No
unrequested features added. 1:1 source-to-test mapping confirmed. Demo artifact validated
(2 executable blocks, both real). Implementation plan tasks all checked.

## Code Review

Tests follow consistent patterns: pytest classes, `@pytest.mark.unit` + `@pytest.mark.asyncio`
markers, `unittest.mock` patching at architectural boundaries. Mock targets are correct
(patching at the module-under-test level). No test exceeds 5 mock patches per test.
Test names read as behavioral specifications.

## Paradigm-Fit

Tests use established project patterns: pytest with fixtures, class-based test organization,
`SimpleNamespace` stubs for lightweight fakes. Consistent with existing test files in the repo.

## Principle Violation Hunt

No principle violations found. This is a test-only delivery with no production code changes
or architectural decisions.

## Security

No secrets, credentials, or sensitive data in test code. Test data uses example/fake values.
No injection risks.

## Errors (Silent Failure Hunt)

No silent failures in the tests themselves. Tests exercise both happy paths and error paths.
Error path tests assert on HTTP status codes (behavioral boundary) rather than error message
prose (correct per testing policy).

## Tests

### Important (Resolved): Coverage gap in sessions_actions_routes.py

`sessions_actions_routes.py` had 11 public route endpoints, with only 4 covered by
characterization tests before the fix (`send_keys_endpoint`, `agent_restart`,
`send_result_endpoint`, `escalate_session`).

**Fixed coverage additions (7 endpoints):**

- `send_voice_endpoint`
- `send_file_endpoint`
- `revive_session`
- `get_session_messages`
- `run_session`
- `unsubscribe_session`
- `render_widget_endpoint`

The new tests pin the current boundary behavior for command mapping, native-session revive
resolution, transcript projection and fallback tail retrieval, worker lifecycle session
metadata, listener unsubscribe outcomes, and widget summary delivery. That closes the
largest remaining coverage gap in the file with the highest refactoring risk.

## Types

No new types introduced. N/A.

## Comments

All module docstrings are accurate. Test docstrings describe behavioral contracts, not
implementation details. No misleading comments found.

## Logging

No logging changes. N/A (test-only delivery).

## Demo

Demo artifact contains 2 executable blocks:

1. Python script verifying 1:1 file mapping — confirmed working.
2. pytest command running all 19 test files — confirmed passing (70 tests).

Guided presentation accurately describes the validation steps.

## Simplify

No simplification opportunities. Tests are appropriately concise.

---

## Resolved During Review

### 1. String assertion on human-facing text — test_agents_routes.py:37

**Was:** `assert response["claude"].model_dump()["reason"] == "Disabled in config.yml"`

The `reason` field is a human-facing informational string. Asserting exact text couples the
test to copywriting, violating the "no string assertions on human-facing text" requirement.

**Fix applied:** Changed to truthy assertion `assert response["claude"].model_dump()["reason"]`
to verify a reason is present without locking prose.

Also fixed a similar assertion on the `error` field at line 39.

### 2. String assertion on human-facing text — test_todo_routes.py:96

**Was:** `assert response == {"result": "OK: dependencies set for 'chartest-api-routes': base-task"}`

The `result` value is a human-readable status message. Same policy violation.

**Fix applied:** Changed to structural assertion verifying `"result"` key exists with a
truthy value.

---

## Fixes Applied

### 1. Coverage gap in sessions_actions_routes.py

**Issue:** Seven public session action endpoints lacked characterization coverage:
`send_voice_endpoint`, `send_file_endpoint`, `revive_session`, `get_session_messages`,
`run_session`, `unsubscribe_session`, and `render_widget_endpoint`.

**Fix:** Added public-boundary behavioral tests for all seven endpoints, including revive
session native-ID resolution, structured transcript projection plus fallback tail output,
worker lifecycle session metadata construction, unsubscribe success/error outcomes, and
widget summary delivery.

**Commit:** `96a95fa24a84f2232e68dfdd27954a3266dad838`

---

## Suggestions

### 1. Coverage gap in notifications_routes.py

3 of 6 public endpoints uncovered: `get_notification`, `mark_notification_seen`,
`update_notification_status`. Lower risk than sessions_actions_routes but still a gap.

### 2. Coverage gap in todo_routes.py

3 of 7 endpoints uncovered: `todo_prepare`, `todo_integrate`, `todo_mark_finalize_ready`.

### 3. sys.modules patching in test_sessions_actions_routes.py

Two tests use `patch.dict("sys.modules", ...)` to inject fake modules. While within the
5-patch limit, this is heavier than typical characterization test mocking. Consider importing
the dependency at test time instead.

### 4. Helper/fixture docstrings

Test helpers in `test_streaming.py` (`_make_request`, `_make_session`, `_collect_stream`,
`_parse_sse_event`) and the `_WebSocketMixinHarness` class in `test_ws_mixin.py` would
benefit from brief docstrings explaining their mock contracts.

---

## Why This Verdict

All blocking findings are resolved. The previously unresolved Important coverage gap in
`sessions_actions_routes.py` is now characterized across the full public route surface, and
the 19-file API characterization suite passes with 70 tests. Suggestions remain
non-blocking.
