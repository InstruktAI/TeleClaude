"""Best-effort file logging primitives.

Logging must never crash hooks/scripts, so all functions here are best-effort and swallow exceptions.
"""

from __future__ import annotations

from pathlib import Path

from utils.rotating_log import rotate_if_needed


def append_line(
    log_path: str | Path,
    line: str,
    *,
    max_bytes: int = 1_000_000,
    backup_count: int = 5,
    encoding: str = "utf-8",
) -> None:
    """Append one line to `log_path`, rotating when it would exceed `max_bytes`."""
    try:
        path = Path(log_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)

        line_to_write = line if line.endswith("\n") else f"{line}\n"
        upcoming_bytes = len(line_to_write.encode(encoding))
        rotate_if_needed(
            path,
            max_bytes=max_bytes,
            backup_count=backup_count,
            upcoming_bytes=upcoming_bytes,
        )
        with open(path, "a", encoding=encoding) as f:
            f.write(line_to_write)
    except Exception:
        pass
