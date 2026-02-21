"""Standalone Textual markdown editor for tmux pane integration.

Launched by the TUI via PaneManagerBridge as a subprocess in the right
tmux pane. Supports view mode (--view, read-only) and edit mode (default,
auto-saves on exit and on focus loss).

Usage: python -m teleclaude.cli.editor [-v|--view] <filepath>
"""

from __future__ import annotations

import sys
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.events import AppBlur
from textual.widgets import Label, TextArea


class EditorApp(App[None]):
    """Minimal markdown editor with auto-save.

    Supports two modes:
    - Edit mode (default): full editing with auto-save on exit and focus loss.
    - View mode (--view): read-only preview, no save.
    """

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

    def __init__(self, file_path: Path, *, view_mode: bool = False, **kwargs: object) -> None:
        super().__init__(**kwargs)
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        self.file_path = file_path
        self.view_mode = view_mode
        self._last_saved_content: str | None = None

    def compose(self) -> ComposeResult:
        mode_label = "VIEW" if self.view_mode else "EDIT"
        yield Label(f" [{mode_label}] {self.file_path.name}", id="editor-title")
        content = self.file_path.read_text(encoding="utf-8")
        self._last_saved_content = content
        yield TextArea(
            content,
            language="markdown",
            soft_wrap=True,
            show_line_numbers=True,
            tab_behavior="indent",
            read_only=self.view_mode,
            id="editor-area",
        )

    def on_mount(self) -> None:
        if not self.view_mode:
            self.query_one("#editor-area", TextArea).focus()

    def on_app_blur(self, _event: AppBlur) -> None:
        """Auto-save when the pane loses focus (requires tmux focus-events on)."""
        if self.view_mode:
            return
        editor = self.query_one("#editor-area", TextArea)
        self._save_if_changed(editor.text)

    def action_save(self) -> None:
        if self.view_mode:
            return
        editor = self.query_one("#editor-area", TextArea)
        self._save_content(editor.text)

    def action_save_and_quit(self) -> None:
        if not self.view_mode:
            editor = self.query_one("#editor-area", TextArea)
            self._save_content(editor.text)
        self.exit()

    def _save_if_changed(self, content: str) -> None:
        """Save only if content differs from last saved state."""
        if content != self._last_saved_content:
            self._save_content(content)

    def _save_content(self, content: str) -> None:
        self.file_path.write_text(content, encoding="utf-8")
        self._last_saved_content = content


def main() -> None:
    args = sys.argv[1:]
    view_mode = False
    if args and args[0] in ("-v", "--view"):
        view_mode = True
        args = args[1:]
    if not args:
        print("Usage: python -m teleclaude.cli.editor [-v|--view] <filepath>", file=sys.stderr)
        sys.exit(1)
    file_path = Path(args[0])
    app = EditorApp(file_path=file_path, view_mode=view_mode)
    app.run()


if __name__ == "__main__":
    main()
