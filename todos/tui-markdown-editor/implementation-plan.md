# TUI Markdown Editor & Todo Creation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add inline markdown editing and one-key todo creation to the TUI preparation view, with a standalone Textual editor micro-app running in the right tmux pane.

**Architecture:** Standalone Textual app (`teleclaude.cli.editor`) provides a TextArea with markdown highlighting, launched in the right tmux pane via the existing PaneManagerBridge command pipeline (same as Glow). New `CreateTodoModal` for slug input, updated keybindings in PreparationView.

**Tech Stack:** Textual (TextArea widget with built-in markdown language support), existing tmux pane architecture.

**Design doc:** `docs/plans/2026-02-20-tui-markdown-editor-design.md`

---

### Task 1: Add input.md template and update scaffold

**Files:**

- Create: `templates/todos/input.md`
- Modify: `teleclaude/todo_scaffold.py:71-79`
- Modify: `tests/unit/test_todo_scaffold.py:12-20`

**Step 1: Update the existing test to expect input.md**

In `tests/unit/test_todo_scaffold.py`, the test `test_create_todo_skeleton_creates_expected_files` currently asserts `not (todo_dir / "input.md").exists()`. Change it to assert the file DOES exist:

```python
def test_create_todo_skeleton_creates_expected_files(tmp_path: Path) -> None:
    todo_dir = create_todo_skeleton(tmp_path, "sample-slug")

    assert todo_dir == tmp_path / "todos" / "sample-slug"
    assert (todo_dir / "requirements.md").exists()
    assert (todo_dir / "implementation-plan.md").exists()
    assert (todo_dir / "quality-checklist.md").exists()
    assert (todo_dir / "state.json").exists()
    assert (todo_dir / "input.md").exists()

    # Verify input.md has correct heading
    content = (todo_dir / "input.md").read_text()
    assert "# Input: sample-slug" in content
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_todo_scaffold.py::test_create_todo_skeleton_creates_expected_files -v`
Expected: FAIL — `assert (todo_dir / "input.md").exists()` fails

**Step 3: Create the input.md template**

Create `templates/todos/input.md`:

```markdown
# Input: {slug}

<!-- Brain dump — raw thoughts, ideas, context. Prepare when ready. -->
```

**Step 4: Add input.md to scaffold**

In `teleclaude/todo_scaffold.py`, after line 73 (the `checklist` line), add:

```python
    input_md = _read_template("input.md").format(slug=slug)
```

After line 79 (the `state.json` write), add:

```python
    _write_file(todo_dir / "input.md", input_md)
```

**Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_todo_scaffold.py -v`
Expected: All 4 tests PASS

**Step 6: Commit**

```
feat: add input.md to todo scaffold
```

---

### Task 2: Create the standalone editor micro-app

**Files:**

- Create: `teleclaude/cli/editor.py`
- Test: `tests/unit/cli/test_editor.py`

**Step 1: Write the test**

Create `tests/unit/cli/test_editor.py`:

```python
"""Tests for the standalone markdown editor app."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_editor_module_is_importable() -> None:
    """Editor module can be imported without side effects."""
    from teleclaude.cli.editor import EditorApp
    assert EditorApp is not None


def test_editor_app_creates_with_file_path(tmp_path: Path) -> None:
    """EditorApp accepts a file path and stores it."""
    test_file = tmp_path / "test.md"
    test_file.write_text("# Hello\n")

    from teleclaude.cli.editor import EditorApp
    app = EditorApp(file_path=test_file)
    assert app.file_path == test_file


def test_editor_app_rejects_missing_file() -> None:
    """EditorApp raises if file does not exist."""
    from teleclaude.cli.editor import EditorApp
    with pytest.raises(FileNotFoundError):
        EditorApp(file_path=Path("/nonexistent/file.md"))


def test_editor_save_writes_content(tmp_path: Path) -> None:
    """_save() writes TextArea content back to the file."""
    test_file = tmp_path / "test.md"
    test_file.write_text("original content")

    from teleclaude.cli.editor import EditorApp
    app = EditorApp(file_path=test_file)
    # Simulate what _save does with a known string
    app._save_content("new content")
    assert test_file.read_text() == "new content"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/cli/test_editor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'teleclaude.cli.editor'`

**Step 3: Create the editor app**

Create `teleclaude/cli/editor.py`:

```python
"""Standalone Textual markdown editor for tmux pane integration.

