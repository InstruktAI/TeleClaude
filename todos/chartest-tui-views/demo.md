# Demo: chartest-tui-views

## Validation

```bash
# Verify all 26 characterization test files exist
ls tests/unit/cli/tui/views/test__config_constants.py \
   tests/unit/cli/tui/views/test_base.py \
   tests/unit/cli/tui/views/test_interaction.py \
   tests/unit/cli/tui/views/test_sessions_highlights.py \
   tests/unit/cli/tui/views/test_config_editing.py \
   tests/unit/cli/tui/widgets/test_agent_status.py \
   tests/unit/cli/tui/widgets/test_banner.py \
   tests/unit/cli/tui/widgets/test_todo_row.py \
   tests/unit/cli/tui/widgets/test_status_bar.py \
   tests/unit/cli/tui/widgets/test_telec_footer.py
```

```bash
# Run the new characterization tests to confirm all pass
. .venv/bin/activate && pytest tests/unit/cli/tui/ -v --tb=short 2>&1 | tail -5
```

## Guided Presentation

The delivery adds 26 characterization test files covering all TUI views and widgets.

Key files demonstrated:

- `tests/unit/cli/tui/views/test_interaction.py` — 14 tests for the `TreeInteractionState` debounce state machine (pure logic, no Textual required).
- `tests/unit/cli/tui/views/test_sessions_highlights.py` — 12 tests for the `SessionsViewHighlightsMixin` using a minimal fake host pattern.
- `tests/unit/cli/tui/widgets/test_agent_status.py` — 10 tests for pure helper functions `is_agent_degraded`, `is_agent_selectable`, `build_agent_render_spec`.
- `tests/unit/cli/tui/widgets/test_banner.py` — 14 tests for banner pure helpers and constants.
- `tests/unit/cli/tui/widgets/test_status_bar.py` — 10 tests for pane theming cells and state persistence.
