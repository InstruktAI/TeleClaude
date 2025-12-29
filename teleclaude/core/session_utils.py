"""Utility functions for session management.

This module provides shared utilities for session creation and management
to avoid code duplication across command handlers and MCP server.
"""

import re
from pathlib import Path
from typing import Optional

from teleclaude.core.db import db

# Session workspace directory (workspace/{session_id}/)
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


def get_session_output_dir(session_id: str) -> Path:
    """Get workspace directory for a session.

    Creates workspace/{session_id} directory if it doesn't exist.
    This directory stores all session-related files:
    - tmux.txt: Terminal output
    - Subdirectories for file downloads, etc.

    Args:
        session_id: Session identifier

    Returns:
        Path to session workspace directory (workspace/{session_id}/)
    """
    session_dir = OUTPUT_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def get_output_file(session_id: str) -> Path:
    """Get output file for a session, creating it if needed.

    Creates workspace/{session_id} directory and tmux.txt file if they don't exist.
    Output file stores RAW terminal output for:
    1. Delta calculation (ignore old scrollback noise)
    2. Download functionality
    3. Daemon restart recovery (checkpoint)

    Args:
        session_id: Session identifier

    Returns:
        Path to output file (workspace/{session_id}/tmux.txt)
    """
    output_file = get_session_output_dir(session_id) / "tmux.txt"
    output_file.touch(exist_ok=True)
    return output_file


def build_computer_prefix(
    computer_name: str,
    agent_name: Optional[str] = None,
    thinking_mode: Optional[str] = None,
) -> str:
    """Build the computer prefix portion of a session title.

    Format:
    - Agent known: "{Agent}-{mode}@{Computer}" (e.g., "Claude-slow@MozMini")
    - Agent unknown: "${Computer}" (e.g., "$MozMini")

    Args:
        computer_name: Name of the computer (e.g., "MozMini")
        agent_name: Name of the agent if known (e.g., "Claude", "Gemini")
        thinking_mode: Thinking mode if known (e.g., "slow", "med", "fast")

    Returns:
        Formatted prefix string
    """
    if agent_name and thinking_mode:
        # Capitalize agent name for display (claude -> Claude)
        agent_display = agent_name.capitalize()
        return f"{agent_display}-{thinking_mode}@{computer_name}"
    return f"${computer_name}"


def build_session_title(
    computer_name: str,
    short_project: str,
    description: str,
    initiator_computer: Optional[str] = None,
    agent_name: Optional[str] = None,
    thinking_mode: Optional[str] = None,
    initiator_agent: Optional[str] = None,
    initiator_mode: Optional[str] = None,
) -> str:
    """Build a session title following the standard format.

    Format:
    - Human session: "{prefix}[{project}] - {description}"
    - AI-to-AI session: "{initiator_prefix} > {target_prefix}[{project}] - {description}"

    Where prefix is either "${Computer}" (agent unknown) or "{Agent}-{mode}@{Computer}" (agent known).

    Args:
        computer_name: Target computer name
        short_project: Short project name (e.g., "apps/TeleClaude")
        description: Session description (e.g., "New session", "Debug auth flow")
        initiator_computer: Initiator computer for AI-to-AI sessions (None for human sessions)
        agent_name: Target agent name if known
        thinking_mode: Target thinking mode if known
        initiator_agent: Initiator agent name if known (AI-to-AI only)
        initiator_mode: Initiator thinking mode if known (AI-to-AI only)

    Returns:
        Formatted session title
    """
    target_prefix = build_computer_prefix(computer_name, agent_name, thinking_mode)

    if initiator_computer:
        # AI-to-AI session
        initiator_prefix = build_computer_prefix(initiator_computer, initiator_agent, initiator_mode)
        return f"{initiator_prefix} > {target_prefix}[{short_project}] - {description}"

    # Human session
    return f"{target_prefix}[{short_project}] - {description}"


# Regex patterns for parsing session titles
# Matches both old "$Computer" and new "Agent-mode@Computer" formats
_COMPUTER_PREFIX_PATTERN = r"(?:\$\w+|\w+-\w+@\w+)"
_TITLE_PATTERN = re.compile(
    rf"^({_COMPUTER_PREFIX_PATTERN}(?:\s*>\s*{_COMPUTER_PREFIX_PATTERN})?\[[^\]]+\]\s*-\s*)(.*)$"
)


def parse_session_title(title: str) -> tuple[Optional[str], Optional[str]]:
    """Parse a session title into prefix and description.

    Handles both formats:
    - Old: "$Computer[project] - description"
    - New: "Agent-mode@Computer[project] - description"
    - AI-to-AI: "$Initiator > $Target[project] - description"

    Args:
        title: Session title to parse

    Returns:
        Tuple of (prefix, description). Returns (None, None) if parsing fails.
    """
    match = _TITLE_PATTERN.match(title)
    if match:
        return match.group(1), match.group(2)
    return None, None


def update_title_with_agent(
    title: str,
    agent_name: str,
    thinking_mode: str,
    computer_name: str,
) -> Optional[str]:
    """Update a session title to include agent information.

    Replaces "${Computer}" prefix with "{Agent}-{mode}@{Computer}" prefix.

    Args:
        title: Current session title
        agent_name: Agent name (e.g., "claude", "gemini")
        thinking_mode: Thinking mode (e.g., "slow", "med", "fast")
        computer_name: Computer name to match in title

    Returns:
        Updated title with agent info, or None if title format doesn't match
    """
    # Pattern to match $ComputerName in the title (for target computer)
    old_prefix = f"${computer_name}"
    new_prefix = build_computer_prefix(computer_name, agent_name, thinking_mode)

    if old_prefix in title:
        return title.replace(old_prefix, new_prefix, 1)  # Only replace first occurrence (target)

    return None