Launched by the TUI via PaneManagerBridge as a subprocess in the right
tmux pane, replacing Glow for editing. Auto-saves on exit.

Usage: python -m teleclaude.cli.editor <filepath>
"""

from __future__ import annotations

import sys
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Label, TextArea


class EditorApp(App[None]):
    """Minimal markdown editor with auto-save on exit."""

    BINDINGS = [
        Binding("escape", "save_and_quit", "Save & Quit", priority=True),
        Binding("ctrl+s", "save", "Save"),
    ]

    CSS = """
    #editor-title {
        height: 1;
        background: $surface;
        color: $text;
        padding: 0 1;
    }
    #editor-area {
        height: 1fr;
    }
    """

    def __init__(self, file_path: Path, **kwargs: object) -> None:
        super().__init__(**kwargs)
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        self.file_path = file_path

    def compose(self) -> ComposeResult:
        yield Label(f" {self.file_path.name}", id="editor-title")
        content = self.file_path.read_text(encoding="utf-8")
        yield TextArea(
            content,
            language="markdown",
            soft_wrap=True,
            show_line_numbers=True,
            tab_behavior="indent",
            id="editor-area",
        )

    def on_mount(self) -> None:
        self.query_one("#editor-area", TextArea).focus()

    def action_save(self) -> None:
        editor = self.query_one("#editor-area", TextArea)
        self._save_content(editor.text)

    def action_save_and_quit(self) -> None:
        editor = self.query_one("#editor-area", TextArea)
        self._save_content(editor.text)
        self.exit()

    def _save_content(self, content: str) -> None:
        self.file_path.write_text(content, encoding="utf-8")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m teleclaude.cli.editor <filepath>", file=sys.stderr)
        sys.exit(1)
    file_path = Path(sys.argv[1])
    app = EditorApp(file_path=file_path)
    app.run()


if __name__ == "__main__":
    main()
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/cli/test_editor.py -v`
Expected: All 4 tests PASS

**Step 5: Verify the editor runs manually**

Create a temp file and test:

```bash
echo "# Test\nHello world" > /tmp/test-editor.md
uv run python -m teleclaude.cli.editor /tmp/test-editor.md
```

Press Escape to save and quit. Verify `/tmp/test-editor.md` still has content.

**Step 6: Commit**

```
feat: add standalone Textual markdown editor for tmux pane
```

---

### Task 3: Add DocEditRequest message

**Files:**

- Modify: `teleclaude/cli/tui/messages.py:193-200`

**Step 1: Add the message class**

In `teleclaude/cli/tui/messages.py`, after the `DocPreviewRequest` class (line 200), add:

```python
class DocEditRequest(Message):
    """Request to edit a document in the editor pane."""

    def __init__(self, doc_id: str, command: str, title: str) -> None:
        super().__init__()
        self.doc_id = doc_id
        self.command = command
        self.title = title
```

**Step 2: Run existing tests to verify nothing breaks**

Run: `uv run pytest tests/unit/ -x --timeout=30 -q`
Expected: All pass

**Step 3: Commit**

```
feat: add DocEditRequest message for editor integration
```

---

### Task 4: Wire PaneManagerBridge to handle DocEditRequest

**Files:**

- Modify: `teleclaude/cli/tui/pane_bridge.py:12-18` (imports)
- Modify: `teleclaude/cli/tui/pane_bridge.py:125-134` (add handler)

**Step 1: Add import**

In `teleclaude/cli/tui/pane_bridge.py`, add `DocEditRequest` to the import from `messages`:

```python
from teleclaude.cli.tui.messages import (
    DataRefreshed,
    DocEditRequest,
    DocPreviewRequest,
    FocusPaneRequest,
    PreviewChanged,
    StickyChanged,
)
```

**Step 2: Add the handler**

After the `on_doc_preview_request` method (line 134), add:

```python
    def on_doc_edit_request(self, message: DocEditRequest) -> None:
        """Handle doc edit request — same as preview but with editor command."""
        logger.debug("on_doc_edit_request: doc=%s", message.doc_id)
        self._preview_session_id = None
        self._active_doc_preview = DocPreviewState(
            doc_id=message.doc_id,
            command=message.command,
            title=message.title,
        )
        self._apply()
```

**Step 3: Run existing tests**

Run: `uv run pytest tests/unit/ -x --timeout=30 -q`
Expected: All pass

**Step 4: Commit**

```
feat: wire PaneManagerBridge for DocEditRequest
```

---

### Task 5: Add CreateTodoModal

**Files:**

- Modify: `teleclaude/cli/tui/widgets/modals.py`
- Test: `tests/unit/cli/tui/test_create_todo_modal.py`

**Step 1: Write the test**

Create `tests/unit/cli/tui/test_create_todo_modal.py`:

```python
"""Tests for CreateTodoModal slug validation."""

from __future__ import annotations

import pytest

from teleclaude.todo_scaffold import SLUG_PATTERN


def test_slug_pattern_accepts_valid_slugs() -> None:
    assert SLUG_PATTERN.match("my-todo")
    assert SLUG_PATTERN.match("simple")
    assert SLUG_PATTERN.match("a-b-c-123")
    assert SLUG_PATTERN.match("fix42")


def test_slug_pattern_rejects_invalid_slugs() -> None:
    assert not SLUG_PATTERN.match("Bad Slug")
    assert not SLUG_PATTERN.match("UPPER")
    assert not SLUG_PATTERN.match("-leading-dash")
    assert not SLUG_PATTERN.match("trailing-dash-")
    assert not SLUG_PATTERN.match("")
    assert not SLUG_PATTERN.match("has_underscore")
```

**Step 2: Run test to verify it passes (slug validation is existing)**

Run: `uv run pytest tests/unit/cli/tui/test_create_todo_modal.py -v`
Expected: PASS (validates against existing SLUG_PATTERN)

**Step 3: Add CreateTodoModal to modals.py**

At the end of `teleclaude/cli/tui/widgets/modals.py`, add:

```python
class CreateTodoModal(ModalScreen[str | None]):
    """Todo creation modal — single input for slug name."""

    BINDINGS = [
        ("escape", "dismiss_modal", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box") as box:
            box.border_title = "New Todo"
            yield Label("Enter a slug (lowercase, hyphens, numbers):", id="slug-label")
            yield Input(placeholder="my-new-todo", id="slug-input")
            yield Label("", id="slug-error")
            with Horizontal(id="modal-actions"):
                yield Button("[Enter] Create", variant="primary", id="create-btn")
                yield Button("[Esc] Cancel", id="cancel-btn")

    def on_mount(self) -> None:
        self.query_one("#slug-input", Input).focus()

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._do_create()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
            return
        if event.button.id == "create-btn":
            self._do_create()

    def _do_create(self) -> None:
        from teleclaude.todo_scaffold import SLUG_PATTERN

        slug_input = self.query_one("#slug-input", Input)
        error_label = self.query_one("#slug-error", Label)
        slug = slug_input.value.strip()

        if not slug:
            error_label.update("Slug is required")
            return
        if not SLUG_PATTERN.match(slug):
            error_label.update("Invalid: use lowercase, numbers, hyphens only")
            return

        self.dismiss(slug)
```

**Step 4: Run tests**

Run: `uv run pytest tests/unit/cli/tui/test_create_todo_modal.py tests/unit/ -x --timeout=30 -q`
Expected: All pass

**Step 5: Commit**

```
feat: add CreateTodoModal for TUI todo creation
```

---

### Task 6: Update PreparationView keybindings and actions

**Files:**

- Modify: `teleclaude/cli/tui/views/preparation.py:12-18` (imports)
- Modify: `teleclaude/cli/tui/views/preparation.py:39-50` (BINDINGS)
- Modify: `teleclaude/cli/tui/views/preparation.py:247-255` (add editor command builder)
- Modify: `teleclaude/cli/tui/views/preparation.py:306-320` (action_activate)
- Add: new `action_new_todo` method

**Step 1: Add imports**

In `teleclaude/cli/tui/views/preparation.py`, add the new message import. Find the existing import of `DocPreviewRequest` and `TodoSelected` and add `DocEditRequest`:

```python
from teleclaude.cli.tui.messages import (
    DocEditRequest,
    DocPreviewRequest,
    TodoSelected,
)
```

Also add the modal import at the top:

```python
from teleclaude.cli.tui.widgets.modals import CreateTodoModal
```

**Step 2: Add keybinding for `n`**

In the `BINDINGS` list, add:

```python
    ("n", "new_todo", "New todo"),
```

**Step 3: Add editor command builder**

After `_glow_command` method, add:

```python
    def _editor_command(self, slug: str, filename: str) -> str:
        """Build an editor command with absolute path for tmux pane."""
        project_path = self._slug_to_project_path.get(slug, "")
        if project_path:
            filepath = f"{project_path}/todos/{slug}/{filename}"
        else:
            filepath = f"todos/{slug}/{filename}"
        return f"uv run python -m teleclaude.cli.editor {filepath}"
```

**Step 4: Update action_activate to use editor for file rows**

Replace the file_row branch in `action_activate` (lines 312-320) with:

```python
        file_row = self._current_file_row()
        if file_row:
            self.post_message(
                DocEditRequest(
                    doc_id=f"todo:{file_row.slug}:{file_row.filename}",
                    command=self._editor_command(file_row.slug, file_row.filename),
                    title=f"Editing: {file_row.slug}/{file_row.filename}",
                )
            )
```

**Step 5: Add action_new_todo method**

After `action_start_work`, add:

```python
    def action_new_todo(self) -> None:
        """n: create a new todo via modal."""

        def _on_modal_result(slug: str | None) -> None:
            if not slug:
                return
            # Find project root from first known project path, or cwd
            project_root = None
            for path in self._slug_to_project_path.values():
                project_root = path
                break

            if not project_root:
                import os
                project_root = os.getcwd()

            from pathlib import Path
            from teleclaude.todo_scaffold import create_todo_skeleton

            try:
                todo_dir = create_todo_skeleton(Path(project_root), slug)
            except (ValueError, FileExistsError) as exc:
                self.notify(str(exc), severity="error")
                return

            # Open input.md in editor
            self.post_message(
                DocEditRequest(
                    doc_id=f"todo:{slug}:input.md",
                    command=self._editor_command(slug, "input.md"),
                    title=f"Editing: {slug}/input.md",
                )
            )

        self.app.push_screen(CreateTodoModal(), callback=_on_modal_result)
```

**Step 6: Run all tests**

Run: `uv run pytest tests/unit/ -x --timeout=30 -q`
Expected: All pass

**Step 7: Commit**

```
feat: wire editor and new-todo creation in PreparationView
```

---

### Task 7: Update ActionBar hints

**Files:**

- Modify: `teleclaude/cli/tui/widgets/action_bar.py:39-43`

**Step 1: Update the preparation context hints**

In `teleclaude/cli/tui/widgets/action_bar.py`, change the preparation entry in `_CONTEXT_BAR`:

```python
    _CONTEXT_BAR: dict[str, str] = {
        "preparation": "[Enter] Edit  [Space] Preview  [n] New Todo  [p] Prepare  [s] Start Work",
        "jobs": "[Enter] Run",
        "config": "[Tab] Next Field  [Enter] Edit",
    }
```

**Step 2: Run all tests**

Run: `uv run pytest tests/unit/ -x --timeout=30 -q`
Expected: All pass

**Step 3: Reload the TUI and verify**

```bash
pkill -SIGUSR2 -f -- "-m teleclaude.cli.telec$"
```

Switch to the Preparation tab and verify the action bar shows the updated hints.

**Step 4: Commit**

```
feat: update ActionBar hints for preparation view editor keybindings
```

---

### Task 8: End-to-end verification

**Step 1: Reload TUI**

```bash
pkill -SIGUSR2 -f -- "-m teleclaude.cli.telec$"
```

**Step 2: Test new todo creation**

1. Switch to Preparation tab (press `2`)
2. Press `n` — CreateTodoModal should appear
3. Type `test-braindump` and press Enter
4. Editor should open in the right tmux pane with `input.md`
5. Type some text, press Escape
6. Verify `todos/test-braindump/input.md` contains your text
7. Verify the todo row appears in the preparation view

**Step 3: Test file editing**

1. Expand any existing todo (Right arrow)
2. Navigate to a file row (Down arrow)
3. Press Enter — editor should open in right pane
4. Press Escape — should save and close
5. Press Space on same file — Glow preview should show

**Step 4: Clean up test todo**

```bash
rm -rf todos/test-braindump
```

**Step 5: Final commit**

If any fixes were needed, commit them. Otherwise, done.
