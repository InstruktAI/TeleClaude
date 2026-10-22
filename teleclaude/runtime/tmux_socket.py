"""The socket of the tmux server used by platform-managed panes."""

from __future__ import annotations

import os
from pathlib import Path

_TMPDIR_ENV = "TMUX_TMPDIR"
_DEFAULT_TMPDIR = "/tmp"
_SOCKET_DIRECTORY = "tmux-{uid}"
_SOCKET_NAME = "default"


def own_tmux_socket_path() -> Path | None:
    """Resolve the platform's default server independently of the TMUX selector."""
    tmpdir = os.getenv(_TMPDIR_ENV) or _DEFAULT_TMPDIR  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
    directory = _SOCKET_DIRECTORY.format(uid=os.getuid())
    try:
        return (Path(tmpdir) / directory / _SOCKET_NAME).resolve(strict=True)
    except OSError:
        return None
