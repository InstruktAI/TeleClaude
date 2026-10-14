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

from instrukt_ai_logging import get_logger

from teleclaude.constants import API_SOCKET_PATH
from teleclaude.core.integration.daemon_window import wait_for_no_accepted_work
from teleclaude.logging_config import setup_logging

logger = get_logger(__name__)

_MAKE_EXECUTABLE = "make"
_RESTART_TARGET = "restart"
_RESTART_ADMISSION_EVENT = "restart_admission_wait"


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
