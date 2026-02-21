"""Standalone Textual markdown editor for tmux pane integration.

Launched by the TUI via PaneManagerBridge as a subprocess in the right
tmux pane. Supports view mode (--view, read-only) and edit mode (default,
auto-saves on exit and on focus loss).

Usage: python -m teleclaude.cli.editor [-v|--view] [--theme NAME] <filepath>
"""

from __future__ import annotations

import argparse
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.events import AppBlur
from textual.widgets import Label, TextArea

from teleclaude.cli.tui.theme import (
    _TELECLAUDE_DARK_AGENT_THEME,
    _TELECLAUDE_DARK_THEME,
    _TELECLAUDE_LIGHT_AGENT_THEME,
    _TELECLAUDE_LIGHT_THEME,
)


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

    def __init__(
        self,
        file_path: Path,
        *,
        view_mode: bool = False,
        theme_name: str = "teleclaude-dark",
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.register_theme(_TELECLAUDE_DARK_THEME)
        self.register_theme(_TELECLAUDE_LIGHT_THEME)
        self.register_theme(_TELECLAUDE_DARK_AGENT_THEME)
        self.register_theme(_TELECLAUDE_LIGHT_AGENT_THEME)
        self.theme = theme_name

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
    parser = argparse.ArgumentParser(description="Standalone Textual markdown editor")
    parser.add_argument("filepath", type=Path, help="Path to markdown file")
    parser.add_argument("-v", "--view", action="store_true", help="View mode (read-only)")
    parser.add_argument("--theme", default="teleclaude-dark", help="Textual theme name")

    args = parser.parse_args()

    app = EditorApp(file_path=args.filepath, view_mode=args.view, theme_name=args.theme)
    app.run()


if __name__ == "__main__":
    main()
