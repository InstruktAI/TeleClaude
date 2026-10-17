"""What names one process, and one boot of one computer, so a recorded process can be told from another.

A pid names a process only until the process ends. A process's identity is the start identity the operating system
gives it, read the same way each time and compared for equality: on Linux the raw start time in clock ticks since
boot (field 22 of its ``stat``), which does not move with the wall clock, and elsewhere the start time the system
reports. The boot session is the host's immutable boot identity. Neither is ever ordered against another to prove
anything; they are equal or they are not (``local/projects/teleclaude/design/process-lifecycle``).
"""

from __future__ import annotations

import subprocess
import sys
from enum import StrEnum
from pathlib import Path
from typing import Final

import psutil

LINUX: Final = "linux"
PROC_STAT_TEMPLATE: Final = "/proc/{pid}/stat"
BOOT_ID_PATH: Final = Path("/proc/sys/kernel/random/boot_id")
STAT_AFTER_COMM_START_FIELD: Final = 3
STAT_START_TIME_FIELD: Final = 22
SYSCTL_BOOT_SESSION: Final = ("sysctl", "-n", "kern.bootsessionuuid")
SYSCTL_TIMEOUT_SECONDS: Final = 5
NO_IDENTITY: Final = ""


_BOOT_SESSION: list[str] = []


def boot_session() -> str:
    """The identity of this boot of this computer; empty when the host offers none right now.

    Only a successful read is remembered, because the identity is immutable; a failed or timed-out read is retried.
    """
    if _BOOT_SESSION:
        return _BOOT_SESSION[0]
    read = _read_boot_session()
    if read:
        _BOOT_SESSION.append(read)
    return read


def _read_boot_session() -> str:
    if sys.platform.startswith(LINUX):
        try:
            return BOOT_ID_PATH.read_text(encoding="utf-8").strip()
        except OSError:
            return NO_IDENTITY
    try:
        completed = subprocess.run(  # the kernel's boot session is only reachable through sysctl
            SYSCTL_BOOT_SESSION, capture_output=True, text=True, timeout=SYSCTL_TIMEOUT_SECONDS, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return NO_IDENTITY
    return completed.stdout.strip() if completed.returncode == 0 else NO_IDENTITY


def _linux_start_ticks(pid: int) -> str:
    """Field 22 of the process's stat, read after the command name, which may itself hold spaces and brackets."""
    try:
        stat = Path(PROC_STAT_TEMPLATE.format(pid=pid)).read_text(encoding="utf-8")
    except OSError:
        return NO_IDENTITY
    fields = stat[stat.rindex(")") + 1 :].split()
    index = STAT_START_TIME_FIELD - STAT_AFTER_COMM_START_FIELD
    return fields[index] if len(fields) > index else NO_IDENTITY


def start_identity(pid: int) -> str:
    """The process's start identity as the system gives it now; empty when the process is gone."""
    if sys.platform.startswith(LINUX):
        return _linux_start_ticks(pid)
    try:
        created: float = psutil.Process(pid).create_time()
    except psutil.Error:
        return NO_IDENTITY
    return repr(created)


class ProcessState(StrEnum):
    """What a probe of a recorded process found: the same process, positively ended or replaced, or not known."""

    SAME = "same"
    ENDED = "ended"
    UNKNOWN = "unknown"


def probe_process(pid: int, identity: str) -> ProcessState:
    """Whether the process recorded as ``pid`` with start ``identity`` still runs.

    ``ENDED`` is positive evidence: the system has no such process, or the pid now has another start identity. A probe
    that could not read the process (access refused, an unreadable record) is ``UNKNOWN`` and proves nothing.
    """
    if sys.platform.startswith(LINUX):
        try:
            stat = Path(PROC_STAT_TEMPLATE.format(pid=pid)).read_text(encoding="utf-8")
        except FileNotFoundError:
            return ProcessState.ENDED
        except OSError:
            return ProcessState.UNKNOWN
        fields = stat[stat.rindex(")") + 1 :].split()
        index = STAT_START_TIME_FIELD - STAT_AFTER_COMM_START_FIELD
        if len(fields) <= index:
            return ProcessState.UNKNOWN
        return ProcessState.SAME if fields[index] == identity else ProcessState.ENDED
    try:
        created = repr(psutil.Process(pid).create_time())
    except psutil.NoSuchProcess:
        return ProcessState.ENDED
    except psutil.Error:
        return ProcessState.UNKNOWN
    return ProcessState.SAME if created == identity else ProcessState.ENDED
