"""Shared helpers for launching sessions from the TUI."""

from __future__ import annotations

import curses
import os
import shlex
import subprocess
from typing import TYPE_CHECKING

from teleclaude.api_models import CreateSessionResponseDTO
from teleclaude.config import config

if TYPE_CHECKING:
    from teleclaude.core.cache import DaemonCache


def _resolve_peer_target(cache: DaemonCache | None, computer: str | None) -> tuple[str, str, str] | None:
    """Return ``(user, host, tmux_binary)`` when ``computer`` is a known remote peer.

    Returns ``None`` when the session is local (no remote SSH-wrap needed) or
    when the peer's identity hasn't been populated yet (no usable target —
    fall back to local attach).
    """
    if computer is None or computer == config.computer.name:
        return None
    if cache is None:
        return None
    info = next((c for c in cache.get_computers() if c.name == computer), None)
    if info is None or info.is_local:
        return None
    if not info.user or not info.host or not info.tmux_binary:
        return None
    return info.user, info.host, info.tmux_binary


def attach_tmux_session(
    tmux_session_name: str | None,
    stdscr: object,
    *,
    computer: str | None = None,
    cache: DaemonCache | None = None,
) -> bool:
    """Attach a tmux session in a right-side split pane.

    For local sessions the split runs ``<tmux> attach -t <name>``. For peer
    sessions the same split runs ``ssh -t <user>@<host> '<peer-tmux> attach -t <name>'``,
    relying on SSH key auth between computers (documented prerequisite — see
    ``project/procedure/multi-computer-setup``).

    Returns True if a split was opened.
    """
    if not tmux_session_name:
        return False

    if not os.environ.get("TMUX"):
        return False

    local_tmux = config.computer.tmux_binary
    remote_target = _resolve_peer_target(cache, computer)
    if remote_target is None:
        inner = f"{local_tmux} attach -t {tmux_session_name}"
    else:
        user, host, peer_tmux = remote_target
        # quote individually so spaces/special chars in tmux_binary don't break the remote shell
        inner = f"ssh -t {shlex.quote(f'{user}@{host}')} {shlex.quote(f'{peer_tmux} attach -t {tmux_session_name}')}"

    curses.def_prog_mode()
    curses.endwin()
    subprocess.run(
        [local_tmux, "split-window", "-h", "-p", "60", inner],
        check=False,
    )
    curses.reset_prog_mode()
    stdscr.refresh()  # type: ignore[attr-defined]
    return True


def attach_tmux_from_result(
    result: CreateSessionResponseDTO,
    stdscr: object,
    *,
    cache: DaemonCache | None = None,
) -> bool:
    """Attach tmux session from create_session API result.

    Honors ``result.computer`` so sessions created on a remote peer are
    attached via SSH wrap rather than treated as local.
    """
    tmux_session_name = result.tmux_session_name
    if not tmux_session_name:
        return False
    return attach_tmux_session(tmux_session_name, stdscr, computer=result.computer, cache=cache)
