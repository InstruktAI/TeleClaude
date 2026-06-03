"""Shared helpers for launching sessions from the TUI."""

from __future__ import annotations

import curses
import os
import shlex
import subprocess
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.api_models import CreateSessionResponseDTO
from teleclaude.config import config
from teleclaude.core.shell_identity import require_shell_safe_identifier

if TYPE_CHECKING:
    from teleclaude.core.cache import DaemonCache

logger = get_logger(__name__)


class RemotePeerIdentityUnavailableError(RuntimeError):
    """Raised when a peer's ComputerInfo hasn't propagated yet.

    Fail-fast for the cross-computer attach surface: if the user asked to
    attach to a peer session but the peer's user/host aren't in
    the cache, we cannot build an honest SSH command — and silently falling
    back to a local attach (which targets the wrong tmux server) is a
    misleading-feedback regression. The caller decides how to surface this
    to the user.
    """


def _resolve_peer_target(cache: DaemonCache | None, computer: str | None) -> tuple[str, str] | None:
    """Return ``(user, host)`` when ``computer`` is a known remote peer.

    Returns ``None`` when the session is local (no remote SSH-wrap needed).
    Raises :class:`RemotePeerIdentityUnavailableError` when the session is
    remote but the peer's identity hasn't propagated yet — the caller must
    decide whether to surface or retry, not silently degrade.
    """
    if computer is None or computer == config.computer.name:
        return None
    if cache is None:
        raise RemotePeerIdentityUnavailableError(f"cache unavailable; cannot resolve peer {computer!r}")
    info = next((c for c in cache.get_computers() if c.name == computer), None)
    if info is None or info.is_local:
        raise RemotePeerIdentityUnavailableError(f"peer {computer!r} not in cache yet")
    if not info.user or not info.host:
        raise RemotePeerIdentityUnavailableError(f"peer {computer!r} cache entry missing user/host")
    return (
        require_shell_safe_identifier(info.user, "peer user"),
        require_shell_safe_identifier(info.host, "peer host"),
    )


def attach_tmux_session(
    tmux_session_name: str | None,
    stdscr: object,
    *,
    computer: str | None = None,
    cache: DaemonCache | None = None,
) -> bool:
    """Attach a tmux session in a right-side split pane.

    For local sessions the split runs ``<tmux> attach -t <name>``. For peer
    sessions the same split runs ``ssh -t <user>@<host> 'tmux attach -t <name>'``,
    relying on SSH key auth between computers (documented prerequisite — see
    ``project/procedure/multi-computer-setup``).

    Returns True if a split was opened. Returns False — and logs a warning
    naming the peer — when the requested attach is remote but the peer's
    identity hasn't propagated yet; the caller can re-render with a status
    message and retry once the heartbeat populates ComputerInfo.
    """
    if not tmux_session_name:
        return False

    if not os.environ.get("TMUX"):
        return False

    local_tmux = config.computer.tmux_binary
    try:
        safe_tmux_session_name = require_shell_safe_identifier(tmux_session_name, "tmux_session_name")
        remote_target = _resolve_peer_target(cache, computer)
    except (RemotePeerIdentityUnavailableError, ValueError) as exc:
        logger.warning(
            "Remote attach unavailable; not falling back to local tmux",
            computer=computer,
            session=tmux_session_name,
            reason=str(exc),
        )
        return False

    if remote_target is None:
        inner = f"{local_tmux} attach -t {safe_tmux_session_name}"
    else:
        user, host = remote_target
        inner = f"ssh -t {shlex.quote(f'{user}@{host}')} {shlex.quote(f'tmux attach -t {safe_tmux_session_name}')}"

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
