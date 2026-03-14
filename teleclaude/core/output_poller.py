"""Tmux output polling - pure poller with no I/O side effects.

Polls tmux pane output and yields output events.
Daemon handles all message sending.
"""

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.constants import DIRECTORY_CHECK_INTERVAL
from teleclaude.core import tmux_bridge
from teleclaude.core.db import db

logger = get_logger(__name__)
_CONFIG_FOR_TESTS = config
IDLE_SUMMARY_INTERVAL_S = 60.0
PROCESS_START_GRACE_S = 3.0
_TERMINAL_SESSION_STATUSES = frozenset({"closing", "closed"})


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

    exit_code: int | None
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

    async def _handle_missing_session(
        self,
        *,
        session_id: str,
        tmux_session_name: str,
        previous_output: str,
        last_sent_output: str | None,
        started_at: float,
        last_output_changed_at: float,
    ) -> AsyncIterator[OutputEvent]:
        logger.info("Process exited for %s, stopping poll", session_id)
        if previous_output and previous_output != last_sent_output and previous_output.strip():
            yield OutputChanged(
                session_id=session_id,
                output=previous_output,
                started_at=started_at,
                last_changed_at=last_output_changed_at,
            )
        yield ProcessExited(
            session_id=session_id,
            exit_code=None,
            final_output=previous_output,
            started_at=started_at,
        )

    async def _log_watchdog_transition(
        self,
        *,
        session_id: str,
        tmux_session_name: str,
        started_at: float,
        poll_iteration: int,
        poll_interval: float,
    ) -> None:
        try:
            session = await db.get_session(session_id)
        except RuntimeError:
            session = None
        if not session:
            logger.debug("Session %s disappeared (session terminated) session=%s", tmux_session_name, session_id)
            return
        if session.closed_at or session.lifecycle_status in _TERMINAL_SESSION_STATUSES:
            logger.info(
                "Session %s disappeared during close transition (watchdog close race) session=%s status=%s",
                tmux_session_name,
                session_id,
                session.lifecycle_status,
            )
            return
        logger.critical(
            "Session %s disappeared between polls (watchdog triggered) "
            "session=%s age=%.2fs poll_iteration=%d seconds_since_last_poll=%.1f",
            tmux_session_name,
            session_id,
            time.time() - started_at,
            poll_iteration,
            poll_interval,
        )

    def _maybe_yield_output(
        self,
        *,
        session_id: str,
        current_cleaned: str,
        started_at: float,
        last_output_changed_at: float,
        output_sent_at_least_once: bool,
        pending_output: bool,
        pending_idle_flush: bool,
        last_yield_time: float,
        output_cadence_s: float,
    ) -> tuple[OutputChanged | None, bool, bool, bool, float, bool]:
        current_time = time.time()
        elapsed_since_last_yield = current_time - last_yield_time
        if elapsed_since_last_yield >= output_cadence_s:
            should_send = (
                pending_output if output_sent_at_least_once else (pending_output and bool(current_cleaned.strip()))
            )
            if should_send:
                return (
                    OutputChanged(
                        session_id=session_id,
                        output=current_cleaned,
                        started_at=started_at,
                        last_changed_at=last_output_changed_at,
                    ),
                    True,
                    False,
                    False,
                    current_time,
                    True,
                )
            if pending_output and not output_sent_at_least_once:
                pending_output = False
        if pending_idle_flush and (current_time - last_output_changed_at) >= 3.0 and current_cleaned.strip():
            return (
                OutputChanged(
                    session_id=session_id,
                    output=current_cleaned,
                    started_at=started_at,
                    last_changed_at=last_output_changed_at,
                ),
                True,
                False,
                False,
                current_time,
                True,
            )
        if pending_idle_flush and not output_sent_at_least_once and not current_cleaned.strip():
            pending_idle_flush = False
        return None, output_sent_at_least_once, pending_output, pending_idle_flush, last_yield_time, False

    async def _maybe_yield_dead_pane(
        self,
        *,
        session_id: str,
        tmux_session_name: str,
        current_cleaned: str,
        started_at: float,
        last_output_changed_at: float,
        pending_output: bool,
        output_changed: bool,
        output_sent_at_least_once: bool,
    ) -> AsyncIterator[OutputEvent]:
        if not await tmux_bridge.is_pane_dead(tmux_session_name):
            return
        should_emit_final = pending_output or output_changed or output_sent_at_least_once
        if should_emit_final and current_cleaned.strip():
            yield OutputChanged(
                session_id=session_id,
                output=current_cleaned,
                started_at=started_at,
                last_changed_at=last_output_changed_at,
            )
        yield ProcessExited(
            session_id=session_id,
            exit_code=None,
            final_output=current_cleaned,
            started_at=started_at,
        )
        logger.info("Shell exited for %s, stopping poll", session_id)

    def _log_output_tail_change(self, session_id: str, captured_output: str, previous_output: str) -> None:
        if not captured_output:
            return
        curr_last_lines = captured_output.rstrip().split("\n")[-3:]
        prev_last_lines = previous_output.rstrip().split("\n")[-3:] if previous_output else []
        if curr_last_lines != prev_last_lines:
            logger.trace(
                "[POLL %s] Last 3 lines changed: prev=%r, curr=%r",
                session_id,
                [line[:50] for line in prev_last_lines],
                [line[:50] for line in curr_last_lines],
            )

    async def _maybe_yield_directory_change(
        self,
        *,
        session_id: str,
        tmux_session_name: str,
        directory_check_interval: int,
        directory_check_ticks: int,
        last_directory: str | None,
    ) -> tuple[int, str | None, DirectoryChanged | None]:
        if directory_check_interval <= 0:
            return directory_check_ticks, last_directory, None
        directory_check_ticks += 1
        if directory_check_ticks < directory_check_interval:
            return directory_check_ticks, last_directory, None
        directory_check_ticks = 0
        current_directory = await tmux_bridge.get_current_directory(tmux_session_name)
        if not current_directory:
            return directory_check_ticks, last_directory, None
        if last_directory is not None and current_directory != last_directory:
            logger.info("Directory changed for %s: %s -> %s", session_id, last_directory, current_directory)
            return (
                directory_check_ticks,
                current_directory,
                DirectoryChanged(
                    session_id=session_id,
                    new_path=current_directory,
                    old_path=last_directory,
                ),
            )
        return directory_check_ticks, current_directory, None

    async def _check_session_presence(
        self,
        *,
        session_id: str,
        tmux_session_name: str,
        session_existed_last_poll: bool,
        started_at: float,
        poll_iteration: int,
        poll_interval: float,
        previous_output: str,
        last_sent_output: str | None,
        last_output_changed_at: float,
    ) -> tuple[bool, bool, list[OutputEvent]]:
        session_exists_now = await tmux_bridge.session_exists(tmux_session_name, log_missing=False)

        if session_existed_last_poll and not session_exists_now:
            await self._log_watchdog_transition(
                session_id=session_id,
                tmux_session_name=tmux_session_name,
                started_at=started_at,
                poll_iteration=poll_iteration,
                poll_interval=poll_interval,
            )

        if session_exists_now:
            return True, False, []

        events = [
            event
            async for event in self._handle_missing_session(
                session_id=session_id,
                tmux_session_name=tmux_session_name,
                previous_output=previous_output,
                last_sent_output=last_sent_output,
                started_at=started_at,
                last_output_changed_at=last_output_changed_at,
            )
        ]
        return False, True, events

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
            logger.trace("Polling started for %s", session_id)

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
                    session_id,
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

                session_exists_now, should_stop, missing_session_events = await self._check_session_presence(
                    session_id=session_id,
                    tmux_session_name=tmux_session_name,
                    session_existed_last_poll=session_existed_last_poll,
                    started_at=started_at,
                    poll_iteration=poll_iteration,
                    poll_interval=poll_interval,
                    previous_output=previous_output,
                    last_sent_output=last_sent_output,
                    last_output_changed_at=last_output_changed_at,
                )
                if should_stop:
                    for event in missing_session_events:
                        yield event
                    break

                session_existed_last_poll = session_exists_now

                captured_output = await tmux_bridge.capture_pane(tmux_session_name)
                output_changed = captured_output != previous_output
                current_cleaned = captured_output

                self._log_output_tail_change(session_id, captured_output, previous_output)

                if output_changed:
                    maybe_log_idle_summary(force=True)
                    previous_output = current_cleaned
                    idle_ticks = 0
                    last_output_changed_at = time.time()
                    pending_output = True
                    pending_idle_flush = True
                    # Output file persistence removed; downloads now use native session logs.

                (
                    output_event,
                    output_sent_at_least_once,
                    pending_output,
                    pending_idle_flush,
                    last_yield_time,
                    did_yield,
                ) = self._maybe_yield_output(
                    session_id=session_id,
                    current_cleaned=current_cleaned,
                    started_at=started_at,
                    last_output_changed_at=last_output_changed_at,
                    output_sent_at_least_once=output_sent_at_least_once,
                    pending_output=pending_output,
                    pending_idle_flush=pending_idle_flush,
                    last_yield_time=last_yield_time,
                    output_cadence_s=output_cadence_s,
                )
                if output_event is not None:
                    yield output_event
                    last_sent_output = current_cleaned

                # Exit condition 2: tmux pane fully exited (shell ended)
                pane_dead = False
                async for event in self._maybe_yield_dead_pane(
                    session_id=session_id,
                    tmux_session_name=tmux_session_name,
                    current_cleaned=current_cleaned,
                    started_at=started_at,
                    last_output_changed_at=last_output_changed_at,
                    pending_output=pending_output,
                    output_changed=output_changed,
                    output_sent_at_least_once=output_sent_at_least_once,
                ):
                    pane_dead = True
                    yield event
                if pane_dead:
                    break

                # Increment idle counter when no new content
                if not output_changed:
                    idle_ticks += 1
                    if not did_yield:
                        suppressed_idle_ticks += 1
                        maybe_log_idle_summary()

                directory_check_ticks, last_directory, directory_event = await self._maybe_yield_directory_change(
                    session_id=session_id,
                    tmux_session_name=tmux_session_name,
                    directory_check_interval=directory_check_interval,
                    directory_check_ticks=directory_check_ticks,
                    last_directory=last_directory,
                )
                if directory_event is not None:
                    yield directory_event

                await asyncio.sleep(poll_interval)

        finally:
            logger.debug("Polling ended for session %s", session_id)
