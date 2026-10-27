"""The starts of a todo's driver that are inside this computer's admission section.

One record per (canonical project root, slug), holding the session that start is creating or
claiming. The record lives in this process only. It is written and dropped by
``driver_start_section`` (``manual_start``) and read here, below the modules that judge a claim,
so a computer can answer that a session is mid-start without importing the start lane.
"""

from __future__ import annotations

from pathlib import Path

from teleclaude.core.project_state import resolve_project_state_root as resolve_project_root

STARTS_IN_FLIGHT: dict[tuple[Path, str], str] = {}


def start_key(project_path: str | Path, slug: str) -> tuple[Path, str]:
    """Return the registry key of a todo's start: its canonical project root and slug."""
    return resolve_project_root(project_path), slug


def is_starting(project_path: str | Path, slug: str, session_id: str) -> bool:
    """Return whether a start of ``session_id`` for this todo is inside an admission section here."""
    return STARTS_IN_FLIGHT.get(start_key(project_path, slug)) == session_id
