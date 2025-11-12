"""Utility functions for session management.

This module provides shared utilities for session creation and management
to avoid code duplication across command handlers and MCP server.
"""

from pathlib import Path

from teleclaude.core.db import db

# Session output directory (workspace/{session_id}/output.txt)
OUTPUT_DIR = Path("workspace")


async def ensure_unique_title(base_title: str) -> str:
    """Ensure session title is unique by appending counter if needed.

    Checks all active (non-closed) sessions for duplicate titles.
    If the base_title exists, appends " (2)", " (3)", etc. until unique.

    Args:
        base_title: The desired session title (e.g., "$MozBook > $RasPi[apps/TeleClaude] - AI Session")

    Returns:
        Unique title (base_title or base_title with counter appended)

    Examples:
        >>> await ensure_unique_title("$MozBook[apps/TC] - New session")
        "$MozBook[apps/TC] - New session"

        >>> # If above title exists:
        >>> await ensure_unique_title("$MozBook[apps/TC] - New session")
        "$MozBook[apps/TC] - New session (2)"
    """
    # Get all active sessions
    existing_sessions = await db.list_sessions(closed=False)
    existing_titles = {s.title for s in existing_sessions}

    # If title is unique, return as-is
    if base_title not in existing_titles:
        return base_title

    # Find next available counter
    counter = 2
    while f"{base_title} ({counter})" in existing_titles:
        counter += 1

    return f"{base_title} ({counter})"


def get_output_file_path(session_id: str) -> Path:
    """Get output file path for a session.

    Creates session workspace directory if it doesn't exist.
    Output file stores RAW terminal output (with exit markers) for:
    1. Delta calculation (ignore old markers in scrollback)
    2. Download functionality (markers stripped on-the-fly)
    3. Daemon restart recovery (checkpoint)

    Args:
        session_id: Session identifier

    Returns:
        Path to output file (workspace/{session_id}/output.txt)
    """
    session_workspace = OUTPUT_DIR / session_id
    session_workspace.mkdir(parents=True, exist_ok=True)
    return session_workspace / "output.txt"
