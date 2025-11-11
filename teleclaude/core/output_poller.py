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
        output_buffer = ""
        idle_ticks = 0
        notification_sent = False
        started_at = None
        last_output_changed_at = None
        ticks_since_last_update = 0
        current_update_interval = global_update_interval  # Start with global interval
        first_poll = True  # Skip exit detection on first poll (establish baseline)
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

                # Exit condition 1: Session died
                session_exists_now = await terminal_bridge.session_exists(tmux_session_name)

                # WATCHDOG: Detect session disappearing between polls
                if session_existed_last_poll and not session_exists_now:
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

                # Exit condition 2: Exit code detected
                # On first poll: establish baseline from current output
                # On subsequent polls: only check when output changes from baseline
                exit_code = None

                if first_poll and current_output.strip():
                    # First poll with output - establish baseline
                    output_buffer = current_output
                    first_poll = False
                    last_output_changed_at = time.time()
                    logger.debug("Baseline established for %s (size=%d)", session_id[:8], len(output_buffer))

                    # Send initial OutputChanged event with baseline
                    clean_output = self._strip_exit_markers(output_buffer)

                    # Write to file
                    try:
                        output_file.write_text(clean_output, encoding="utf-8")
                    except Exception as e:
                        logger.warning("Failed to write initial output file: %s", e)

                    yield OutputChanged(
                        session_id=session_id,
                        output=clean_output,
                        started_at=started_at,
                        last_changed_at=last_output_changed_at,
                    )

                    # Continue polling (don't check for exit in baseline to avoid old markers)
                    await asyncio.sleep(poll_interval)
                    continue

                elif not first_poll:
                    # Check for exit on every poll after baseline (not just when output changes)
                    # This handles fast commands where exit marker appears before first poll
                    if current_output != output_buffer:
                        # Output changed - always check for exit
                        exit_code = self._extract_exit_code(current_output, has_exit_marker)
                    elif has_exit_marker and output_buffer.strip():
                        # Output unchanged but we expect exit marker - check baseline
                        exit_code = self._extract_exit_code(output_buffer, has_exit_marker)

                if exit_code is not None:
                    # Strip markers from output (both marker and echo command)
                    current_output = self._strip_exit_markers(current_output)
                    logger.info("Exit code %d detected for %s", exit_code, session_id[:8])

                    # Write final output to file for downloads
                    try:
                        output_file.write_text(current_output, encoding="utf-8")
                    except Exception as e:
                        logger.warning("Failed to write final output file: %s", e)

                    yield ProcessExited(
                        session_id=session_id, exit_code=exit_code, final_output=current_output, started_at=started_at
                    )
                    break

                # Check if output changed (and exit wasn't already detected)
                output_changed = False
                if current_output != output_buffer and exit_code is None:
                    # Output changed - update buffer and reset idle counter
                    output_buffer = current_output
                    idle_ticks = 0
                    notification_sent = False
                    last_output_changed_at = time.time()
                    output_changed = True

                    # Write to file (with markers stripped)
                    clean_output = self._strip_exit_markers(output_buffer)
                    try:
                        output_file.write_text(clean_output, encoding="utf-8")
                    except Exception as e:
                        logger.warning("Failed to write output file: %s", e)

                    # Reset backoff to global interval when activity resumes
                    current_update_interval = global_update_interval

                # Increment tick counter
                ticks_since_last_update += 1

                # CRITICAL FIX: Send update immediately when output changes OR when interval reached
                # This fixes the bug where first output was delayed by 2 seconds
                if output_buffer and (output_changed or ticks_since_last_update >= current_update_interval):
                    # Strip exit markers before sending
                    clean_output = self._strip_exit_markers(output_buffer)

                    yield OutputChanged(
                        session_id=session_id,
                        output=clean_output,
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

                # Increment idle counter when no output change
                if current_output == output_buffer:
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
        2. <system-reminder>...</system-reminder> blocks (can be nested/multiline)

        Examples of patterns removed:
        - "⎿ UserPromptSubmit hook succeeded: <system-reminder>...</system-reminder>"
        - "⎿  SessionStart:startup hook succeeded: ..."
        - Nested: "<system-reminder>...hook...<system-reminder>...</system-reminder></system-reminder>"

        Args:
            output: Terminal output

        Returns:
            Output with Claude Code hook messages removed
        """
        original_length = len(output)

        # Check if output contains system-reminder tags
        has_system_reminder = "<system-reminder>" in output or "</system-reminder>" in output
        if has_system_reminder:
            logger.info("Found system-reminder tags in output (length: %d)", original_length)

        # Strip hook success prefix lines (⎿ ... hook succeeded: ...)
        output = re.sub(r"⎿[^\n]*hook succeeded:[^\n]*\n?", "", output)

        # Strip <system-reminder> blocks (handles nesting by running multiple times)
        # Use [\s\S] instead of . to explicitly match ANY character including newlines
        for i in range(10):  # Increased iterations for deeply nested blocks
            before = output
            output = re.sub(r"<system-reminder>[\s\S]*?</system-reminder>\s*\n?", "", output)
            if output == before:
                if i > 0 and has_system_reminder:
                    logger.info("System-reminder filtering converged after %d iterations", i)
                break

        # Strip orphaned closing tags and their preceding content
        # Look for patterns that indicate system-reminder content before the closing tag
        before_orphan = output

        # Remove everything from "adhere to the best practices" up to </system-reminder>
        # This is a signature phrase from Claude Code hooks
        output = re.sub(
            r"adhere to the best practices[\s\S]*?</system-reminder>\s*\n?", "", output, flags=re.IGNORECASE
        )

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
        """Strip exit code markers from output.

        Removes both:
        1. The __EXIT__N__ marker output
        2. The ; echo "__EXIT__$?__" command text from shell prompts

        Args:
            output: Terminal output

        Returns:
            Output with markers removed
        """
        # Strip Claude Code hook messages first
        output = self._strip_claude_code_hooks(output)

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
