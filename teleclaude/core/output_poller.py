"""Terminal output polling - pure poller with no I/O side effects.

Polls tmux and yields output events. Daemon handles all message sending.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Optional

from teleclaude.config import config
from teleclaude.core import terminal_bridge
from teleclaude.core.db import db

logger = logging.getLogger(__name__)


@dataclass
class OutputEvent:
    """Base class for output events."""

    session_id: str


@dataclass
class OutputChanged(OutputEvent):
    """Output changed event."""

    output: str
    started_at: float
    last_changed_at: float


@dataclass
class ProcessExited(OutputEvent):
    """Process exited event."""

    exit_code: Optional[int]
    final_output: str
    started_at: float


@dataclass
class IdleDetected(OutputEvent):
    """Idle detected event."""

    idle_seconds: int


@dataclass
class DirectoryChanged(OutputEvent):
    """Directory changed event."""

    new_path: str
    old_path: str


class OutputPoller:
    """Pure poller - yields output events, no message sending.

    All dependencies (config, terminal_bridge) are imported at module level.
    """

    async def poll(
        self,
        session_id: str,
        tmux_session_name: str,
        output_file: Path,
        has_exit_marker: bool,
    ) -> AsyncIterator[OutputEvent]:
        """Poll terminal output and yield events.

        Args:
            session_id: Session ID
            tmux_session_name: tmux session name
            output_file: Path to output file
            has_exit_marker: Whether exit marker was appended

        Yields:
            OutputEvent subclasses (OutputChanged, ProcessExited, IdleDetected, DirectoryChanged)
        """
        # Configuration
        idle_threshold = config.polling.idle_notification_seconds
        poll_interval = 1.0
        global_update_interval = 2  # Global update interval (seconds)
        directory_check_interval = getattr(config.polling, "directory_check_interval", 5)

        # State tracking
        output_buffer = ""  # In-memory buffer for display/comparison only
        idle_ticks = 0
        notification_sent = False
        started_at = None
        last_output_changed_at = None
        ticks_since_last_update = 0
        current_update_interval = global_update_interval  # Start with global interval
        last_directory = None
        directory_check_ticks = 0
        poll_iteration = 0
        session_existed_last_poll = True  # Watchdog: track if session existed in previous poll

        try:
            # Initial delay before first poll (1s to catch fast commands)
            await asyncio.sleep(1.0)
            started_at = time.time()
            last_output_changed_at = started_at
            logger.debug("Polling started for %s with has_exit_marker=%s", session_id[:8], has_exit_marker)

            # Poll loop - EXPLICIT EXIT CONDITIONS
            while True:
                poll_iteration += 1

                # Exit condition 1: Session died (don't log ERROR here - we check below)
                session_exists_now = await terminal_bridge.session_exists(tmux_session_name, log_missing=False)

                # WATCHDOG: Detect session disappearing between polls
                if session_existed_last_poll and not session_exists_now:
                    # Check if this was an expected closure (user closed topic)
                    session = await db.get_session(session_id)
                    if session and session.closed:
                        # Expected closure - user closed the topic
                        logger.debug(
                            "Session %s disappeared (user closed topic)",
                            tmux_session_name,
                            extra={"session_id": session_id[:8]},
                        )
                    else:
                        # Unexpected death - log as critical with diagnostics
                        age_seconds = time.time() - started_at
                        logger.critical(
                            "Session %s disappeared between polls (watchdog triggered)",
                            tmux_session_name,
                            extra={
                                "session_id": session_id[:8],
                                "age_seconds": round(age_seconds, 2),
                                "poll_iteration": poll_iteration,
                                "seconds_since_last_poll": poll_interval,
                            },
                        )

                if not session_exists_now:
                    logger.info("Process exited for %s, stopping poll", session_id[:8])
                    yield ProcessExited(
                        session_id=session_id, exit_code=None, final_output=output_buffer, started_at=started_at
                    )
                    break

                session_existed_last_poll = session_exists_now

                # Capture current output
                current_output = await terminal_bridge.capture_pane(tmux_session_name)
                if not current_output.strip():
                    # No output yet, keep polling
                    await asyncio.sleep(poll_interval)
                    continue

                # Exit condition 2: Exit code detected (STATELESS DELTA-BASED)
                # Calculate delta by comparing tmux output with cumulative file history
                # File accumulates ENTIRE session, never truncates

                # Read accumulated history from file (source of truth)
                accumulated = ""
                if output_file.exists():
                    try:
                        accumulated = output_file.read_text(encoding="utf-8")
                    except Exception as e:
                        logger.warning("Failed to read output file: %s", e)

                # Calculate delta between tmux view and accumulated history
                delta_raw = ""
                if current_output.startswith(accumulated):
                    # Fast path: tmux has all our history + new content
                    delta_raw = current_output[len(accumulated) :]
                else:
                    # Tmux scrollback truncated: find overlap to determine delta
                    # Try to find where current output continues from accumulated history
                    overlap_len = 0

                    # Try progressively smaller chunks of current's beginning
                    for chunk_size in [1000, 500, 100, 50]:
                        if len(current_output) < chunk_size:
                            continue
                        chunk = current_output[:chunk_size]
                        pos = accumulated.find(chunk)
                        if pos >= 0:
                            # Found where current continues from accumulated
                            overlap_len = len(accumulated) - pos
                            logger.debug(
                                "Found overlap at pos %d for %s (overlap_len=%d)",
                                pos,
                                session_id[:8],
                                overlap_len,
                            )
                            break

                    # Delta is everything after the overlap point
                    delta_raw = current_output[overlap_len:]

                    if overlap_len == 0:
                        logger.debug("Full reset (clear or major truncation) for %s", session_id[:8])

                # Always check delta for exit code (unconditional)
                exit_code = self._extract_exit_code(delta_raw, has_exit_marker)

                # Append delta to file (cumulative history, never overwrites)
                if delta_raw:
                    try:
                        with open(output_file, "a", encoding="utf-8") as f:
                            f.write(delta_raw)
                    except Exception as e:
                        logger.warning("Failed to append to output file: %s", e)

                    # Update output_buffer with full accumulated content (for UI display)
                    output_buffer = accumulated + delta_raw
                    idle_ticks = 0
                    notification_sent = False
                    last_output_changed_at = time.time()
                    current_update_interval = global_update_interval

                    # Send OutputChanged immediately when delta appears (responsive UI)
                    if exit_code is None:
                        yield OutputChanged(
                            session_id=session_id,
                            output=delta_raw,  # RAW delta (daemon will filter)
                            started_at=started_at,
                            last_changed_at=last_output_changed_at,
                        )
                        # Reset tick counter since we just sent an update
                        ticks_since_last_update = 0
                elif not output_buffer and accumulated:
                    # First poll with existing file but no new delta - initialize buffer
                    output_buffer = accumulated

                if exit_code is not None:
                    # Exit detected - yield ProcessExited with full accumulated output
                    logger.info("Exit code %d detected for %s", exit_code, session_id[:8])

                    # Read full accumulated history for final output
                    final_accumulated = ""
                    if output_file.exists():
                        try:
                            final_accumulated = output_file.read_text(encoding="utf-8")
                        except Exception as e:
                            logger.warning("Failed to read final output: %s", e)

                    # Yield RAW accumulated output (daemon will filter)
                    yield ProcessExited(
                        session_id=session_id,
                        exit_code=exit_code,
                        final_output=final_accumulated,
                        started_at=started_at,
                    )
                    break

                # Increment tick counter
                ticks_since_last_update += 1

                # Send updates based on time interval only (enforce minimum 2s between updates)
                # This prevents Telegram API rate limiting from excessive message edits
                if output_buffer and ticks_since_last_update >= current_update_interval:
                    yield OutputChanged(
                        session_id=session_id,
                        output=output_buffer,  # RAW buffer (daemon will filter)
                        started_at=started_at,
                        last_changed_at=last_output_changed_at,
                    )

                    # Reset tick counter
                    ticks_since_last_update = 0

                    # Apply exponential backoff when idle: 2s -> 4s -> 6s -> 8s -> 10s
                    if idle_ticks >= current_update_interval:
                        current_update_interval = min(current_update_interval + 2, 10)
                        logger.debug(
                            "No activity for %ds, increasing update interval to %ds for %s",
                            idle_ticks,
                            current_update_interval,
                            session_id[:8],
                        )

                # Increment idle counter when no new content
                if not delta_raw:
                    idle_ticks += 1

                    # Send idle notification once at threshold
                    if idle_ticks == idle_threshold and not notification_sent:
                        logger.info("No output change for %ds for %s, notifying user", idle_threshold, session_id[:8])
                        yield IdleDetected(session_id=session_id, idle_seconds=idle_threshold)
                        notification_sent = True

                # Check for directory changes (if enabled)
                if directory_check_interval > 0:
                    directory_check_ticks += 1
                    if directory_check_ticks >= directory_check_interval:
                        directory_check_ticks = 0
                        current_directory = await terminal_bridge.get_current_directory(tmux_session_name)
                        if current_directory and current_directory != last_directory:
                            if last_directory is not None:
                                logger.info(
                                    "Directory changed for %s: %s -> %s",
                                    session_id[:8],
                                    last_directory,
                                    current_directory,
                                )
                                yield DirectoryChanged(
                                    session_id=session_id,
                                    new_path=current_directory,
                                    old_path=last_directory,
                                )
                            last_directory = current_directory

                await asyncio.sleep(poll_interval)

        finally:
            logger.debug("Polling ended for session %s", session_id[:8])

    def _strip_claude_code_hooks(self, output: str) -> str:
        """Strip Claude Code hook messages from output.

        Removes:
        1. Hook success prefix lines: ⎿ <hook_name> hook succeeded:
        2. <system-reminder>...</system-reminder> blocks (can be multiline, NOT nested)

        Examples of patterns removed:
        - "⎿ UserPromptSubmit hook succeeded: <system-reminder>...</system-reminder>"
        - "⎿  SessionStart:startup hook succeeded: ..."

        Args:
            output: Terminal output

        Returns:
            Output with Claude Code hook messages removed
        """
        original_length = len(output)

        # Strip hook success prefix lines (⎿ ... hook succeeded: ...)
        output = re.sub(r"⎿[^\n]*hook succeeded:[^\n]*\n?", "", output)

        # Check if output contains system-reminder tags
        has_system_reminder = "<system-reminder>" in output or "</system-reminder>" in output
        if has_system_reminder:
            logger.info("Found system-reminder tags in output (length: %d)", original_length)

        # Strip <system-reminder> blocks
        # Use [\s\S] instead of . to explicitly match ANY character including newlines
        output = re.sub(r"<system-reminder>[\s\S]*?</system-reminder>\s*\n?", "", output)

        # Strip orphaned closing tags and their preceding content
        # Look for patterns that indicate system-reminder content before the closing tag
        before_orphan = output

        # Also remove standalone closing tags
        output = re.sub(r"[^\n]*</system-reminder>\s*\n?", "", output)

        if output != before_orphan:
            logger.info("Removed orphaned </system-reminder> tag and associated content")

        filtered_length = len(output)
        if filtered_length < original_length:
            logger.info(
                "Filtered Claude Code hooks: %d -> %d bytes (%d bytes removed)",
                original_length,
                filtered_length,
                original_length - filtered_length,
            )

        return output

    def _strip_exit_markers(self, output: str) -> str:
        """Strip exit code markers from RAW output (for exit code detection).

        This is ONLY used for extracting exit codes from raw tmux output.
        UI filtering happens in daemon layer.

        Removes:
        1. The __EXIT__N__ marker output
        2. The ; echo "__EXIT__$?__" command text from shell prompts

        Args:
            output: RAW terminal output

        Returns:
            Output with exit markers removed (still contains ANSI codes)
        """
        # Strip the marker output (__EXIT__0__, __EXIT__1__, etc.)
        # Allow whitespace/newlines within marker due to tmux line wrapping
        # Remove marker + ONE trailing newline (preserves line structure)
        # Handles: __EXIT__0__, __EXIT__0\n__, __EXIT__\n0__, etc.
        output = re.sub(r"__EXIT__\s*\d+\s*__\n?", "", output)

        # Strip the echo command from shell prompts (handles line wrapping)
        # Allow whitespace/newlines within the quoted string and between command parts
        # Handles: ; echo "__EXIT__$?__", ; echo "__EXIT__$?\n__", etc.
        output = re.sub(r';\s*echo\s*"__EXIT__\s*\$\?\s*__\s*"', "", output)

        return output

    def _extract_exit_code(self, output: str, has_exit_marker: bool) -> Optional[int]:
        """Extract exit code from output if marker present.

        Args:
            output: Terminal output
            has_exit_marker: Whether exit marker was appended

        Returns:
            Exit code or None
        """
        if not has_exit_marker:
            return None

        # Search last 5 NON-EMPTY lines for exit marker
        # Only check recent lines to avoid detecting old markers from previous commands
        # Fresh exit markers appear near the end after command completes
        # Case 1 - Normal exit:
        #   ...
        #   __EXIT__0__
        #   (many empty lines)
        # Case 2 - After Ctrl+C:
        #   ...
        #   __EXIT__130__
        #   ➜  teleclaude git:(main) ✗
        #   (many empty lines)
        lines = output.splitlines()
        if not lines:
            return None

        # Get last 5 non-empty lines (recent output only)
        non_empty_lines = [line for line in lines if line.strip()]
        if not non_empty_lines:
            return None

        # Check last 5 non-empty lines for exit marker
        last_n = non_empty_lines[-5:] if len(non_empty_lines) >= 5 else non_empty_lines

        for line in last_n:
            # Strict pattern: marker must be on its own line (with optional whitespace)
            # This prevents matching the marker in typed command text or shell syntax
            # Valid: "   __EXIT__0__   " or "__EXIT__130__"
            # Invalid: "echo "__EXIT__$?__"" or "; echo "__EXIT__$?__""
            match = re.search(r"^\s*__EXIT__(\d+)__\s*$", line)
            if match:
                return int(match.group(1))

        return None
