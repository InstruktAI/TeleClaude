"""Registry of live TUI processes, and the reload signal addressed to them.

The TUI app is the only process that installs a ``SIGUSR2`` handler, so it is
the only process the reload signal may reach — everywhere else the signal's
default disposition terminates the target. A running TUI therefore records its
own pid here and drops the record when it exits, and a caller wanting to reload
reads this registry.

Identity is asserted by the process itself rather than inferred from a command
line. A command line records how a process was launched — through the wrapper,
through ``uv run``, through the interpreter directly — and every one of those
spellings names the same thing, while a subcommand invocation of the same
entrypoint is a different thing wearing the same spelling.

A record is withdrawn before the reload's ``execvp``, not carried across it.
The exec hands the pid to the launch wrapper, which outlives the handoff and
answers no signal, and the TUI returns as that wrapper's child under a new pid;
a record kept across the handoff would therefore name the wrapper, and signalling
a wrapper terminates it.

A record outlives its process only when that process dies without unwinding;
readers reap such a record on sight. Between the crash and the next read the
pid could in principle be recycled onto an unrelated process, which is the
residual risk of pid-keyed identity and the reason every ordinary exit
deregisters.
"""

from __future__ import annotations

import os
import signal
from pathlib import Path

from teleclaude.paths import TUI_PIDS_DIR

__all__ = [
    "deregister_tui",
    "live_tui_pids",
    "register_tui",
    "signal_tui_reload",
]


def register_tui(pid: int) -> None:
    """Record ``pid`` as a live TUI. Idempotent."""
    TUI_PIDS_DIR.mkdir(parents=True, exist_ok=True)
    _record_path(pid).touch()


def deregister_tui(pid: int) -> None:
    """Drop ``pid``'s record. A missing record is already the desired state."""
    _record_path(pid).unlink(missing_ok=True)


def live_tui_pids() -> list[int]:
    """Return the recorded pids still running, reaping the records that are not."""
    live: list[int] = []
    for record in _records():
        pid = _record_pid(record)
        if pid is not None and _is_running(pid):
            live.append(pid)
            continue
        record.unlink(missing_ok=True)
    return sorted(live)


def signal_tui_reload() -> list[int]:
    """Send the reload signal to every live TUI and return the pids reached.

    A process that has exited between the liveness check and the signal is
    reaped. Any other failure to signal — a permission boundary above all —
    says nothing about whether the TUI is there, so it is raised rather than
    answered with a deletion and an empty result.
    """
    reached: list[int] = []
    for pid in live_tui_pids():
        try:
            os.kill(pid, signal.SIGUSR2)
        except ProcessLookupError:
            deregister_tui(pid)
            continue
        reached.append(pid)
    return reached


def _record_path(pid: int) -> Path:
    return TUI_PIDS_DIR / str(pid)


def _records() -> list[Path]:
    """Return the record files. An absent directory means no TUI has run yet."""
    if not TUI_PIDS_DIR.exists():
        return []
    return [entry for entry in TUI_PIDS_DIR.iterdir() if entry.is_file()]


def _record_pid(record: Path) -> int | None:
    try:
        return int(record.name)
    except ValueError:
        return None


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
