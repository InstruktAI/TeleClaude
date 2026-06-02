"""Reap subprocess descendants that a test or runner leaves attached to this process.

The per-test pytest timeout flags hung tests; that flag is the sole authority.
This module exists so the worker can actually finish and *print* the flag, by
killing any subprocess still attached to it at teardown — preventing the orphan
from holding the worker's stdout pipe open and deadlocking xdist.

Scope: strictly descendants of the current process (the xdist worker). Cannot
see processes that live in a different subtree (the daemon's agent tmux
sessions are children of the daemon, never of the worker). Cannot reap a child
that deliberately daemonizes and reparents away from this process (e.g. a tmux
server started with ``-d``); those require fixture-owned cleanup by a unique
identifier (socket name, working dir, env marker).
"""

from __future__ import annotations

import psutil


def snapshot_descendants() -> set[int]:
    """Return the PIDs of every process currently attached as a descendant of this process."""
    try:
        return {p.pid for p in psutil.Process().children(recursive=True)}
    except psutil.Error:
        return set()


def reap_new_descendants(before: set[int], *, grace_seconds: float = 0.5) -> list[int]:
    """SIGTERM-then-SIGKILL every descendant whose PID is not in ``before``.

    Returns the PIDs of processes that were targeted (whether or not the kill
    fully reaped them). Caller decides whether to assert on the result.
    """
    try:
        current = psutil.Process().children(recursive=True)
    except psutil.Error:
        return []
    leaked = [p for p in current if p.pid not in before]
    if not leaked:
        return []
    for proc in leaked:
        try:
            proc.terminate()
        except psutil.Error:
            pass
    _gone, alive = psutil.wait_procs(leaked, timeout=grace_seconds)
    for proc in alive:
        try:
            proc.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(alive, timeout=grace_seconds)
    return [p.pid for p in leaked]
