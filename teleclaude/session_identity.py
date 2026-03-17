"""Unified session identity resolution via the file-based marker contract."""

from __future__ import annotations

import os
from pathlib import Path


def get_session_id() -> str | None:
    """Current TeleClaude session ID from the session marker file.

    All sessions (tmux and headless) get a session-scoped TMPDIR with a
    marker file written at bootstrap by the daemon. This is the single
    source of truth for "which session am I in?"
    """
    tmpdir = os.environ.get("TMPDIR") or os.environ.get("TMP") or os.environ.get("TEMP")
    if not tmpdir:
        return None
    marker = Path(tmpdir) / "teleclaude_session_id"
    try:
        value = marker.read_text(encoding="utf-8").strip()
        return value or None
    except OSError:
        return None
