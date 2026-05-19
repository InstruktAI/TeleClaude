"""Standalone themed markdown viewer/editor for todo artifacts.

This command is launched in a tmux pane by the preparation view.

- View mode runs a themed Textual markdown preview.
- Edit mode runs a themed Textual markdown editor with TeleClaude-owned save
  semantics. Escape saves if changed and exits.
- For DB-backed artifacts, content is materialized into a temporary file before
  editing and persisted back through the daemon API on save/exit.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import signal
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.events import AppBlur
from textual.widgets import Label, Markdown, TextArea

from teleclaude.cli.tool_client import tool_api_request
from teleclaude.cli.tui.theme import (
    _TELECLAUDE_DARK_AGENT_THEME,
    _TELECLAUDE_DARK_THEME,
    _TELECLAUDE_LIGHT_AGENT_THEME,
    _TELECLAUDE_LIGHT_THEME,
)
from teleclaude.todo_artifacts import artifact_display_filename, read_artifact_content


@dataclass
class MaterializedArtifact:
    """Temporary-file backing for a DB-stored todo artifact."""

    project_root: Path
    slug: str
    artifact_name: str
    file_path: Path
    _temp_dir_path: Path

    @classmethod
    def from_db(cls, *, project_root: Path, slug: str, artifact_name: str) -> MaterializedArtifact:
        """Materialize an artifact from todos.db into a temporary file."""
        temp_dir = Path(tempfile.mkdtemp(prefix="teleclaude-artifact-"))
        file_path = temp_dir / artifact_display_filename(artifact_name)
        file_path.write_text(read_artifact_content(project_root, slug, artifact_name), encoding="utf-8")
        return cls(
            project_root=project_root,
            slug=slug,
            artifact_name=artifact_name,
            file_path=file_path,
            _temp_dir_path=temp_dir,
        )

    @property
    def display_name(self) -> str:
        """Return the user-facing filename for the materialized artifact."""
        return artifact_display_filename(self.artifact_name)

    def persist(self, content: str) -> None:
        """Write updated temp-file content through the daemon artifact API."""
        tool_api_request(
            "POST",
            f"/todos/artifacts/{quote(self.slug, safe='')}/{quote(self.artifact_name, safe='')}",
            json_body={
                "content": content,
                "cwd": str(self.project_root),
                "updated_by": "teleclaude.cli.editor",
            },
        )

    def cleanup(self) -> None:
        """Remove the temporary file backing this artifact."""
        shutil.rmtree(self._temp_dir_path, ignore_errors=True)


def persist_if_changed(
    file_path: Path,
    content: str,
    *,
    last_saved_content: str,
    save_callback: Callable[[str], None] | None = None,
) -> bool:
    """Persist the buffer only when content differs from the last saved state."""
    if content == last_saved_content:
        return False
    if save_callback is not None:
        save_callback(content)
    file_path.write_text(content, encoding="utf-8")
    return True


class EditorApp(App[None]):
    """Themed markdown editor with TeleClaude-owned save semantics."""

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
    #editor-footer {
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """

    def __init__(
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
        self.view_mode = view_mode
        self.display_name = display_name or file_path.name
        self._save_callback = save_callback
        self._last_saved_content = self.file_path.read_text(encoding="utf-8")

    def compose(self) -> ComposeResult:
        mode_label = "VIEW" if self.view_mode else "EDIT"
        yield Label(f" [{mode_label}] {self.display_name}", id="editor-title")
        if self.view_mode:
            with VerticalScroll(id="view-area"):
                yield Markdown(self._last_saved_content)
            return
        yield TextArea(
            self._last_saved_content,
            language="markdown",
            soft_wrap=True,
            show_line_numbers=True,
            tab_behavior="indent",
            id="editor-area",
        )
        yield Label(" Esc save+close  Ctrl+S save", id="editor-footer")

    def on_mount(self) -> None:
        """Install shutdown handlers and focus the editable buffer."""
        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGHUP, signal.SIGTERM):
                loop.add_signal_handler(sig, self.exit)
        except (ValueError, OSError):
            pass  # not in asyncio context or signal unavailable
        if self.view_mode:
            return
        self.query_one("#editor-area", TextArea).focus()

    def on_app_blur(self, _event: AppBlur) -> None:
        """Auto-save when the pane loses focus."""
        if self.view_mode:
            return
        self._save_current_buffer(notify_unchanged=False)

    def action_save(self) -> None:
        """Persist the current buffer without leaving the editor."""
        if self.view_mode:
            return
        self._save_current_buffer(notify_unchanged=True)

    def action_save_and_quit(self) -> None:
        """Persist the current buffer and exit the editor."""
        if self.view_mode:
            self.exit()
            return
        if self._save_current_buffer(notify_unchanged=True):
            self.exit()

    def _set_status(self, message: str) -> None:
        self.query_one("#editor-footer", Label).update(f" {message}")

    def _save_current_buffer(self, *, notify_unchanged: bool) -> bool:
        editor = self.query_one("#editor-area", TextArea)
        content = editor.text
        try:
            changed = persist_if_changed(
                self.file_path,
                content,
                last_saved_content=self._last_saved_content,
                save_callback=self._save_callback,
            )
        except Exception as exc:
            self._set_status(f"Save failed: {exc}")
            return False
        if changed:
            self._last_saved_content = content
            self._set_status("Saved")
        elif notify_unchanged:
            self._set_status("No changes")
        return True


def _run_inline_editor(
    file_path: Path,
    display_name: str,
    *,
    view_mode: bool = False,
    theme_name: str = "teleclaude-dark",
    save_callback: Callable[[str], None] | None = None,
) -> int:
    """Run the themed Textual markdown app until the user exits."""
    app = EditorApp(
        file_path=file_path,
        view_mode=view_mode,
        theme_name=theme_name,
        display_name=display_name,
        save_callback=save_callback,
    )
    app.run()
    return 0


def main() -> None:
    """CLI entry point for the standalone viewer/editor."""
    parser = argparse.ArgumentParser(description="Standalone themed markdown viewer/editor")
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
    else:
        assert args.filepath is not None
        file_path = args.filepath
        display_name = file_path.name

    try:
        exit_code = _run_inline_editor(
            file_path,
            display_name,
            view_mode=args.view,
            theme_name=args.theme,
            save_callback=None if args.view or materialized is None else materialized.persist,
        )
    finally:
        if materialized is not None:
            materialized.cleanup()

    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
