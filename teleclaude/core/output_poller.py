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
from teleclaude.utils import strip_ansi_codes, strip_exit_markers

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
        global_update_interval = 1  # Global update interval (seconds) - first update after 1s
        directory_check_interval = getattr(config.polling, "directory_check_interval", 5)

        # State tracking
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
        exit_marker_count = None  # Baseline count (None = not established yet)
        output_sent_at_least_once = False  # Ensure user sees output before exit
        previous_output = ""  # Track previous clean output for change detection

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

                    # Read final output from file
                    final_output = ""
                    if output_file.exists():
                        try:
                            final_output = output_file.read_text(encoding="utf-8")
                        except Exception as e:
                            logger.warning("Failed to read final output: %s", e)

                    yield ProcessExited(
                        session_id=session_id, exit_code=None, final_output=final_output, started_at=started_at
                    )
                    break

                session_existed_last_poll = session_exists_now

                # Capture current output
                current_output = await terminal_bridge.capture_pane(tmux_session_name)
                if not current_output.strip():
                    # No output yet, keep polling
                    await asyncio.sleep(poll_interval)
                    continue

                # Strip ANSI codes and collapse whitespace, but KEEP markers (for exit detection)
                current_with_markers = strip_ansi_codes(current_output)
                current_with_markers = re.sub(r"\n\n+", "\n", current_with_markers)

                # Also create clean version (markers stripped) for UI
                current_cleaned = strip_exit_markers(current_with_markers)

                # Detect output changes (for idle tracking)
                output_changed = current_cleaned != previous_output
                if output_changed:
                    previous_output = current_cleaned
                    idle_ticks = 0
                    notification_sent = False
                    last_output_changed_at = time.time()
                    current_update_interval = global_update_interval
                    ticks_since_last_update = 0

                # Increment tick counter
                ticks_since_last_update += 1

                # Send updates based on time interval only (enforce minimum 2s between updates)
                # This prevents Telegram API rate limiting from excessive message edits
                # Send FILTERED TMUX PANE (mirrors what user sees in terminal)
                if ticks_since_last_update >= current_update_interval:
                    # Send clean output to UI (current_cleaned already has markers stripped)
                    yield OutputChanged(
                        session_id=session_id,
                        output=current_cleaned,  # Already clean (markers stripped at line 175)
                        started_at=started_at,
                        last_changed_at=last_output_changed_at,
                    )

                    # Mark that we've sent at least one update
                    output_sent_at_least_once = True

                    # Reset tick counter
                    ticks_since_last_update = 0

                # Exit condition 2: Exit code detected (COUNT-BASED)
                # Count ACTUAL exit markers (pattern __EXIT__\d+__), NOT echo commands
                # Handles: baseline, screen clears, new markers
                # Check AFTER periodic update so user always sees output before exit
                if has_exit_marker:
                    current_marker_count = len(re.findall(r"__EXIT__\d+__", current_with_markers))

                    if exit_marker_count is None:
                        # First poll - check for fast completion
                        # Fast completion: marker exists and at/near end (<50 chars after)
                        # If marker has >50 chars after = old scrollback, establish baseline instead
                        if current_marker_count > 0:
                            # Check content after LAST marker
                            marker_match = re.search(r"__EXIT__\d+__", current_with_markers)
                            if marker_match:
                                content_after_marker = current_with_markers[marker_match.end() :]
                                chars_after = len(content_after_marker.strip())

                                if chars_after < 50:
                                    # Fast completion - marker at/near end
                                    exit_code = self._extract_exit_code(current_with_markers, has_exit_marker)
                                    logger.info(
                                        "Fast completion detected for %s (marker in first poll, %d chars after, exit_code=%d)",
                                        session_id[:8],
                                        chars_after,
                                        exit_code,
                                    )

                                    # Send output before exit (current_cleaned already has markers stripped)
                                    if not output_sent_at_least_once:
                                        yield OutputChanged(
                                            session_id=session_id,
                                            output=current_cleaned,
                                            started_at=started_at,
                                            last_changed_at=last_output_changed_at,
                                        )

                                    # Send current cleaned output (what user sees in tmux)
                                    yield ProcessExited(
                                        session_id=session_id,
                                        exit_code=exit_code,
                                        final_output=current_cleaned,
                                        started_at=started_at,
                                    )
                                    break

                        # Not fast completion - establish baseline (may include old scrollback markers)
                        exit_marker_count = current_marker_count
                        logger.debug(
                            "Exit marker baseline established for %s: %d markers",
                            session_id[:8],
                            current_marker_count,
                        )
                    elif current_marker_count < exit_marker_count:
                        # Screen clear detected - markers disappeared from tmux pane
                        # Reset baseline to current count
                        logger.debug(
                            "Screen clear detected for %s: marker count decreased %d -> %d (resetting baseline)",
                            session_id[:8],
                            exit_marker_count,
                            current_marker_count,
                        )
                        exit_marker_count = current_marker_count
                    elif current_marker_count > exit_marker_count:
                        # NEW marker detected! Count increased from baseline
                        exit_code = self._extract_exit_code(current_with_markers, has_exit_marker)
                        logger.info(
                            "Exit code %d detected for %s (marker count: %d -> %d)",
                            exit_code,
                            session_id[:8],
                            exit_marker_count,
                            current_marker_count,
                        )

                        # ALWAYS send output before exit (ensures visibility)
                        if not output_sent_at_least_once:
                            yield OutputChanged(
                                session_id=session_id,
                                output=current_cleaned,  # Already has markers stripped
                                started_at=started_at,
                                last_changed_at=last_output_changed_at,
                            )
                            output_sent_at_least_once = True

                        # Send current cleaned output (what user sees in tmux)
                        yield ProcessExited(
                            session_id=session_id,
                            exit_code=exit_code,
                            final_output=current_cleaned,
                            started_at=started_at,
                        )
                        break

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
                if not output_changed:
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

    def _extract_exit_code(self, output: str, has_exit_marker: bool) -> Optional[int]:
        """Extract exit code from FULL output using regex.

        Args:
            output: Terminal output (FULL, not just last N lines)
            has_exit_marker: Whether exit marker was appended

        Returns:
            Exit code from LAST marker in output, or None
        """
        if not has_exit_marker:
            return None

        # Find ALL markers in full output using regex
        # Pattern: __EXIT__\d+__ (actual marker with exit code)
        # Returns LAST marker (most recent command)
        matches = re.findall(r"__EXIT__(\d+)__", output)
        if matches:
            return int(matches[-1])  # Return LAST match (most recent)

        return None
