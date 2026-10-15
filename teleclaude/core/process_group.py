"""Observing and settling a process group that holds a detached unit of work, and classifying a recorded one.

The gate runner leads the group its workload runs in. These primitives are shared by the runner (which settles its
own group), the daemon (which classifies a recorded unit and records its end) and the janitor (which enforces a
lease). They never act on a group number alone: a member is signalled only after its group is read again, and a
recorded unit is classified from the recorded identity and the processes, never from a clock
(``local/projects/teleclaude/design/process-lifecycle``).
"""

from __future__ import annotations

import os
import signal
import time
from collections.abc import Callable
from enum import StrEnum
from typing import Final

import psutil

from teleclaude.core.process_identity import NO_IDENTITY, start_identity

GRACE_SECONDS: Final = 3.0
SETTLE_BOUND_SECONDS: Final = 10.0
POLL_SECONDS: Final = 0.1
MIN_SIGNALLABLE_PID: Final = 1  # pid 0 reads as the caller's own group and pid 1 is the init process


class UnitClass(StrEnum):
    """What is known of a recorded unit: its runner lives, nothing of it remains, or that cannot be told."""

    LIVE = "live"
    DEAD = "dead"
    UNKNOWN = "unknown"


def live_members(pgid: int, *, exclude: int = 0) -> list[int]:
    """The pids of the non-zombie processes whose group is ``pgid``, except ``exclude``; a zombie is not running work."""
    members: list[int] = []
    for process in psutil.process_iter():
        try:
            if process.pid <= MIN_SIGNALLABLE_PID or process.pid == exclude:
                continue
            if process.status() == psutil.STATUS_ZOMBIE:
                continue
            if os.getpgid(process.pid) == pgid:
                members.append(process.pid)
        except (psutil.Error, ProcessLookupError, PermissionError):
            continue
    return members


def _signal_member(pid: int, pgid: int, sig: signal.Signals) -> bool:
    """Signal one process after reading its group again; False when it is no longer in the group."""
    if pid <= MIN_SIGNALLABLE_PID:
        return False
    try:
        if os.getpgid(pid) != pgid:
            return False
        os.kill(pid, sig)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def settle_members(
    pgid: int,
    *,
    exclude: int = 0,
    grace: float = GRACE_SECONDS,
    bound: float = SETTLE_BOUND_SECONDS,
    before_signal: Callable[[int], None] | None = None,
) -> tuple[bool, tuple[int, ...]]:
    """End every live member of the group except ``exclude``: terminate, give a grace, kill, then observe.

    Returns whether none remains within the bound, and the pids that were signalled. Only the group's leader being
    positively known to be the caller's own makes this safe to call; the callers establish that.
    """
    signalled: list[int] = []
    deadline = time.monotonic() + bound
    for pid in live_members(pgid, exclude=exclude):
        if before_signal is not None:
            before_signal(pid)
        if _signal_member(pid, pgid, signal.SIGTERM):
            signalled.append(pid)
    grace_end = time.monotonic() + grace
    while time.monotonic() < grace_end and live_members(pgid, exclude=exclude):
        time.sleep(POLL_SECONDS)
    for pid in live_members(pgid, exclude=exclude):
        if before_signal is not None:
            before_signal(pid)
        if _signal_member(pid, pgid, signal.SIGKILL) and pid not in signalled:
            signalled.append(pid)
    while time.monotonic() < deadline:
        if not live_members(pgid, exclude=exclude):
            return True, tuple(signalled)
        time.sleep(POLL_SECONDS)
    return not live_members(pgid, exclude=exclude), tuple(signalled)


def is_runner_alive(pid: int, identity: str) -> bool:
    """Whether the recorded runner lives: the same pid with the same start identity, and not a zombie."""
    if not pid or not identity or start_identity(pid) != identity:
        return False
    try:
        return bool(psutil.Process(pid).status() != psutil.STATUS_ZOMBIE)
    except psutil.Error:
        return False


def classify_unit(*, host: str, boot: str, pid: int, identity: str, local_host: str, local_boot: str) -> UnitClass:
    """Classify a recorded unit from what the row says and what this computer can see.

    Only the computer and boot session that wrote the row classify it. A different boot session proves every earlier
    process gone; a different computer proves nothing. On the owner's boot, a living runner makes it live; a gone
    runner with no non-zombie member left in its group makes it dead; a gone runner with members left is unknown, and
    nothing about it authorizes a signal.
    """
    if not host or not local_host or host != local_host:
        return UnitClass.UNKNOWN
    if not boot or not local_boot or local_boot == NO_IDENTITY:
        return UnitClass.UNKNOWN
    if boot != local_boot:
        return UnitClass.DEAD
    if not identity:
        return UnitClass.UNKNOWN
    if is_runner_alive(pid, identity):
        return UnitClass.LIVE
    return UnitClass.UNKNOWN if live_members(pid) else UnitClass.DEAD
