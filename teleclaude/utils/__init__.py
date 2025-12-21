"""Utility functions for TeleClaude."""

import asyncio
import os
import re
import time
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Awaitable, Callable, ParamSpec, TypeVar

from instrukt_ai_logging import get_logger

T = TypeVar("T")
P = ParamSpec("P")
logger = get_logger(__name__)


def command_retry(
    max_retries: int = 3, max_timeout: float = 5.0
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Decorator for retrying adapter commands with exponential backoff and max timeout.

    Handles:
    - Rate limits: Retry with suggested delay if exception provides retry_after
    - Network errors (connection issues, timeouts): Retry with exponential backoff (1s, 2s, 4s)
    - Other errors: Fail immediately
    - Max timeout: Stop retrying after total elapsed time exceeds max_timeout

    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        max_timeout: Maximum total time in seconds for all retries (default: 30.0)

    Returns:
        Decorator function
    """

    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:  # type: ignore[misc]
            start_time = time.time()
            excluded_wait_time = 0.0  # Rate-limit wait time doesn't count against timeout
            last_exception = None

            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)

                except Exception as e:
                    # Elapsed operation time (excludes rate-limit waits)
                    elapsed_time = time.time() - start_time - excluded_wait_time

                    # Check if max timeout exceeded (only counting operation time)
                    if elapsed_time >= max_timeout:
                        logger.error(
                            "Max timeout (%.1fs) exceeded after %d attempts (elapsed: %.1fs)",
                            max_timeout,
                            attempt + 1,
                            elapsed_time,
                        )
                        raise

                    # Check for rate limit (RetryAfter or similar)
                    if hasattr(e, "retry_after"):
                        if attempt < max_retries - 1:
                            retry_after = getattr(e, "retry_after")  # type: ignore[misc]
                            logger.warning(
                                "%s: Rate limited, retrying in %ss (attempt %d/%d)",
                                func.__name__,
                                retry_after,  # type: ignore[misc]
                                attempt + 1,
                                max_retries,
                            )
                            await asyncio.sleep(retry_after)  # type: ignore[misc]
                            excluded_wait_time += retry_after  # type: ignore[misc]  # Don't count wait against timeout
                            last_exception = e
                        else:
                            logger.error(
                                "%s: Rate limit exceeded after %d attempts",
                                func.__name__,
                                max_retries,
                            )
                            raise

                    # Check for network errors
                    elif type(e).__name__ in (
                        "NetworkError",
                        "TimedOut",
                        "ConnectionError",
                        "TimeoutError",
                    ):
                        if attempt < max_retries - 1:
                            delay = 2**attempt  # type: ignore[misc]  # 1s, 2s, 4s
                            logger.warning(
                                "Network error (%s), retrying in %ds (attempt %d/%d)",
                                type(e).__name__,
                                delay,  # type: ignore[misc]
                                attempt + 1,
                                max_retries,
                            )
                            await asyncio.sleep(delay)  # type: ignore[misc]
                            last_exception = e
                        else:
                            logger.error("Network error after %d attempts: %s", max_retries, e)
                            raise

                    # Other errors - fail immediately, don't retry
                    else:
                        logger.debug("Non-retryable error in %s: %s", func.__name__, e)
                        raise

            # Should never reach here, but just in case
            if last_exception:
                raise last_exception
            raise RuntimeError(f"Retry logic failed unexpectedly in {func.__name__}")

        return wrapper  # type: ignore[misc]

    return decorator


def expand_env_vars(config: object) -> object:
    """Recursively expand environment variables in config.

    Replaces ${VAR} patterns with environment variable values.

    Args:
        config: Configuration object (dict, list, str, or primitive)

    Returns:
        Configuration with all ${VAR} patterns replaced
    """
    if isinstance(config, dict):
        return {k: expand_env_vars(v) for k, v in config.items()}  # type: ignore[misc]
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
    status_color: str,
    started_time: str,
    last_active_time: str,
    size_str: str,
    is_truncated: bool,
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
        f"active: {last_active_time}",
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


def apply_code_block_formatting(text: str, metadata: dict[str, object]) -> str:
    """Apply code block formatting unless already formatted.

    Args:
        text: Text to format
        metadata: Message metadata (checks for raw_format flag)

    Returns:
        Formatted text (wrapped in backticks if not raw_format)
    """
    if metadata.get("raw_format"):
        # Already formatted, return as-is
        return text
    # Wrap in code block
    return f"```\n{text}\n```" if text.strip() else text


def strip_ansi_codes(text: str) -> str:
    """Strip ANSI escape codes from text.

    Args:
        text: Text with ANSI escape codes

    Returns:
        Text with ANSI codes removed
    """
    # Pattern matches:
    # - CSI sequences: ESC [ ... (m, H, J, etc.)
    # - OSC sequences: ESC ] ... (BEL or ST)
    # - Simple escape sequences: ESC (single char)
    ansi_pattern = re.compile(
        r"\x1b"  # ESC
        r"(?:"  # Start non-capturing group
        r"\[[0-9;]*[a-zA-Z]"  # CSI sequences (ESC[...m, ESC[...H, etc.)
        r"|"
        r"\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC sequences (ESC]...BEL or ESC]...ST)
        r"|"
        r"[=>]"  # Simple sequences (ESC=, ESC>)
        r")"
    )
    return ansi_pattern.sub("", text)


def strip_exit_markers(text: str) -> str:
    """Strip exit code markers from text.

    Removes:
    1. Old format marker output (__EXIT__0__, __EXIT__1__, etc.)
    2. New format marker output with hash (__EXIT__a1b2c3d4__0__, etc.)
    3. The echo command from shell prompts (; echo "__EXIT__$?__" or ; echo "__EXIT__{hash}__$?__")

    Args:
        text: Text with exit markers

    Returns:
        Text with markers removed
    """
    # Strip new format marker (__EXIT__{marker_id}__\d+__)
    # marker_id is an alphanumeric string (usually 8-char hex from MD5, but can vary)
    text = re.sub(r"__EXIT__[a-zA-Z0-9]+__\s*\d+\s*__\n?", "", text)

    # Strip old format marker (__EXIT__0__, __EXIT__1__, etc.)
    # Allow whitespace/newlines within marker due to tmux line wrapping
    text = re.sub(r"__EXIT__\s*\d+\s*__\n?", "", text)

    # Strip the echo command - handles line wrapping
    # Pattern 1: new format with marker_id ; echo "__EXIT__{id}__$?__"
    text = re.sub(r';\s*\n?\s*echo\s+"__EXIT__[a-zA-Z0-9]+__\s*\$\?\s*__"', "", text)

    # Pattern 2: old format ; echo "__EXIT__$?__"
    text = re.sub(r';\s*\n?\s*echo\s+"__EXIT__\s*\$\?\s*__"', "", text)

    # Pattern 3: echo at start of line (with or without leading whitespace) - new format
    text = re.sub(
        r'^\s*echo\s+"__EXIT__[a-zA-Z0-9]+__\s*\$\?\s*__"\s*\n?',
        "",
        text,
        flags=re.MULTILINE,
    )

    # Pattern 4: echo at start of line (with or without leading whitespace) - old format
    text = re.sub(r'^\s*echo\s+"__EXIT__\s*\$\?\s*__"\s*\n?', "", text, flags=re.MULTILINE)

    # Pattern 5: multiline wrapped - newline INSIDE the echo string (e.g., ; echo "__\nEXIT__...")
    text = re.sub(r';\s*echo\s+"__\s*\n\s*EXIT__[a-zA-Z0-9]+__\s*\$\?\s*__"', "", text)
    text = re.sub(r';\s*echo\s+"__\s*\n\s*EXIT__\s*\$\?\s*__"', "", text)

    # Strip Claude Code hook success messages (including wrapped continuation lines)
    # Matches lines starting with "  ⎿ " and continuation lines indented with 5+ spaces
    text = re.sub(r"^  ⎿ .*(?:\n {5,}.*)*\n?", "", text, flags=re.MULTILINE)

    return text


def get_filtered_output(output_file: Path, max_len: int) -> tuple[str, bool]:
    """Get filtered output from raw file (strips ANSI codes and exit markers).

    Args:
        output_file: Path to raw output file
        max_len: Maximum length to return (gets last N chars)

    Returns:
        Tuple of (filtered_output, is_truncated)
    """
    if not output_file.exists():
        return ("", False)

    try:
        raw_output = output_file.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("Failed to read output file %s: %s", output_file, e)
        return ("", False)

    # Strip ANSI codes and exit markers
    filtered = strip_ansi_codes(raw_output)
    filtered = strip_exit_markers(filtered)

    # Truncate to last N chars
    is_truncated = len(filtered) > max_len
    if is_truncated:
        filtered = filtered[-max_len:]

    return (filtered, is_truncated)
