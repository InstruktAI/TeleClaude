"""Utility functions for session management.

This module provides shared utilities for session creation and management
to avoid code duplication across command handlers and MCP server.
"""

from teleclaude.core.db import db


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
