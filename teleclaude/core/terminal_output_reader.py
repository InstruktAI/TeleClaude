"""Terminal output reader for TTY/TUI streams."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pyte
from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


@dataclass
class TerminalScreen:
    """VT/ANSI screen renderer using pyte."""

    columns: int
    rows: int

    def __post_init__(self) -> None:
        self._screen = pyte.Screen(self.columns, self.rows)
        self._stream = pyte.Stream(self._screen)

    def feed(self, data: str) -> None:
        self._stream.feed(data)

    def render(self) -> str:
        lines = [line.rstrip() for line in self._screen.display]
        return "\n".join(lines).rstrip()


def parse_terminal_size(value: Optional[str]) -> tuple[int, int]:
    if value and "x" in value:
        try:
            cols_str, rows_str = value.split("x", 1)
            cols = int(cols_str)
            rows = int(rows_str)
            if cols > 0 and rows > 0:
                return cols, rows
        except ValueError:
            pass
    return 80, 24


class TerminalOutputReader:
    """Incrementally renders terminal output from a raw log file."""

    def __init__(self, log_file: Path, columns: int, rows: int) -> None:
        self._log_file = log_file
        self._screen = TerminalScreen(columns, rows)
        self._offset = 0
        self._last_output = ""

    def read(self) -> Optional[str]:
        if not self._log_file.exists():
            return None

        try:
            with open(self._log_file, "r", encoding="utf-8", errors="ignore") as handle:
                handle.seek(self._offset)
                chunk = handle.read()
                self._offset = handle.tell()
        except Exception as exc:
            logger.warning("Failed reading TUI log %s: %s", self._log_file, exc)
            return None

        if not chunk:
            return None

        self._screen.feed(chunk)
        rendered = self._screen.render()
        if rendered == self._last_output:
            return None

        self._last_output = rendered
        return rendered

    @property
    def last_output(self) -> str:
        return self._last_output
