"""Utility functions for session management.

This module provides shared utilities for session creation and management
to avoid code duplication across command handlers and MCP server.
"""

import os
import re
from pathlib import Path
from typing import Iterable, Optional

from teleclaude.core.db import db

# Session workspace directory (workspace/{session_id}/)
OUTPUT_DIR = Path("workspace")


def unique_title(base_title: str, existing_titles: set[str]) -> str:
    """Return a unique title by appending a counter if needed."""
    if base_title not in existing_titles:
        return base_title

    counter = 2
    while f"{base_title} ({counter})" in existing_titles:
        counter += 1
    return f"{base_title} ({counter})"


async def ensure_unique_title(base_title: str) -> str:
    """Ensure session title is unique by appending counter if needed.

    Checks all active sessions for duplicate titles.
    If the base_title exists, appends " (2)", " (3)", etc. until unique.

    Args:
        base_title: The desired session title (e.g., "$MozBook > $RasPi[apps/TeleClaude] - AI Session")

    Returns:
        Unique title (base_title or base_title with counter appended)

    Examples:
        >>> await ensure_unique_title("$MozBook[apps/TC] - Untitled")
        "$MozBook[apps/TC] - Untitled"

        >>> # If above title exists:
        >>> await ensure_unique_title("$MozBook[apps/TC] - Untitled")
        "$MozBook[apps/TC] - Untitled (2)"
    """
    # Get all active sessions
    existing_sessions = await db.list_sessions()
    existing_titles = {s.title for s in existing_sessions}
    return unique_title(base_title, existing_titles)


def get_session_output_dir(session_id: str) -> Path:
    """Get workspace directory for a session.

    Creates workspace/{session_id} directory if it doesn't exist.
    This directory stores all session-related files:
    - tmux.txt: Tmux output
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
    Output file stores RAW tmux output for:
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
    include_computer: bool = True,
) -> str:
    """Build the computer prefix portion of a session title.

    Format:
    - Agent known + include_computer: "{Agent}-{mode}@{Computer}" (e.g., "Claude-slow@MozMini")
    - Agent known + no computer: "{Agent}-{mode}" (e.g., "Gemini-fast")
    - Agent unknown: "${Computer}" (e.g., "$MozMini")

    Args:
        computer_name: Name of the computer (e.g., "MozMini")
        agent_name: Name of the agent if known (e.g., "Claude", "Gemini")
        thinking_mode: Thinking mode if known (e.g., "slow", "med", "fast")
        include_computer: Whether to include @Computer suffix (default True)

    Returns:
        Formatted prefix string
    """
    if agent_name and thinking_mode:
        agent_display = agent_name.capitalize()
        if include_computer:
            return f"{agent_display}-{thinking_mode}@{computer_name}"
        return f"{agent_display}-{thinking_mode}"
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
    - Human session: "{project}: {prefix} - {description}"
    - AI-to-AI session: "{project}: {initiator} > {target} - {description}"

    Where prefix is either "${Computer}" (agent unknown) or "{Agent}-{mode}@{Computer}" (agent known).
    For AI-to-AI, if initiator and target are same computer, target drops @Computer suffix.

    Args:
        computer_name: Target computer name
        short_project: Short project name (e.g., "TeleClaude", "TeleClaude/fix-bug")
        description: Session description (e.g., "Untitled", "Debug auth flow")
        initiator_computer: Initiator computer for AI-to-AI sessions (None for human sessions)
        agent_name: Target agent name if known
        thinking_mode: Target thinking mode if known
        initiator_agent: Initiator agent name if known (AI-to-AI only)
        initiator_mode: Initiator thinking mode if known (AI-to-AI only)

    Returns:
        Formatted session title
    """
    if initiator_computer:
        # AI-to-AI session - drop target @Computer if same as initiator
        same_computer = initiator_computer == computer_name
        initiator_prefix = build_computer_prefix(initiator_computer, initiator_agent, initiator_mode)
        target_prefix = build_computer_prefix(
            computer_name, agent_name, thinking_mode, include_computer=not same_computer
        )
        return f"{short_project}: {initiator_prefix} > {target_prefix} - {description}"

    # Human session
    target_prefix = build_computer_prefix(computer_name, agent_name, thinking_mode)
    return f"{short_project}: {target_prefix} - {description}"


