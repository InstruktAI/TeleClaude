"""Standalone temporary-file viewer/editor for todo artifacts.

This command is launched in a tmux pane by the preparation view.

- View mode prints the current file contents immediately and stays alive until
  tmux respawns or closes the pane.
- Edit mode opens a real terminal editor on the target file. For DB-backed
  artifacts, content is materialized into a temporary file before editing and
  persisted back into todos.db when the editor exits successfully.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

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


def _default_editor_command() -> list[str]:
    """Choose a real terminal editor without depending on Textual startup."""
    env_editor = os.environ.get("TELECLAUDE_EDITOR_COMMAND") or os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if env_editor:
        return shlex.split(env_editor)
    for candidate in ("nvim", "vim", "nano", "vi"):
        path = shutil.which(candidate)
        if path:
            return [path]
    raise RuntimeError("No terminal editor found. Set TELECLAUDE_EDITOR_COMMAND or EDITOR.")


def _run_editor(file_path: Path) -> int:
    """Open the file in the configured terminal editor and return its exit code."""
    command = [*_default_editor_command(), str(file_path)]
    result = subprocess.run(command, check=False)
    return int(result.returncode)


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
            exit_code = _run_editor(file_path)
            if exit_code == 0 and materialized is not None:
                materialized.persist(file_path.read_text(encoding="utf-8"))
    finally:
        if materialized is not None:
            materialized.cleanup()

    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
