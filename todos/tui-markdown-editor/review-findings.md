# Review Findings: tui-markdown-editor

## Review Scope

Branch: `tui-markdown-editor` (9 commits, 13 files changed, +319/-45)

Files reviewed:

- `teleclaude/cli/editor.py` (new)
- `teleclaude/cli/tui/messages.py`
- `teleclaude/cli/tui/pane_bridge.py`
- `teleclaude/cli/tui/views/preparation.py`
- `teleclaude/cli/tui/widgets/action_bar.py`
- `teleclaude/cli/tui/widgets/modals.py`
- `teleclaude/todo_scaffold.py`
- `templates/todos/input.md` (new)
- `tests/unit/cli/test_editor.py` (new)
- `tests/unit/cli/tui/test_create_todo_modal.py` (new)
- `tests/unit/test_todo_scaffold.py`

## Requirements Tracing

| Requirement                                        | Status | Implementation                                                                                    |
| -------------------------------------------------- | ------ | ------------------------------------------------------------------------------------------------- |
| `n` opens slug modal, creates todo, opens input.md | Traced | `PreparationView.action_new_todo` → `CreateTodoModal` → `create_todo_skeleton` → `DocEditRequest` |
| `Enter` on TodoFileRow opens editor                | Traced | `action_activate` sends `DocEditRequest` with `_editor_command`                                   |
| `Space` on TodoFileRow shows Glow preview          | Traced | `action_preview_file` still sends `DocPreviewRequest` with `_glow_command`                        |
| Editor auto-saves on Escape, Ctrl+S works          | Traced | `EditorApp` bindings: escape→save_and_quit, ctrl+s→save                                           |
| `input.md` scaffolded with new todos               | Traced | `create_todo_skeleton` reads and writes `input.md` template                                       |
| Existing tests pass, new tests added               | Traced | 4 editor tests, 2 slug validation tests, scaffold test updated                                    |

All 6 success criteria are addressed.

## Critical

(none)

## Important

1. **Stale docstring in `todo_scaffold.py:49-58`** — The `create_todo_skeleton` docstring lists 4 created files but now creates 5 (`input.md` is missing from the "Creates:" list). Comments must describe the present.

## Suggestions

2. **Unused import in `tests/unit/cli/tui/test_create_todo_modal.py:6`** — `import pytest` is present but no `pytest.*` API is used in the file. Either remove or use `pytest.param`/parametrize to justify the import.

3. **No view refresh after todo creation** — `action_new_todo` creates the todo on disk but doesn't trigger a data refresh, so the new item won't appear in the preparation view until the next API poll cycle. Consider posting a refresh message or calling `update_data` after successful creation. This is a UX polish item and may be acceptable given the existing polling architecture.

## Verdict: APPROVE

The implementation is clean, follows existing patterns (message → bridge → pane pipeline), and all requirements are traced to working code. The editor micro-app is well-bounded. The only actionable finding is a stale docstring (Important #1), which does not block merge.
