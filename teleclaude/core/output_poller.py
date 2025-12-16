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

from teleclaude.constants import DIRECTORY_CHECK_INTERVAL
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
class DirectoryChanged(OutputEvent):
    """Directory changed event."""

    new_path: str
    old_path: str


class OutputPoller:
    """Pure poller - yields output events, no message sending.

    All dependencies (config, terminal_bridge) are imported at module level.
    """

    async def poll(  # pylint: disable=too-many-locals  # Poll loop naturally has many state variables
        self,
        session_id: str,
        tmux_session_name: str,
        output_file: Path,
        marker_id: Optional[str],
    ) -> AsyncIterator[OutputEvent]:
        """Poll terminal output and yield events.

        Args:
            session_id: Session ID
            tmux_session_name: tmux session name
            output_file: Path to output file
            marker_id: Unique marker ID for exit detection (None = no exit marker)

        Yields:
            OutputEvent subclasses (OutputChanged, ProcessExited, DirectoryChanged)
        """
        # Configuration
        poll_interval = 1.0
        global_update_interval = 3  # Global update interval (seconds) - first update after 1s
        directory_check_interval = DIRECTORY_CHECK_INTERVAL

        # State tracking
        idle_ticks = 0
        started_at: float | None = None
        last_output_changed_at: float | None = None
        current_update_interval = global_update_interval  # Start with global interval
        last_directory: str | None = None
        directory_check_ticks = 0
        poll_iteration = 0
        session_existed_last_poll = True  # Watchdog: track if session existed in previous poll
        output_sent_at_least_once = False  # Ensure user sees output before exit
        previous_output = ""  # Track previous clean output for change detection

        try:
            # Initial delay before first poll (1s to catch fast commands)
            await asyncio.sleep(1.0)
            started_at = time.time()
            last_output_changed_at = started_at
            last_yield_time = started_at  # Track when we last yielded (wall-clock, not tick-based)
            logger.debug("Polling started for %s with marker_id=%s", session_id[:8], marker_id)

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
                            raw_output = output_file.read_text(encoding="utf-8")
                            # Clean the output (strip ANSI and exit markers)
                            final_output = strip_ansi_codes(raw_output)
                            final_output = strip_exit_markers(final_output)
                        except Exception as e:
                            logger.warning("Failed to read final output: %s", e)

                    yield ProcessExited(
                        session_id=session_id,
                        exit_code=None,
                        final_output=final_output,
                        started_at=started_at,
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
                    last_output_changed_at = time.time()
                    current_update_interval = global_update_interval
                    logger.debug(
                        "[POLL %s] Output CHANGED - reset interval to %ds, idle_ticks=0",
                        session_id[:8],
                        global_update_interval,
                    )

                # Check if enough time elapsed since last yield (wall-clock, not tick-based)
                current_time = time.time()
                elapsed_since_last_yield = current_time - last_yield_time

                # Send updates based on time interval only (enforce minimum 2s between updates)
                # This prevents Telegram API rate limiting from excessive message edits
                # Send FILTERED TMUX PANE (mirrors what user sees in terminal)
                if elapsed_since_last_yield >= current_update_interval:
                    logger.debug(
                        "[POLL %s] YIELDING OutputChanged: elapsed=%.1fs >= interval=%ds, idle_ticks=%d",
                        session_id[:8],
                        elapsed_since_last_yield,
                        current_update_interval,
                        idle_ticks,
                    )
                    # Send clean output to UI (current_cleaned already has markers stripped)
                    yield OutputChanged(
                        session_id=session_id,
                        output=current_cleaned,  # Already clean (markers stripped at line 175)
                        started_at=started_at,
                        last_changed_at=last_output_changed_at,
                    )
                    logger.debug(
                        "[POLL %s] Resumed after yield, consumer processed event",
                        session_id[:8],
                    )

                    # Mark that we've sent at least one update
                    output_sent_at_least_once = True

                    # Update last yield time (ONLY after yielding, not on every change!)
                    last_yield_time = current_time
                else:
                    wait_time = current_update_interval - elapsed_since_last_yield
                    logger.debug(
                        "[POLL %s] SKIPPING yield: elapsed=%.1fs < interval=%ds (waiting %.1f more seconds)",
                        session_id[:8],
                        elapsed_since_last_yield,
                        current_update_interval,
                        wait_time,
                    )

                # Exit condition 2: Exit code detected (EXACT MARKER MATCHING)
                # Search for unique marker pattern - no counting, no baseline needed
                # Check AFTER periodic update so user always sees output before exit
                if marker_id:
                    marker_pattern = f"__EXIT__{marker_id}__(\\d+)__"
                    marker_match = re.search(marker_pattern, current_with_markers)

                    if marker_match:
                        exit_code = int(marker_match.group(1))
                        logger.info(
                            "Exit code %d detected for %s (marker_id=%s)",
                            exit_code,
                            session_id[:8],
                            marker_id,
                        )

                        # Ensure output is sent before exit
                        if not output_sent_at_least_once:
                            yield OutputChanged(
                                session_id=session_id,
                                output=current_cleaned,
                                started_at=started_at,
                                last_changed_at=last_output_changed_at,
                            )

                        yield ProcessExited(
                            session_id=session_id,
                            exit_code=exit_code,
                            final_output=current_cleaned,
                            started_at=started_at,
                        )
                        break

                # Apply exponential backoff when idle: 3s -> 6s -> 9s -> 12s -> 15s
                if idle_ticks >= current_update_interval:
                    old_interval = current_update_interval
                    current_update_interval = min(current_update_interval + 3, 15)
                    logger.debug(
                        "[POLL %s] BACK-OFF APPLIED: idle_ticks=%d, interval %ds → %ds",
                        session_id[:8],
                        idle_ticks,
                        old_interval,
                        current_update_interval,
                    )

                # Increment idle counter when no new content
                if not output_changed:
                    idle_ticks += 1
                    logger.debug(
                        "[POLL %s] Output unchanged - idle_ticks=%d, current_interval=%ds",
                        session_id[:8],
                        idle_ticks,
                        current_update_interval,
                    )

                # Check for directory changes (if enabled)
                if directory_check_interval > 0:
                    directory_check_ticks += 1
                    if directory_check_ticks >= directory_check_interval:
                        directory_check_ticks = 0
                        current_directory = await terminal_bridge.get_current_directory(tmux_session_name)

                        if current_directory:
                            # Only yield event if we moved FROM a directory (not startup)
                            if last_directory is not None and current_directory != last_directory:
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

                            # Update state if changed
                            if current_directory != last_directory:
                                last_directory = current_directory

                await asyncio.sleep(poll_interval)

        finally:
            logger.debug("Polling ended for session %s", session_id[:8])

    def _extract_exit_code(self, output: str, marker_id: Optional[str]) -> Optional[int]:
        """Extract exit code from output using exact marker matching.

        Args:
            output: Terminal output
            marker_id: Unique marker ID (None = no exit marker)

        Returns:
            Exit code from matching marker, or None
        """
        if not marker_id:
            return None

        # Search for exact marker with marker_id
        # Pattern: __EXIT__{marker_id}__\d+__
        pattern = f"__EXIT__{marker_id}__(\\d+)__"
        match = re.search(pattern, output)
        if match:
            return int(match.group(1))

        return None
