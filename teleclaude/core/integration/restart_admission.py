"""Commit-boundary restart action: wait, admission open, until the daemon holds no accepted work.

An integration whose commit owes the restart is accepted work like any other, so
preparing the daemon while it still runs would close admission around it. The action
therefore waits up to a bound it owns, then hands over to `make restart`, which stays the
action's last act and decides its outcome. Only a positively read observation ends the wait
early: no held work, admission already closed, or a daemon that publishes no observation. An
unreadable sample is not evidence of no work, so the wait continues until the bound expires.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass

from instrukt_ai_logging import get_logger

from teleclaude.constants import API_SOCKET_PATH
from teleclaude.core.shutdown_drain import DrainPhase
from teleclaude.logging_config import setup_logging
from teleclaude.runtime.daemon_shutdown_control import ControlRefusal, read_health

logger = get_logger(__name__)

# Covers the post-push tail of an integration (final content gate, repo-root publication and
# Blueprint regeneration) with margin; a busier daemon is prepared regardless once it expires.
ADMISSION_WAIT_BOUND_SECONDS = 180.0
_POLL_INTERVAL_SECONDS = 1.0
_MAKE_EXECUTABLE = "make"
_RESTART_TARGET = "restart"
_RESTART_ADMISSION_EVENT = "restart_admission_wait"


@dataclass(frozen=True)
class AdmissionWait:
    """How long the action waited and whether its bound expired before the daemon held no work."""

    waited_seconds: float
    bound_expired: bool


def _must_keep_waiting(socket_path: str) -> bool:
    """Whether the wait goes on: the daemon is open and holds accepted work, or could not be read."""
    try:
        preparation = read_health(socket_path).preparation
    except ControlRefusal:
        return True
    return preparation is not None and preparation.phase is DrainPhase.OPEN and preparation.held_units > 0


def wait_for_no_accepted_work(
    socket_path: str,
    *,
    bound_seconds: float = ADMISSION_WAIT_BOUND_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> AdmissionWait:
    """Poll until the open daemon holds no accepted work, or the bound expires."""
    started = clock()
    deadline = started + bound_seconds
    while _must_keep_waiting(socket_path):
        if clock() >= deadline:
            return AdmissionWait(waited_seconds=clock() - started, bound_expired=True)
        sleep(_POLL_INTERVAL_SECONDS)
    return AdmissionWait(waited_seconds=clock() - started, bound_expired=False)


def main() -> None:
    """Wait for the daemon to hold no accepted work, then replace this process with `make restart`."""
    setup_logging()
    wait = wait_for_no_accepted_work(API_SOCKET_PATH)
    logger.info(
        _RESTART_ADMISSION_EVENT,
        waited_seconds=round(wait.waited_seconds, 1),
        bound_expired=wait.bound_expired,
    )
    # exec leaves nothing to flush the log handlers afterwards.
    logging.shutdown()
    os.execvp(_MAKE_EXECUTABLE, [_MAKE_EXECUTABLE, _RESTART_TARGET])


if __name__ == "__main__":
    main()
