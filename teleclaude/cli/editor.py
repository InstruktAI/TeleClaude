"""Standalone Textual file editor for tmux pane integration.

Launched by the TUI via PaneManagerBridge as a subprocess in the right
tmux pane. Supports view mode (--view, read-only) and edit mode (default,
auto-saves on exit and on focus loss).

The editor can open a real filesystem path or materialize a todo artifact from
todos.db into a temporary file. File type is detected from extension: markdown
files get rich preview in view mode; all other files use syntax-highlighted
TextArea in both modes.

Usage:
  python -m teleclaude.cli.editor [-v|--view] [--theme NAME] <filepath>
  python -m teleclaude.cli.editor --project-root PATH --artifact-slug SLUG --artifact-name NAME
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.events import AppBlur
from textual.widgets import Label, Markdown, TextArea

from teleclaude.cli.tui.theme import (
    _TELECLAUDE_DARK_AGENT_THEME,
    _TELECLAUDE_DARK_THEME,
    _TELECLAUDE_LIGHT_AGENT_THEME,
    _TELECLAUDE_LIGHT_THEME,
)
from teleclaude.core.todos_db import TodosDb
from teleclaude.todo_artifacts import artifact_display_filename


@dataclass
class MaterializedArtifact:
    """Temporary-file backing for a DB-stored todo artifact."""

    project_root: Path
    slug: str
    artifact_name: str
    file_path: Path
    _temp_dir_path: Path
    _db: TodosDb

    @classmethod
    def from_db(cls, *, project_root: Path, slug: str, artifact_name: str) -> MaterializedArtifact:
        """Materialize an artifact from todos.db into a temporary file."""
        db_path = project_root / ".teleclaude" / "todos.db"
        if not db_path.exists():
            raise FileNotFoundError(f"Todos DB not found: {db_path}")
        db = TodosDb(str(db_path))
        temp_dir = Path(tempfile.mkdtemp(prefix="teleclaude-artifact-"))
        file_path = temp_dir / artifact_display_filename(artifact_name)
        file_path.write_text(db.read_artifact_sync(slug, artifact_name), encoding="utf-8")
        return cls(
            project_root=project_root,
            slug=slug,
            artifact_name=artifact_name,
            file_path=file_path,
            _temp_dir_path=temp_dir,
            _db=db,
        )

    @property
    def display_name(self) -> str:
        """Return the user-facing filename for the materialized artifact."""
        return artifact_display_filename(self.artifact_name)

    def persist(self, content: str) -> None:
        """Write updated temp-file content back to todos.db."""
        self._db.write_artifact_sync(
            self.slug,
            self.artifact_name,
            content,
            updated_by="teleclaude.cli.editor",
        )

    def cleanup(self) -> None:
        """Remove the temporary file backing this artifact."""
        shutil.rmtree(self._temp_dir_path, ignore_errors=True)


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
    #view-area {
        height: 1fr;
        padding: 0 1;
    }
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        file_path: Path,
        *,
        view_mode: bool = False,
        theme_name: str = "teleclaude-dark",
        display_name: str | None = None,
        save_callback: Callable[[str], None] | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.register_theme(_TELECLAUDE_DARK_THEME)
        self.register_theme(_TELECLAUDE_LIGHT_THEME)
        self.register_theme(_TELECLAUDE_DARK_AGENT_THEME)
        self.register_theme(_TELECLAUDE_LIGHT_AGENT_THEME)
        self.theme = theme_name

        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        self.file_path = file_path
        self.display_name = display_name or file_path.name
        self.view_mode = view_mode
        self._save_callback = save_callback
        self._last_saved_content: str | None = None

    _LANGUAGE_MAP: dict[str, str] = {
        ".py": "python",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".json": "json",
        ".toml": "toml",
        ".md": "markdown",
        ".txt": "markdown",
    }

    _MARKDOWN_EXTS: set[str] = {".md", ".txt"}

    def compose(self) -> ComposeResult:
        mode_label = "VIEW" if self.view_mode else "EDIT"
        yield Label(f" [{mode_label}] {self.display_name}", id="editor-title")
        content = self.file_path.read_text(encoding="utf-8")
        self._last_saved_content = content
        ext = self.file_path.suffix.lower()
        language = self._LANGUAGE_MAP.get(ext, "markdown")
        is_markdown = ext in self._MARKDOWN_EXTS
        if self.view_mode and is_markdown:
            with VerticalScroll(id="view-area"):
                yield Markdown(content)
        else:
            yield TextArea(
                content,
                language=language,
                soft_wrap=True,
                show_line_numbers=True,
                tab_behavior="indent",
                read_only=self.view_mode,
                id="editor-area",
            )

    def on_mount(self) -> None:
        """Focus the editor area on mount."""
        editors = self.query("#editor-area")
        if editors:
            editors.first(TextArea).focus()

    def on_app_blur(self, _event: AppBlur) -> None:
        """Auto-save when the pane loses focus (requires tmux focus-events on)."""
        if self.view_mode:
            return
        editor = self.query_one("#editor-area", TextArea)
        self._save_if_changed(editor.text)

    def action_save(self) -> None:
        """Save the current file content."""
        if self.view_mode:
            return
        editor = self.query_one("#editor-area", TextArea)
        self._save_content(editor.text)

    def action_save_and_quit(self) -> None:
        """Save current content and exit the editor."""
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
        if self._save_callback is not None:
            try:
                self._save_callback(content)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                self.notify(f"Save failed: {exc}", severity="error")
                return
        self._last_saved_content = content


def main() -> None:
    """CLI entry point for the standalone editor."""
    parser = argparse.ArgumentParser(description="Standalone Textual file editor")
    parser.add_argument("filepath", nargs="?", type=Path, help="Path to a real file")
    parser.add_argument("-v", "--view", action="store_true", help="View mode (read-only)")
    parser.add_argument("--theme", default="teleclaude-dark", help="Textual theme name")
    parser.add_argument("--project-root", type=Path, help="Project root that owns the artifact database")
    parser.add_argument("--artifact-slug", help="Todo slug for DB-backed artifact editing")
    parser.add_argument("--artifact-name", help="Logical artifact name in todos.db")

    args = parser.parse_args()
    materialized: MaterializedArtifact | None = None

    artifact_mode = args.project_root is not None and args.artifact_slug is not None and args.artifact_name is not None
    if args.filepath and artifact_mode:
        parser.error("filepath and artifact arguments are mutually exclusive")
    if not args.filepath and not artifact_mode:
        parser.error("provide either filepath or --project-root/--artifact-slug/--artifact-name")

    if artifact_mode:
        materialized = MaterializedArtifact.from_db(
            project_root=args.project_root.resolve(),
            slug=args.artifact_slug,
            artifact_name=args.artifact_name,
        )
        file_path = materialized.file_path
        display_name = materialized.display_name
        save_callback = None if args.view else materialized.persist
    else:
        assert args.filepath is not None
        file_path = args.filepath
        display_name = None
        save_callback = None

    app = EditorApp(
        file_path=file_path,
        view_mode=args.view,
        theme_name=args.theme,
        display_name=display_name,
        save_callback=save_callback,
    )
    try:
        app.run()
    finally:
        if materialized is not None:
            materialized.cleanup()


if __name__ == "__main__":
    main()