def get_short_project_name(project_path: str | None, subdir: str | None) -> str:
    """Extract short project name from project_path + subdir."""
    base = project_path.rstrip("/") if project_path else ""
    if not base:
        return "unknown"
    root_name = base.split("/")[-1] if base else "unknown"
    if subdir:
        slug = subdir.split("/")[-1] if subdir else ""
        return f"{root_name}/{slug}" if slug else root_name
    return root_name


def resolve_working_dir(project_path: str | None, subdir: str | None) -> str:
    """Resolve actual working directory from project_path and subdir."""
    if not project_path:
        raise ValueError("project_path is required to resolve working directory")
    if subdir and Path(subdir).is_absolute():
        raise ValueError(f"subdir must be relative: {subdir}")
    base = os.path.expanduser(os.path.expandvars(str(project_path)))
    return str(Path(base) / subdir) if subdir else str(Path(base))


def split_project_path_and_subdir(
    target_dir: str,
    trusted_roots: Iterable[str],
) -> tuple[str, str | None]:
    """Split a working directory into project_path + subdir using trusted roots."""
    resolved_target = Path(os.path.expanduser(os.path.expandvars(target_dir))).resolve()
    best_root: Path | None = None

    for root in trusted_roots:
        root_path = Path(os.path.expanduser(os.path.expandvars(root))).resolve()
        if resolved_target == root_path or root_path in resolved_target.parents:
            if best_root is None or len(str(root_path)) > len(str(best_root)):
                best_root = root_path

    if best_root is None:
        return str(resolved_target), None

    rel = resolved_target.relative_to(best_root)
    subdir = str(rel) if str(rel) != "." else None
    return str(best_root), subdir


# Regex patterns for parsing session titles
# Format: "{project}: {prefix} - {description}" or "{project}: {init} > {target} - {description}"
# Prefix matches: "$Computer" or "Agent-mode@Computer" or "Agent-mode"
_AGENT_PREFIX = r"(?:\$\w+|\w+-\w+(?:@\w+)?)"
_TITLE_PATTERN = re.compile(rf"^([^:]+:\s*{_AGENT_PREFIX}(?:\s*>\s*{_AGENT_PREFIX})?\s*-\s*)(.*)$")


def parse_session_title(title: str) -> tuple[Optional[str], Optional[str]]:
    """Parse a session title into prefix and description.

    Format: "{project}: {prefix} - {description}"
    AI-to-AI: "{project}: {initiator} > {target} - {description}"

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

    Replaces "${Computer} - " with "{Agent}-{mode}@{Computer} - " in the title.
    The target computer is always followed by " - " (before the description).

    For AI-to-AI sessions on the same computer, drops @Computer from target
    to avoid redundancy (initiator already shows @Computer).

    Format: "{project}: {prefix} - {description}"
    AI-to-AI: "{project}: {initiator} > {target} - {description}"

    Args:
        title: Current session title
        agent_name: Agent name (e.g., "claude", "gemini")
        thinking_mode: Thinking mode (e.g., "slow", "med", "fast")
        computer_name: Computer name to match in title

    Returns:
        Updated title with agent info, or None if title format doesn't match
    """
    # Match "$Computer - " to ensure we replace the TARGET prefix (before description),
    # not the initiator prefix in AI-to-AI titles like "Project: $Init > $Target - desc"
    old_pattern = f"${computer_name} - "

    # Check if initiator is same computer (AI-to-AI same-computer case)
    # Initiator patterns: "$Computer >" or "Agent-mode@Computer >"
    same_computer = f"${computer_name} >" in title or f"@{computer_name} >" in title

    new_pattern = (
        f"{build_computer_prefix(computer_name, agent_name, thinking_mode, include_computer=not same_computer)} - "
    )

    if old_pattern in title:
        return title.replace(old_pattern, new_pattern, 1)

    return None
