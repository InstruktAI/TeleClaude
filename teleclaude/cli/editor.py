"""Standalone temporary-file viewer/editor for todo artifacts.

This command is launched in a tmux pane by the preparation view.

- View mode prints the current file contents immediately and stays alive until
  tmux respawns or closes the pane.
- Edit mode runs a lightweight inline curses editor. Escape saves if changed
  and exits. For DB-backed artifacts, content is materialized into a temporary
  file before editing and persisted back into todos.db on save/exit.
"""

from __future__ import annotations

import argparse
import os
import select
import shutil
import signal
import sys
import tempfile
import termios
import time
import tty
from collections.abc import Callable
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


@dataclass
class InlineEditorSession:
    """Stateful inline editor model with save-on-escape semantics."""

    file_path: Path
    display_name: str
    save_callback: Callable[[str], None] | None = None

    def __post_init__(self) -> None:
        initial_content = self.file_path.read_text(encoding="utf-8")
        self.lines = initial_content.split("\n")
        self.cursor_row = 0
        self.cursor_col = 0
        self.top_line = 0
        self.col_offset = 0
        self.status = "Esc save+close  Ctrl+S save"
        self._last_saved_content = initial_content

    lines: list[str] = None  # type: ignore[assignment]
    cursor_row: int = 0
    cursor_col: int = 0
    top_line: int = 0
    col_offset: int = 0
    status: str = ""
    _last_saved_content: str = ""

    def current_text(self) -> str:
        """Return the current buffer text."""
        return "\n".join(self.lines)

    def save_if_changed(self) -> bool:
        """Persist only when the content differs from the last saved state."""
        content = self.current_text()
        if content == self._last_saved_content:
            self.status = "No changes"
            return False
        self.file_path.write_text(content, encoding="utf-8")
        if self.save_callback is not None:
            self.save_callback(content)
        self._last_saved_content = content
        self.status = "Saved"
        return True

    def ensure_visible(self, height: int, width: int) -> None:
        """Adjust viewport offsets so the cursor stays on-screen."""
        if self.cursor_row < self.top_line:
            self.top_line = self.cursor_row
        elif self.cursor_row >= self.top_line + height:
            self.top_line = self.cursor_row - height + 1

        if self.cursor_col < self.col_offset:
            self.col_offset = self.cursor_col
        elif self.cursor_col >= self.col_offset + width:
            self.col_offset = self.cursor_col - width + 1

        self.top_line = max(0, self.top_line)
        self.col_offset = max(0, self.col_offset)

    def move_left(self) -> None:
        if self.cursor_col > 0:
            self.cursor_col -= 1
        elif self.cursor_row > 0:
            self.cursor_row -= 1
            self.cursor_col = len(self.lines[self.cursor_row])

    def move_right(self) -> None:
        line = self.lines[self.cursor_row]
        if self.cursor_col < len(line):
            self.cursor_col += 1
        elif self.cursor_row < len(self.lines) - 1:
            self.cursor_row += 1
            self.cursor_col = 0

    def move_up(self) -> None:
        if self.cursor_row > 0:
            self.cursor_row -= 1
            self.cursor_col = min(self.cursor_col, len(self.lines[self.cursor_row]))

    def move_down(self) -> None:
        if self.cursor_row < len(self.lines) - 1:
            self.cursor_row += 1
            self.cursor_col = min(self.cursor_col, len(self.lines[self.cursor_row]))

    def insert_text(self, text: str) -> None:
        line = self.lines[self.cursor_row]
        self.lines[self.cursor_row] = line[: self.cursor_col] + text + line[self.cursor_col :]
        self.cursor_col += len(text)

    def insert_newline(self) -> None:
        line = self.lines[self.cursor_row]
        left = line[: self.cursor_col]
        right = line[self.cursor_col :]
        self.lines[self.cursor_row] = left
        self.lines.insert(self.cursor_row + 1, right)
        self.cursor_row += 1
        self.cursor_col = 0

    def backspace(self) -> None:
        if self.cursor_col > 0:
            line = self.lines[self.cursor_row]
            self.lines[self.cursor_row] = line[: self.cursor_col - 1] + line[self.cursor_col :]
            self.cursor_col -= 1
            return
        if self.cursor_row == 0:
            return
        current = self.lines.pop(self.cursor_row)
        self.cursor_row -= 1
        self.cursor_col = len(self.lines[self.cursor_row])
        self.lines[self.cursor_row] += current

    def delete(self) -> None:
        line = self.lines[self.cursor_row]
        if self.cursor_col < len(line):
            self.lines[self.cursor_row] = line[: self.cursor_col] + line[self.cursor_col + 1 :]
            return
        if self.cursor_row >= len(self.lines) - 1:
            return
        self.lines[self.cursor_row] += self.lines.pop(self.cursor_row + 1)

    def handle_key(self, key: str) -> bool:
        """Apply one keystroke. Returns False when editing should end."""
        if key == "LEFT":
            self.move_left()
        elif key == "RIGHT":
            self.move_right()
        elif key == "UP":
            self.move_up()
        elif key == "DOWN":
            self.move_down()
        elif key == "HOME":
            self.cursor_col = 0
        elif key == "END":
            self.cursor_col = len(self.lines[self.cursor_row])
        elif key == "BACKSPACE":
            self.backspace()
        elif key == "DELETE":
            self.delete()
        elif key == "ENTER":
            self.insert_newline()
        elif key == "TAB":
            self.insert_text("    ")
        elif key == "CTRL_S":
            try:
                self.save_if_changed()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                self.status = f"Save failed: {exc}"
        elif key == "ESC":
            try:
                self.save_if_changed()
                return False
            except Exception as exc:  # pylint: disable=broad-exception-caught
                self.status = f"Save failed: {exc}"
        elif key:
            self.insert_text(key)
        return True

    def frame(self, height: int, width: int) -> tuple[str, int, int]:
        """Return the current screen frame and cursor position."""
        text_height = max(1, height - 2)
        text_width = max(1, width)
        self.ensure_visible(text_height, text_width)

        header = f"[EDIT] {self.display_name}"
        lines = [header[:width].ljust(width)]
        for row in range(text_height):
            line_index = self.top_line + row
            if line_index >= len(self.lines):
                lines.append("")
                continue
            visible = self.lines[line_index][self.col_offset : self.col_offset + text_width]
            lines.append(visible)
        lines.append(self.status[:width].ljust(width))

        cursor_y = 1 + self.cursor_row - self.top_line
        cursor_x = max(0, self.cursor_col - self.col_offset)
        cursor_y = min(max(1, cursor_y), height - 2)
        cursor_x = min(max(0, cursor_x), width - 1)
        return ("\x1b[2J\x1b[H" + "\n".join(lines), cursor_y, cursor_x)


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


