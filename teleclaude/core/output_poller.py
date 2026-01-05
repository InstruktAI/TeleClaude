"""Terminal output polling - pure poller with no I/O side effects.

Reads raw terminal output logs (tmux pipe-pane) and yields output events.
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
from teleclaude.core import terminal_bridge
from teleclaude.core.db import db

logger = get_logger(__name__)
_CONFIG_FOR_TESTS = config
IDLE_SUMMARY_INTERVAL_S = 60.0
PROCESS_START_GRACE_S = 3.0


def _parse_terminal_rows(value: str | None) -> int | None:
    if value and "x" in value:
        try:
            _cols_str, rows_str = value.split("x", 1)
            rows = int(rows_str)
            return rows if rows > 0 else None
        except ValueError:
            return None
    return None


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
    ) -> AsyncIterator[OutputEvent]:
        """Poll terminal output and yield events.

        Args:
            session_id: Session ID
            tmux_session_name: tmux session name
            output_file: Path to output file

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
        last_sent_output: str | None = None
        previous_output = ""  # Track previous clean output for change detection
        pending_output = False  # Output changed since last yield
        suppressed_idle_ticks = 0
        last_summary_time: float | None = None
        idle_summary_interval = IDLE_SUMMARY_INTERVAL_S
        terminal_rows: int | None = None

        try:
            # Initial delay before first poll (1s to catch fast commands)
            await asyncio.sleep(1.0)
            started_at = time.time()
            last_output_changed_at = started_at
            last_yield_time = started_at  # Track when we last yielded (wall-clock, not tick-based)
            last_summary_time = started_at
            logger.trace("Polling started for %s", session_id[:8])

            try:
                session = await db.get_session(session_id)
                terminal_rows = _parse_terminal_rows(session.terminal_size) if session else None
            except Exception:
                terminal_rows = None

            def maybe_log_idle_summary(force: bool = False) -> None:
                nonlocal last_summary_time, suppressed_idle_ticks
                if suppressed_idle_ticks <= 0:
                    return
                now = time.time()
                if last_summary_time is None:
                    last_summary_time = now
                if not force and (now - last_summary_time) < idle_summary_interval:
                    return
                idle_for = 0.0
                if last_output_changed_at is not None:
                    idle_for = max(0.0, now - last_output_changed_at)
                logger.trace(
                    "[POLL %s] idle: unchanged for %.1fs (suppressed=%d, interval=%ds, idle_ticks=%d)",
                    session_id[:8],
                    idle_for,
                    suppressed_idle_ticks,
                    current_update_interval,
                    idle_ticks,
                )
                suppressed_idle_ticks = 0
                last_summary_time = now

            # Poll loop - EXPLICIT EXIT CONDITIONS
            while True:
                poll_iteration += 1

                # Exit condition 1: Session died (don't log ERROR here - we check below)
                session_exists_now = await terminal_bridge.session_exists(tmux_session_name, log_missing=False)

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
                    if previous_output and previous_output != last_sent_output:
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

                captured_output = await terminal_bridge.capture_pane(tmux_session_name, lines=terminal_rows)
                output_changed = captured_output != previous_output
                current_cleaned = captured_output

                if output_changed:
                    maybe_log_idle_summary(force=True)
                    previous_output = current_cleaned
                    idle_ticks = 0
                    last_output_changed_at = time.time()
                    current_update_interval = global_update_interval
                    pending_output = True
                    try:
                        output_file.write_text(current_cleaned, encoding="utf-8")
                    except Exception as exc:
                        logger.warning("Failed to write output file %s: %s", output_file, exc)

                # Check if enough time elapsed since last yield (wall-clock, not tick-based)
                current_time = time.time()
                elapsed_since_last_yield = current_time - last_yield_time

                # Send updates based on time interval, but only when output changes
                # (or when we have never sent output yet). This avoids UI spam when idle.
                did_yield = False
                if elapsed_since_last_yield >= current_update_interval:
                    if pending_output or (not output_sent_at_least_once and current_cleaned.strip()):
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

                        # Update last yield time (ONLY after yielding, not on every change!)
                        last_yield_time = current_time
                        did_yield = True
                else:
                    # Skip per-tick logging; summarized in idle summaries.
                    pass

                # Exit condition 2: tmux pane fully exited (shell ended)
                if await terminal_bridge.is_pane_dead(tmux_session_name):
                    # Force a final snapshot if output changed since last yield (or nothing was sent yet).
                    if pending_output or output_changed or not output_sent_at_least_once:
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

                # Apply exponential backoff when idle: 3s -> 6s -> 9s -> 12s -> 15s
                if idle_ticks >= current_update_interval:
                    current_update_interval = min(current_update_interval + 3, 15)

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
