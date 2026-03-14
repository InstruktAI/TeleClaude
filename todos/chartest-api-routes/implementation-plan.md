# Implementation Plan: chartest-api-routes

## Approach

For each source file, follow OBSERVE-ASSERT-VERIFY:

1. Read the source, identify public functions/methods/classes
2. Write tests asserting observed behavior at public boundaries
3. Verify each test would catch a deliberate mutation

Commit after completing each file's characterization tests.

## Tasks

- [ ] Characterize `teleclaude/api/agents_routes.py` → `tests/unit/api/test_agents_routes.py`
- [ ] Characterize `teleclaude/api/chiptunes_routes.py` → `tests/unit/api/test_chiptunes_routes.py`
- [ ] Characterize `teleclaude/api/computers_routes.py` → `tests/unit/api/test_computers_routes.py`
- [ ] Characterize `teleclaude/api/data_routes.py` → `tests/unit/api/test_data_routes.py`
- [ ] Characterize `teleclaude/api/event_routes.py` → `tests/unit/api/test_event_routes.py`
- [ ] Characterize `teleclaude/api/jobs_routes.py` → `tests/unit/api/test_jobs_routes.py`
- [ ] Characterize `teleclaude/api/notifications_routes.py` → `tests/unit/api/test_notifications_routes.py`
- [ ] Characterize `teleclaude/api/operations_routes.py` → `tests/unit/api/test_operations_routes.py`
- [ ] Characterize `teleclaude/api/people_routes.py` → `tests/unit/api/test_people_routes.py`
- [ ] Characterize `teleclaude/api/projects_routes.py` → `tests/unit/api/test_projects_routes.py`
- [ ] Characterize `teleclaude/api/session_access.py` → `tests/unit/api/test_session_access.py`
- [ ] Characterize `teleclaude/api/sessions_actions_routes.py` → `tests/unit/api/test_sessions_actions_routes.py`
- [ ] Characterize `teleclaude/api/sessions_routes.py` → `tests/unit/api/test_sessions_routes.py`
- [ ] Characterize `teleclaude/api/settings_routes.py` → `tests/unit/api/test_settings_routes.py`
- [ ] Characterize `teleclaude/api/streaming.py` → `tests/unit/api/test_streaming.py`
- [ ] Characterize `teleclaude/api/todo_routes.py` → `tests/unit/api/test_todo_routes.py`
- [ ] Characterize `teleclaude/api/transcript_converter.py` → `tests/unit/api/test_transcript_converter.py`
- [ ] Characterize `teleclaude/api/ws_constants.py` → `tests/unit/api/test_ws_constants.py`
- [ ] Characterize `teleclaude/api/ws_mixin.py` → `tests/unit/api/test_ws_mixin.py`
