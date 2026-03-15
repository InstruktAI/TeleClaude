# Implementation Plan: chartest-tui-views

## Approach

For each source file, follow OBSERVE-ASSERT-VERIFY:

1. Read the source, identify public functions/methods/classes
2. Write tests asserting observed behavior at public boundaries
3. Verify each test would catch a deliberate mutation

Commit after completing each file's characterization tests.

## Tasks

- [x] Characterize `teleclaude/cli/tui/views/_config_constants.py` → `tests/unit/cli/tui/views/test__config_constants.py`
- [x] Characterize `teleclaude/cli/tui/views/base.py` → `tests/unit/cli/tui/views/test_base.py`
- [x] Characterize `teleclaude/cli/tui/views/config.py` → `tests/unit/cli/tui/views/test_config.py`
- [x] Characterize `teleclaude/cli/tui/views/config_editing.py` → `tests/unit/cli/tui/views/test_config_editing.py`
- [x] Characterize `teleclaude/cli/tui/views/config_render.py` → `tests/unit/cli/tui/views/test_config_render.py`
- [x] Characterize `teleclaude/cli/tui/views/interaction.py` → `tests/unit/cli/tui/views/test_interaction.py`
- [x] Characterize `teleclaude/cli/tui/views/jobs.py` → `tests/unit/cli/tui/views/test_jobs.py`
- [x] Characterize `teleclaude/cli/tui/views/preparation.py` → `tests/unit/cli/tui/views/test_preparation.py`
- [x] Characterize `teleclaude/cli/tui/views/preparation_actions.py` → `tests/unit/cli/tui/views/test_preparation_actions.py`
- [x] Characterize `teleclaude/cli/tui/views/sessions.py` → `tests/unit/cli/tui/views/test_sessions.py`
- [x] Characterize `teleclaude/cli/tui/views/sessions_actions.py` → `tests/unit/cli/tui/views/test_sessions_actions.py`
- [x] Characterize `teleclaude/cli/tui/views/sessions_highlights.py` → `tests/unit/cli/tui/views/test_sessions_highlights.py`
- [x] Characterize `teleclaude/cli/tui/widgets/activity_row.py` → `tests/unit/cli/tui/widgets/test_activity_row.py`
- [x] Characterize `teleclaude/cli/tui/widgets/agent_badge.py` → `tests/unit/cli/tui/widgets/test_agent_badge.py`
- [ ] Characterize `teleclaude/cli/tui/widgets/agent_status.py` → `tests/unit/cli/tui/widgets/test_agent_status.py`
- [ ] Characterize `teleclaude/cli/tui/widgets/banner.py` → `tests/unit/cli/tui/widgets/test_banner.py`
- [ ] Characterize `teleclaude/cli/tui/widgets/box_tab_bar.py` → `tests/unit/cli/tui/widgets/test_box_tab_bar.py`
- [ ] Characterize `teleclaude/cli/tui/widgets/computer_header.py` → `tests/unit/cli/tui/widgets/test_computer_header.py`
- [ ] Characterize `teleclaude/cli/tui/widgets/group_separator.py` → `tests/unit/cli/tui/widgets/test_group_separator.py`
- [ ] Characterize `teleclaude/cli/tui/widgets/job_row.py` → `tests/unit/cli/tui/widgets/test_job_row.py`
- [ ] Characterize `teleclaude/cli/tui/widgets/modals.py` → `tests/unit/cli/tui/widgets/test_modals.py`
- [ ] Characterize `teleclaude/cli/tui/widgets/project_header.py` → `tests/unit/cli/tui/widgets/test_project_header.py`
- [ ] Characterize `teleclaude/cli/tui/widgets/status_bar.py` → `tests/unit/cli/tui/widgets/test_status_bar.py`
- [ ] Characterize `teleclaude/cli/tui/widgets/telec_footer.py` → `tests/unit/cli/tui/widgets/test_telec_footer.py`
- [ ] Characterize `teleclaude/cli/tui/widgets/todo_file_row.py` → `tests/unit/cli/tui/widgets/test_todo_file_row.py`
- [ ] Characterize `teleclaude/cli/tui/widgets/todo_row.py` → `tests/unit/cli/tui/widgets/test_todo_row.py`
