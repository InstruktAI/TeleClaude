"""Best-effort log rotation utilities (max size in bytes).

This project writes several plain-text log files.
To avoid unbounded growth, callers should invoke `rotate_if_needed()` before
appending new data.
"""

from __future__ import annotations

import os
from pathlib import Path


def rotate_if_needed(
    log_path: str | Path,
    *,
    max_bytes: int = 1_000_000,
    backup_count: int = 5,
    upcoming_bytes: int = 0,
) -> None:
    """Rotate `log_path` when it would exceed `max_bytes`.

    Rotation scheme:
      - `file.log` -> `file.log.1`
      - `file.log.1` -> `file.log.2` ... up to `backup_count`

    Best-effort: failures are swallowed because logging must never crash hooks.
    """
    try:
        path = Path(log_path).expanduser()
        if max_bytes <= 0 or backup_count <= 0:
            return
        if not path.exists():
            return

        current_size = path.stat().st_size
        if current_size + max(0, upcoming_bytes) < max_bytes:
            return

        # Shift backups: .(backup_count-1) -> .backup_count
        for i in range(backup_count - 1, 0, -1):
            src = path.with_name(f"{path.name}.{i}")
            dst = path.with_name(f"{path.name}.{i + 1}")
            if src.exists():
                os.replace(src, dst)

        os.replace(path, path.with_name(f"{path.name}.1"))
    except Exception:
        return
