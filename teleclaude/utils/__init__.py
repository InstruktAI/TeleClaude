"""Utility functions for TeleClaude."""

import asyncio
import logging
import os
import re
import time
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Awaitable, Callable, List, ParamSpec, TypeVar

T = TypeVar("T")
P = ParamSpec("P")
logger = logging.getLogger(__name__)


def command_retry(
    max_retries: int = 3, max_timeout: float = 30.0
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
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            start_time = time.time()
            last_exception = None

            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)

                except Exception as e:
                    elapsed_time = time.time() - start_time

                    # Check if max timeout exceeded
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
                            retry_after = getattr(e, "retry_after")
                            # Check if retry would exceed max timeout
                            if elapsed_time + retry_after >= max_timeout:
                                logger.error(
                                    "Rate limit retry (%.1fs) would exceed max timeout (%.1fs), failing",
                                    retry_after,
                                    max_timeout,
                                )
                                raise
                            logger.warning(
                                "Rate limited, retrying in %ss (attempt %d/%d)", retry_after, attempt + 1, max_retries
                            )
                            await asyncio.sleep(retry_after)
                            last_exception = e
                        else:
                            logger.error("Rate limit exceeded after %d attempts", max_retries)
                            raise

                    # Check for network errors
                    elif type(e).__name__ in ("NetworkError", "TimedOut", "ConnectionError", "TimeoutError"):
                        if attempt < max_retries - 1:
                            delay = 2**attempt  # 1s, 2s, 4s, 8s, 16s
                            # Check if retry would exceed max timeout
                            if elapsed_time + delay >= max_timeout:
                                logger.error(
                                    "Network retry (%.1fs) would exceed max timeout (%.1fs), failing",
                                    delay,
                                    max_timeout,
                                )
                                raise
                            logger.warning(
                                "Network error (%s), retrying in %ds (attempt %d/%d)",
                                type(e).__name__,
                                delay,
                                attempt + 1,
                                max_retries,
                            )
                            await asyncio.sleep(delay)
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

        return wrapper

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
    1. The marker output (__EXIT__0__, __EXIT__1__, etc.)
    2. The echo command from shell prompts (; echo "__EXIT__$?__")

    Args:
        text: Text with exit markers

    Returns:
        Text with markers removed
    """
    # Strip the marker output (__EXIT__0__, __EXIT__1__, etc.)
    # Allow whitespace/newlines within marker due to tmux line wrapping
    text = re.sub(r"__EXIT__\s*\d+\s*__\n?", "", text)

    # Strip the echo command - handles line wrapping
    # Pattern 1: ; echo (together on same line or across lines) - preserves newline before next content
    text = re.sub(r';\s*\n?\s*echo\s+"__EXIT__\s*\$\?\s*__"', "", text)

    # Pattern 2: echo at start of line (after line wrap, semicolon lost) - removes the entire line
    text = re.sub(r'^\s+echo\s+"__EXIT__\s*\$\?\s*__"\s*\n', "", text, flags=re.MULTILINE)

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
