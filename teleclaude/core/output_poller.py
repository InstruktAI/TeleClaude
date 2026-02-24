"""Tmux output polling - pure poller with no I/O side effects.

Polls tmux pane output and yields output events.
Daemon handles all message sending.
"""

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Optional

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.constants import DIRECTORY_CHECK_INTERVAL
from teleclaude.core import tmux_bridge
from teleclaude.core.db import db

logger = get_logger(__name__)
_CONFIG_FOR_TESTS = config
IDLE_SUMMARY_INTERVAL_S = 60.0
PROCESS_START_GRACE_S = 3.0


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

    All dependencies (config, tmux_bridge) are imported at module level.
    """

    async def poll(  # pylint: disable=too-many-locals  # Poll loop naturally has many state variables
        self,
        session_id: str,
        tmux_session_name: str,
        output_file: Path,
    ) -> AsyncIterator[OutputEvent]:
        """Poll tmux output and yield events.

        Args:
            session_id: Session ID
            tmux_session_name: tmux session name
            output_file: Reserved for future file-based polling; currently unused.

        Yields:
            OutputEvent subclasses (OutputChanged, ProcessExited, DirectoryChanged)
        """
        # Configuration
        output_cadence_s = max(0.1, float(getattr(_CONFIG_FOR_TESTS.polling, "output_cadence_s", 1.0)))
        poll_interval = min(1.0, output_cadence_s)
        directory_check_interval = DIRECTORY_CHECK_INTERVAL

        # State tracking
        idle_ticks = 0
        started_at: float | None = None
        last_output_changed_at = 0.0
        last_directory: str | None = None
        directory_check_ticks = 0
        poll_iteration = 0
        session_existed_last_poll = True  # Watchdog: track if session existed in previous poll
        output_sent_at_least_once = False  # Ensure user sees output before exit
        last_sent_output: str | None = None
        previous_output = ""  # Track previous clean output for change detection
        pending_output = False  # Output changed since last yield
        pending_idle_flush = False  # One-time flush after output goes idle
        suppressed_idle_ticks = 0
        last_summary_time: float | None = None
        idle_summary_interval = IDLE_SUMMARY_INTERVAL_S

        try:
            # Initial delay before first poll (1s to catch fast commands)
            await asyncio.sleep(1.0)
            started_at = time.time()
            last_output_changed_at = started_at
            last_yield_time = started_at - output_cadence_s  # Force first send after cadence check
            last_summary_time = started_at
            logger.trace("Polling started for %s", session_id[:8])

            def maybe_log_idle_summary(force: bool = False) -> None:
                nonlocal last_summary_time, suppressed_idle_ticks
                if suppressed_idle_ticks <= 0:
                    return
                now = time.time()
                if last_summary_time is None:
                    last_summary_time = now
                if not force and (now - last_summary_time) < idle_summary_interval:
                    return
                idle_for = max(0.0, now - last_output_changed_at)
                logger.trace(
                    "[POLL %s] idle: unchanged for %.1fs (suppressed=%d, cadence_s=%.2f, idle_ticks=%d)",
                    session_id[:8],
                    idle_for,
                    suppressed_idle_ticks,
                    output_cadence_s,
                    idle_ticks,
                )
                suppressed_idle_ticks = 0
                last_summary_time = now

            # Poll loop - EXPLICIT EXIT CONDITIONS
            while True:
                poll_iteration += 1

                session_exists_now = await tmux_bridge.session_exists(tmux_session_name, log_missing=False)
                if session_exists_now:
                    captured_output = await tmux_bridge.capture_pane(tmux_session_name)
                else:
                    captured_output = ""

                # WATCHDOG: Detect session disappearing between polls
                if session_existed_last_poll and not session_exists_now:
                    # Check if this was an expected closure (session terminated)
                    try:
                        session = await db.get_session(session_id)
                    except RuntimeError:
                        session = None
                    if not session:
                        # Expected closure - session was terminated and removed
                        logger.debug(
                            "Session %s disappeared (session terminated) session=%s",
                            tmux_session_name,
                            session_id[:8],
                        )
                    else:
                        # Unexpected death - log as critical with diagnostics
                        age_seconds = time.time() - started_at
                        logger.critical(
                            "Session %s disappeared between polls (watchdog triggered) "
                            "session=%s age=%.2fs poll_iteration=%d seconds_since_last_poll=%.1f",
                            tmux_session_name,
                            session_id[:8],
                            age_seconds,
                            poll_iteration,
                            poll_interval,
                        )

                if not session_exists_now:
                    logger.info("Process exited for %s, stopping poll", session_id[:8])

                    # Send a final snapshot if the last observed output wasn't emitted yet.
                    if previous_output and previous_output != last_sent_output and previous_output.strip():
                        yield OutputChanged(
                            session_id=session_id,
                            output=previous_output,
                            started_at=started_at,
                            last_changed_at=last_output_changed_at,
                        )
                        last_sent_output = previous_output

                    final_output = previous_output

                    yield ProcessExited(
                        session_id=session_id,
                        exit_code=None,
                        final_output=final_output,
                        started_at=started_at,
                    )
                    break

                session_existed_last_poll = session_exists_now

                captured_output = await tmux_bridge.capture_pane(tmux_session_name)
                output_changed = captured_output != previous_output
                current_cleaned = captured_output

                # Debug: Log last line changes for Codex input detection
                if captured_output:
                    curr_last_lines = captured_output.rstrip().split("\n")[-3:]
                    prev_last_lines = previous_output.rstrip().split("\n")[-3:] if previous_output else []
                    if curr_last_lines != prev_last_lines:
                        logger.trace(
                            "[POLL %s] Last 3 lines changed: prev=%r, curr=%r",
                            session_id[:8],
                            [line[:50] for line in prev_last_lines],
                            [line[:50] for line in curr_last_lines],
                        )

                if output_changed:
                    maybe_log_idle_summary(force=True)
                    previous_output = current_cleaned
                    idle_ticks = 0
                    last_output_changed_at = time.time()
                    pending_output = True
                    pending_idle_flush = True
                    # Output file persistence removed; downloads now use native session logs.

                # Check if enough time elapsed since last yield (wall-clock, not tick-based)
                current_time = time.time()
                elapsed_since_last_yield = current_time - last_yield_time

                # Send updates based on time interval, but only when output changes
                # (or when we have never sent output yet). This avoids UI spam when idle.
                did_yield = False
                if elapsed_since_last_yield >= output_cadence_s:
                    should_send = False
                    if output_sent_at_least_once:
                        should_send = pending_output
                    else:
                        should_send = True

                    if should_send:
                        # Send rendered TUI snapshot to UI
                        yield OutputChanged(
                            session_id=session_id,
                            output=current_cleaned,
                            started_at=started_at,
                            last_changed_at=last_output_changed_at,
                        )

                        # Mark that we've sent at least one update
                        output_sent_at_least_once = True
                        last_sent_output = current_cleaned
                        pending_output = False
                        pending_idle_flush = False

                        # Update last yield time (ONLY after yielding, not on every change!)
                        last_yield_time = current_time
                        did_yield = True
                    elif pending_output and not output_sent_at_least_once:
                        # Suppress empty initial output until something real appears.
                        pending_output = False
                if pending_idle_flush and (current_time - last_output_changed_at) >= 3.0:
                    yield OutputChanged(
                        session_id=session_id,
                        output=current_cleaned,
                        started_at=started_at,
                        last_changed_at=last_output_changed_at,
                    )
                    output_sent_at_least_once = True
                    last_sent_output = current_cleaned
                    pending_output = False
                    pending_idle_flush = False
                    last_yield_time = current_time
                    did_yield = True
                else:
                    # Skip per-tick logging; summarized in idle summaries.
                    pass

                # Exit condition 2: tmux pane fully exited (shell ended)
                if await tmux_bridge.is_pane_dead(tmux_session_name):
                    # Force a final snapshot if output changed since last yield (or nothing was sent yet).
                    should_emit_final = pending_output or output_changed or output_sent_at_least_once
                    if should_emit_final and current_cleaned.strip():
                        yield OutputChanged(
                            session_id=session_id,
                            output=current_cleaned,
                            started_at=started_at,
                            last_changed_at=last_output_changed_at,
                        )
                        last_sent_output = current_cleaned

                    yield ProcessExited(
                        session_id=session_id,
                        exit_code=None,
                        final_output=current_cleaned,
                        started_at=started_at,
                    )
                    logger.info("Shell exited for %s, stopping poll", session_id[:8])
                    break

                # Increment idle counter when no new content
                if not output_changed:
                    idle_ticks += 1
                    if not did_yield:
                        suppressed_idle_ticks += 1
                        maybe_log_idle_summary()

                # Check for directory changes (if enabled)
                if directory_check_interval > 0:
                    directory_check_ticks += 1
                    if directory_check_ticks >= directory_check_interval:
                        directory_check_ticks = 0
                        current_directory = await tmux_bridge.get_current_directory(tmux_session_name)

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
