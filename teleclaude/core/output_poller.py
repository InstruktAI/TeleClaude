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
            OutputEvent subclasses (OutputChanged, ProcessExited, IdleDetected)
        """
        # Configuration
        idle_threshold = config.polling.idle_notification_seconds
        poll_interval = 1.0

        # State tracking
        output_buffer = ""
        idle_ticks = 0
        notification_sent = False
        started_at = None
        last_output_changed_at = None
        ticks_since_last_update = 0
        update_interval = 5  # Start with 5 seconds
        next_update_at = update_interval  # When to send next periodic update
        first_poll = True  # Skip exit detection on first poll (establish baseline)

        try:
            # Initial delay before first poll (1s to catch fast commands)
            await asyncio.sleep(1.0)
            started_at = time.time()
            last_output_changed_at = started_at
            logger.debug("Polling started for %s with has_exit_marker=%s", session_id[:8], has_exit_marker)

            # Poll loop - EXPLICIT EXIT CONDITIONS
            while True:
                # Exit condition 1: Session died
                if not await terminal_bridge.session_exists(tmux_session_name):
                    logger.info("Process exited for %s, stopping poll", session_id[:8])
                    yield ProcessExited(
                        session_id=session_id, exit_code=None, final_output=output_buffer, started_at=started_at
                    )
                    break

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
                    logger.debug("Baseline established for %s (size=%d)", session_id[:8], len(output_buffer))
                    # Continue polling (don't check for exit in baseline to avoid old markers)

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
                if current_output != output_buffer and exit_code is None:
                    # Output changed - reset idle counter and exponential backoff
                    output_buffer = current_output
                    idle_ticks = 0
                    notification_sent = False
                    ticks_since_last_update = 0
                    update_interval = 5  # Reset to initial interval
                    next_update_at = update_interval
                    last_output_changed_at = time.time()

                    # Strip exit markers from output before showing to user
                    clean_output = self._strip_exit_markers(output_buffer)

                    # Write to file (with markers stripped)
                    try:
                        output_file.write_text(clean_output, encoding="utf-8")
                    except Exception as e:
                        logger.warning("Failed to write output file: %s", e)

                    # Yield output changed event (with markers stripped)
                    yield OutputChanged(
                        session_id=session_id,
                        output=clean_output,
                        started_at=started_at,
                        last_changed_at=last_output_changed_at,
                    )

                else:
                    # Output unchanged - increment idle counter
                    idle_ticks += 1
                    ticks_since_last_update += 1

                    # Send periodic updates with exponential backoff to refresh idle status
                    # Only if we have output (command is running)
                    if output_buffer and ticks_since_last_update >= next_update_at:
                        # Strip exit markers before sending
                        clean_output = self._strip_exit_markers(output_buffer)

                        yield OutputChanged(
                            session_id=session_id,
                            output=clean_output,
                            started_at=started_at,
                            last_changed_at=last_output_changed_at,
                        )

                        # Exponential backoff: double interval, capped at idle_threshold
                        ticks_since_last_update = 0
                        update_interval = min(update_interval * 2, idle_threshold)
                        next_update_at = update_interval
                        logger.debug(
                            "Sent periodic update for %s, next update in %ds",
                            session_id[:8],
                            update_interval,
                        )

                    # Send idle notification once at threshold
                    if idle_ticks == idle_threshold and not notification_sent:
                        logger.info("No output change for %ds for %s, notifying user", idle_threshold, session_id[:8])
                        yield IdleDetected(session_id=session_id, idle_seconds=idle_threshold)
                        notification_sent = True

                await asyncio.sleep(poll_interval)

        finally:
            logger.debug("Polling ended for session %s", session_id[:8])

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
