"""Snapshot test helpers."""

from __future__ import annotations

import difflib
import os
from pathlib import Path

SNAPSHOT_ROOT = Path(__file__).resolve().parent / "snapshots"


def normalize_lines(lines: list[str]) -> str:
    """Normalize rendered lines for snapshot comparison."""
    return "\n".join(lines).rstrip() + "\n"


def assert_snapshot(content: str, snapshot_path: Path) -> None:
    """Assert snapshot content matches expected file.

    Set UPDATE_SNAPSHOTS=1 to (re)write snapshots.
    """
    update = os.environ.get("UPDATE_SNAPSHOTS") == "1"
    if update:
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(content, encoding="utf-8")
        return

    if not snapshot_path.exists():
        raise AssertionError(f"Missing snapshot: {snapshot_path}. Run UPDATE_SNAPSHOTS=1 pytest <test> to create it.")

    expected = snapshot_path.read_text(encoding="utf-8")
    if content == expected:
        return

    diff = "\n".join(
        difflib.unified_diff(
            expected.splitlines(),
            content.splitlines(),
            fromfile="expected",
            tofile="actual",
            lineterm="",
        )
    )
    raise AssertionError(f"Snapshot mismatch: {snapshot_path}\n{diff}")
