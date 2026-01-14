# Code Review: model-boundary-consolidation

**Reviewed**: 2026-01-13
**Reviewer**: Codex

## Completeness Verification

### Implementation Plan Status
- Unchecked tasks: 0
- Silent deferrals found: no

### Success Criteria Verification

| Criterion | Implemented | Call Path | Test | Status |
|-----------|-------------|-----------|------|--------|
| REST and WS responses are validated via DTOs at the boundary. | `teleclaude/adapters/rest_adapter.py:109`, `teleclaude/adapters/rest_adapter.py:812` (partial) | RESTAdapter.list_sessions -> SessionSummaryDTO; RESTAdapter._on_cache_change -> ws.send_json | tests/unit/test_rest_adapter.py::test_list_sessions_success; NO TEST for WS update DTO validation | ❌ |
| Core logic uses dataclasses only. | `teleclaude/core/models.py:30` | command_handlers.handle_list_sessions -> SessionSummary dataclass | tests/unit/test_rest_adapter.py::test_list_sessions_success | ✅ |
| No REST read endpoint returns aggregate payloads. | NOT FOUND (see `teleclaude/adapters/rest_adapter.py:449`) | GET /projects-with-todos -> RESTAdapter.list_projects_with_todos -> ProjectWithTodosDTO | tests/unit/test_rest_adapter.py::test_list_projects_with_todos_success | ❌ |
| Docs point to the canonical model files. | `docs/rest-api.md:4`, `docs/tui-data-requirements.md:5` | docs reference core models and DTOs | N/A | ✅ |

**Verification notes:**
- REST list endpoints build DTOs, but WebSocket cache change events for non-session data bypass DTO validation and may emit dataclass instances directly.

### Integration Test Check
- Main flow integration test exists: yes
- Test file: `tests/integration/test_e2e_smoke.py`
- Coverage: WebSocket subscription and cache -> WS event flow
- Quality: heavy use of mocks, limited end-to-end verification of serialized payloads

### Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| Single Source of Truth | ✅ | Core resource dataclasses live in `teleclaude/core/models.py`. |
| Boundary Validation Only | ⚠️ | WS cache-change events emit raw data without DTO validation. |
| DTO Layer | ⚠️ | DTOs exist, but aggregate DTOs are still used in REST. |
| Remove Ad-Hoc Shapes | ❌ | `/projects-with-todos` returns aggregate payloads. |
| Client Alignment | ✅ | CLI models now alias REST DTOs in `teleclaude/cli/models.py`. |
| Documentation Reference | ✅ | REST and TUI docs reference canonical models. |

## Critical Issues (must fix)

- [code] `teleclaude/adapters/rest_adapter.py:449` - REST read endpoint `/projects-with-todos` still returns aggregate payloads, which violates the requirement to remove mixed-resource responses and contradicts `docs/rest-api.md`.
  - Suggested fix: remove `/projects-with-todos`, update any callers to fetch `/projects` and `/todos` separately, and delete the related tests.

## Important Issues (should fix)

- [code] `teleclaude/adapters/rest_adapter.py:812` - WebSocket cache-change events for projects, todos, and computers do not map to DTOs and may include dataclass objects (from `teleclaude/core/cache.py:259`). This breaks the stated boundary-validation rule and risks JSON serialization failures.
  - Suggested fix: normalize cache-change payloads through DTOs (or explicit `.to_dict()` conversion for nested lists) before `ws.send_json`, and add a WS update serialization test.

## Suggestions (nice to have)

- [tests] `tests/integration/test_e2e_smoke.py` - Add a coverage case for `projects_updated` and `todos_updated` WebSocket events to validate serialized payloads.

## Strengths

- DTOs and core dataclasses are now aligned across REST and CLI models.
- Session summary generation is centralized in `command_handlers.handle_list_sessions` and reused by REST.
- Tests were updated to exercise new DTO-backed responses.

## Verdict

**[ ] APPROVE** - Ready to merge
**[x] REQUEST CHANGES** - Fix critical/important issues first

### If REQUEST CHANGES:

Priority fixes:
1. Remove `/projects-with-todos` aggregate REST endpoint and update callers/tests.
2. Ensure WS cache-change events are DTO-validated and JSON-serializable.
