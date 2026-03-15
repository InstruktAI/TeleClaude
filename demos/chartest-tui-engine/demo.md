# Demo: chartest-tui-engine

## Validation

```bash
. .venv/bin/activate && pytest tests/unit/cli/tui -q
```

```bash
. .venv/bin/activate && pytest tests/unit/cli/tui/config_components/test_guidance.py tests/unit/cli/tui/test__pane_specs.py tests/unit/cli/tui/test_app_actions.py tests/unit/cli/tui/test_app_media.py tests/unit/cli/tui/test_app_ws.py tests/unit/cli/tui/test_base.py tests/unit/cli/tui/test_color_utils.py tests/unit/cli/tui/test_controller.py tests/unit/cli/tui/test_messages.py tests/unit/cli/tui/test_pane_bridge.py tests/unit/cli/tui/test_pane_layout.py tests/unit/cli/tui/test_pane_manager.py tests/unit/cli/tui/test_pane_theming.py tests/unit/cli/tui/test_persistence.py tests/unit/cli/tui/test_pixel_mapping.py tests/unit/cli/tui/test_prep_tree.py tests/unit/cli/tui/test_session_launcher.py tests/unit/cli/tui/test_state.py tests/unit/cli/tui/test_state_store.py tests/unit/cli/tui/test_theme.py tests/unit/cli/tui/test_todos.py tests/unit/cli/tui/test_tree.py tests/unit/cli/tui/utils/test_formatters.py -q
```

## Guided Presentation

Run the full TUI unit subtree and show that the characterization suite passes end-to-end.

Call out that the delivery is test-only: no production TUI code changed, but each planned engine module now has a matching `tests/unit/cli/tui/...` file that pins current behavior.

Run the explicit 23-file characterization command and point out that it covers pane layout/theming, controller/state persistence, websocket/app mixins, tree building, and formatter utilities in one sweep.
