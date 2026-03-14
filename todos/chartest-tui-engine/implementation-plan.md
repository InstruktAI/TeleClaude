# Implementation Plan: chartest-tui-engine

## Approach

For each source file, follow OBSERVE-ASSERT-VERIFY:

1. Read the source, identify public functions/methods/classes
2. Write tests asserting observed behavior at public boundaries
3. Verify each test would catch a deliberate mutation

Commit after completing each file's characterization tests.

## Tasks

- [ ] Characterize `teleclaude/cli/tui/_pane_specs.py` → `tests/unit/cli/tui/test__pane_specs.py`
- [ ] Characterize `teleclaude/cli/tui/app_actions.py` → `tests/unit/cli/tui/test_app_actions.py`
- [ ] Characterize `teleclaude/cli/tui/app_media.py` → `tests/unit/cli/tui/test_app_media.py`
- [ ] Characterize `teleclaude/cli/tui/app_ws.py` → `tests/unit/cli/tui/test_app_ws.py`
- [ ] Characterize `teleclaude/cli/tui/base.py` → `tests/unit/cli/tui/test_base.py`
- [ ] Characterize `teleclaude/cli/tui/color_utils.py` → `tests/unit/cli/tui/test_color_utils.py`
- [ ] Characterize `teleclaude/cli/tui/config_components/guidance.py` → `tests/unit/cli/tui/config_components/test_guidance.py`
- [ ] Characterize `teleclaude/cli/tui/controller.py` → `tests/unit/cli/tui/test_controller.py`
- [ ] Characterize `teleclaude/cli/tui/messages.py` → `tests/unit/cli/tui/test_messages.py`
- [ ] Characterize `teleclaude/cli/tui/pane_bridge.py` → `tests/unit/cli/tui/test_pane_bridge.py`
- [ ] Characterize `teleclaude/cli/tui/pane_layout.py` → `tests/unit/cli/tui/test_pane_layout.py`
- [ ] Characterize `teleclaude/cli/tui/pane_manager.py` → `tests/unit/cli/tui/test_pane_manager.py`
- [ ] Characterize `teleclaude/cli/tui/pane_theming.py` → `tests/unit/cli/tui/test_pane_theming.py`
- [ ] Characterize `teleclaude/cli/tui/persistence.py` → `tests/unit/cli/tui/test_persistence.py`
- [ ] Characterize `teleclaude/cli/tui/pixel_mapping.py` → `tests/unit/cli/tui/test_pixel_mapping.py`
- [ ] Characterize `teleclaude/cli/tui/prep_tree.py` → `tests/unit/cli/tui/test_prep_tree.py`
- [ ] Characterize `teleclaude/cli/tui/session_launcher.py` → `tests/unit/cli/tui/test_session_launcher.py`
- [ ] Characterize `teleclaude/cli/tui/state.py` → `tests/unit/cli/tui/test_state.py`
- [ ] Characterize `teleclaude/cli/tui/state_store.py` → `tests/unit/cli/tui/test_state_store.py`
- [ ] Characterize `teleclaude/cli/tui/theme.py` → `tests/unit/cli/tui/test_theme.py`
- [ ] Characterize `teleclaude/cli/tui/todos.py` → `tests/unit/cli/tui/test_todos.py`
- [ ] Characterize `teleclaude/cli/tui/tree.py` → `tests/unit/cli/tui/test_tree.py`
- [ ] Characterize `teleclaude/cli/tui/utils/formatters.py` → `tests/unit/cli/tui/utils/test_formatters.py`
