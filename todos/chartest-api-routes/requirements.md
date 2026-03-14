# Requirements: chartest-api-routes

Characterization tests for API route handlers.

## Goal

Write characterization tests that pin current behavior of all listed source files
at their public boundaries, creating a safety net for future refactoring.

## Scope

### In scope

- Characterization tests for every listed source file
- 1:1 source-to-test file mapping under `tests/unit/`

### Out of scope

- Modifying production code
- Adding new features
- Refactoring existing code

## Source files

- `teleclaude/api/agents_routes.py`
- `teleclaude/api/chiptunes_routes.py`
- `teleclaude/api/computers_routes.py`
- `teleclaude/api/data_routes.py`
- `teleclaude/api/event_routes.py`
- `teleclaude/api/jobs_routes.py`
- `teleclaude/api/notifications_routes.py`
- `teleclaude/api/operations_routes.py`
- `teleclaude/api/people_routes.py`
- `teleclaude/api/projects_routes.py`
- `teleclaude/api/session_access.py`
- `teleclaude/api/sessions_actions_routes.py`
- `teleclaude/api/sessions_routes.py`
- `teleclaude/api/settings_routes.py`
- `teleclaude/api/streaming.py`
- `teleclaude/api/todo_routes.py`
- `teleclaude/api/transcript_converter.py`
- `teleclaude/api/ws_constants.py`
- `teleclaude/api/ws_mixin.py`

## Success criteria

- [ ] Every listed source file has a corresponding test file (or documented exemption)
- [ ] Tests pin actual behavior at public boundaries
- [ ] All tests pass on current codebase
- [ ] No string assertions on human-facing text
- [ ] Max 5 mock patches per test
- [ ] Each test name reads as a behavioral specification
- [ ] All existing tests still pass (no regressions)
- [ ] Lint and type checks pass

## Constraints

- Recommended agent: **codex**
- Follow OBSERVE-ASSERT-VERIFY cycle (not RED-GREEN-REFACTOR)
- Tests pass immediately — this is expected for characterization

## Methodology: Characterization Testing (OBSERVE-ASSERT-VERIFY)

Follow the OBSERVE-ASSERT-VERIFY cycle per source file. See testing policy for full details.

### Rules

- Test at public API boundaries only
- Behavioral contracts, not implementation details
- No string assertions on human-facing text
- Max 5 mock patches per test
- One clear expectation per test
- Mock at architectural boundaries (I/O, DB, network)
- Every test must answer: "What real bug in OUR code would this catch?"
- 1:1 source-to-test mapping
- Use pytest with standard fixtures
- Skip files with genuinely no testable logic — document why
