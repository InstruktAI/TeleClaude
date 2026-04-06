"""Standalone temporary-file viewer/editor for todo artifacts.

This command is launched in a tmux pane by the preparation view.

- View mode prints the current file contents immediately and stays alive until
  tmux respawns or closes the pane.
- Edit mode uses a Textual text area with TeleClaude-owned save semantics.
  Escape saves if changed and exits. For DB-backed artifacts, content is
  materialized into a temporary file before editing and persisted back into
  todos.db on save/exit.
"""

from __future__ import annotations

import argparse
import shutil
import signal
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.events import AppBlur
from textual.widgets import Label, TextArea

from teleclaude.todo_artifacts import (
    artifact_display_filename,
    read_artifact_content,
    write_artifact_content,
)


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
        """Write updated temp-file content back to todos.db."""
        write_artifact_content(self.project_root, self.slug, self.artifact_name, content)

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
    """Inline Textual editor with save-on-escape semantics."""

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
        display_name: str | None = None,
        save_callback: Callable[[str], None] | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        self.file_path = file_path
        self.display_name = display_name or file_path.name
        self._save_callback = save_callback
        self._last_saved_content = self.file_path.read_text(encoding="utf-8")

    def compose(self) -> ComposeResult:
        yield Label(f" [EDIT] {self.display_name}", id="editor-title")
        yield TextArea(
            self._last_saved_content,
            soft_wrap=True,
            show_line_numbers=True,
            tab_behavior="indent",
            id="editor-area",
        )
        yield Label(" Esc save+close  Ctrl+S save", id="editor-footer")

    def on_mount(self) -> None:
        """Focus the editable buffer after the app mounts."""
        self.query_one("#editor-area", TextArea).focus()

    def on_app_blur(self, _event: AppBlur) -> None:
        """Auto-save when the pane loses focus."""
        self._save_current_buffer(notify_unchanged=False)

    def action_save(self) -> None:
        """Persist the current buffer without leaving the editor."""
        self._save_current_buffer(notify_unchanged=True)

    def action_save_and_quit(self) -> None:
        """Persist the current buffer and exit the editor."""
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
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._set_status(f"Save failed: {exc}")
            return False
        if changed:
            self._last_saved_content = content
            self._set_status("Saved")
        elif notify_unchanged:
            self._set_status("No changes")
        return True


def _render_view(file_path: Path, display_name: str) -> None:
    """Print a static preview that is visible immediately in the tmux pane."""
    content = file_path.read_text(encoding="utf-8")
    rule = "=" * min(max(len(display_name) + 8, 24), 80)
    print(f"[VIEW] {display_name}")
    print(rule)
    if content:
        print(content, end="" if content.endswith("\n") else "\n")


def _wait_until_terminated() -> None:
    """Keep the preview pane alive until tmux closes or respawns it."""

    def _exit(_signum: int, _frame: object) -> None:
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _exit)
    signal.signal(signal.SIGINT, _exit)
    try:
        while True:
            signal.pause()
    except AttributeError:
        while True:
            time.sleep(3600)


def _run_inline_editor(
    file_path: Path,
    display_name: str,
    *,
    save_callback: Callable[[str], None] | None = None,
) -> int:
    """Run the inline Textual editor until Escape saves and exits."""
    app = EditorApp(file_path=file_path, display_name=display_name, save_callback=save_callback)
    app.run()
    return 0


def main() -> None:
    """CLI entry point for the standalone viewer/editor."""
    parser = argparse.ArgumentParser(description="Standalone temporary-file viewer/editor")
    parser.add_argument("filepath", nargs="?", type=Path, help="Path to a real file")
    parser.add_argument("-v", "--view", action="store_true", help="View mode (read-only)")
    parser.add_argument("--theme", default="teleclaude-dark", help="Reserved for compatibility")
    parser.add_argument("--project-root", type=Path, help="Project root that owns the artifact database")
    parser.add_argument("--artifact-slug", help="Todo slug for DB-backed artifact editing")
    parser.add_argument("--artifact-name", help="Logical artifact name in todos.db")

    args = parser.parse_args()
    materialized: MaterializedArtifact | None = None
    exit_code = 0

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
        if args.view:
            _render_view(file_path, display_name)
            _wait_until_terminated()
        else:
            exit_code = _run_inline_editor(
                file_path,
                display_name,
                save_callback=None if materialized is None else materialized.persist,
            )
    finally:
        if materialized is not None:
            materialized.cleanup()

    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
