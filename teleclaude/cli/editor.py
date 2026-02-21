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
from textual.widgets import Label, TextArea


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
