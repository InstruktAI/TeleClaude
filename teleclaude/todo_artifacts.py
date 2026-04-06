"""Helpers for logical todo artifact names and display filenames."""

from __future__ import annotations

from pathlib import PurePosixPath


def artifact_display_filename(artifact_name: str) -> str:
    """Return a user-facing filename for a logical artifact name."""
    return artifact_name if PurePosixPath(artifact_name).suffix else f"{artifact_name}.md"