def _terminal_size(fd: int) -> tuple[int, int]:
    """Return the current terminal size with a sane fallback."""
    try:
        size = os.get_terminal_size(fd)
        return size.lines, size.columns
    except OSError:
        return 24, 80


def _read_key(fd: int) -> str | None:
    """Read one keypress from the raw terminal."""
    first = os.read(fd, 1)
    if not first:
        return None
    if first == b"\x13":
        return "CTRL_S"
    if first in (b"\r", b"\n"):
        return "ENTER"
    if first == b"\t":
        return "TAB"
    if first in (b"\x7f", b"\x08"):
        return "BACKSPACE"
    if first != b"\x1b":
        return first.decode("utf-8", errors="ignore") or None

    sequence = b""
    while select.select([fd], [], [], 0.01)[0]:
        sequence += os.read(fd, 1)
        if sequence.endswith(b"~") or sequence in {b"[A", b"[B", b"[C", b"[D", b"[H", b"[F", b"OH", b"OF"}:
            break
    mapping = {
        b"[A": "UP",
        b"[B": "DOWN",
        b"[C": "RIGHT",
        b"[D": "LEFT",
        b"[H": "HOME",
        b"[F": "END",
        b"OH": "HOME",
        b"OF": "END",
        b"[3~": "DELETE",
    }
    if not sequence:
        return "ESC"
    return mapping.get(sequence, "ESC")


def _run_inline_editor(
    file_path: Path,
    display_name: str,
    *,
    save_callback: Callable[[str], None] | None = None,
) -> int:
    """Run the lightweight inline editor until Escape saves and exits."""
    session = InlineEditorSession(file_path=file_path, display_name=display_name, save_callback=save_callback)
    fd = sys.stdin.fileno()
    original_attrs = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        os.write(fd, b"\x1b[?25h")
        while True:
            height, width = _terminal_size(fd)
            frame, cursor_y, cursor_x = session.frame(height, width)
            os.write(fd, frame.encode("utf-8", errors="ignore"))
            os.write(fd, f"\x1b[{cursor_y + 1};{cursor_x + 1}H".encode("ascii"))
            key = _read_key(fd)
            if key is None:
                continue
            if not session.handle_key(key):
                return 0
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, original_attrs)
        os.write(fd, b"\x1b[0m\x1b[?25h")


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
