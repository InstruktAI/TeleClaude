"""Utility functions for TeleClaude."""

import os
import re
from datetime import datetime
from typing import Any, List


def expand_env_vars(config: Any) -> Any:
    """Recursively expand environment variables in config.

    Replaces ${VAR} patterns with environment variable values.

    Args:
        config: Configuration object (dict, list, str, or primitive)

    Returns:
        Configuration with all ${VAR} patterns replaced
    """
    if isinstance(config, dict):
        return {k: expand_env_vars(v) for k, v in config.items()}
    if isinstance(config, list):
        return [expand_env_vars(item) for item in config]
    if isinstance(config, str):

        def replace_env_var(match: re.Match[str]) -> str:
            env_var = match.group(1)
            return os.getenv(env_var, match.group(0))

        return re.sub(r"\$\{([^}]+)\}", replace_env_var, config)
    return config


def format_size(size_bytes: int) -> str:
    """Format byte size to human-readable string.

    Args:
        size_bytes: Size in bytes

    Returns:
        Human-readable size string (e.g., "1.5KB", "2.3MB")
    """
    if size_bytes < 1024:
        return f"{size_bytes}B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    return f"{size_bytes / (1024 * 1024):.1f}MB"


def format_active_status_line(
    status_color: str, started_time: str, last_active_time: str, size_str: str, is_truncated: bool
) -> str:
    """Format status line for active polling process.

    Args:
        status_color: Status emoji (🟢/🟡/🟠/🔴)
        started_time: Process start time (HH:MM:SS)
        last_active_time: Last activity time (HH:MM:SS)
        size_str: Human-readable output size
        is_truncated: Whether output is truncated

    Returns:
        Formatted status line
    """
    status_parts = [
        f"{status_color} started: {started_time}",
        f"last active: {last_active_time}",
        f"📊 {size_str}",
    ]
    if is_truncated:
        status_parts.append("(truncated)")
    return " | ".join(status_parts)


def format_completed_status_line(exit_code: int, started_timestamp: float, size_str: str, is_truncated: bool) -> str:
    """Format status line for completed process.

    Args:
        exit_code: Process exit code
        started_timestamp: Process start timestamp
        size_str: Human-readable output size
        is_truncated: Whether output is truncated

    Returns:
        Formatted status line
    """
    exit_emoji = "✅" if exit_code == 0 else "❌"
    started_time = datetime.fromtimestamp(started_timestamp).strftime("%H:%M:%S")
    completed_time = datetime.now().strftime("%H:%M:%S")
    truncation_marker = " | (truncated)" if is_truncated else ""
    return f"{exit_emoji} started: {started_time} | completed: {completed_time} | 📊 {size_str}{truncation_marker}"


def format_terminal_message(terminal_output: str, status_line: str) -> str:
    """Format terminal output with status line.

    Args:
        terminal_output: Terminal output text
        status_line: Status line text

    Returns:
        Formatted message with code block and status line
    """
    message_parts = []
    if terminal_output:
        message_parts.append(f"```\n{terminal_output}\n```")
    message_parts.append(status_line)
    return "\n".join(message_parts)
