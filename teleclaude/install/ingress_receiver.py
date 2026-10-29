"""Whether this computer's ingress receiver units are installed (ADR-0148).

The installed units decide who serves the inbound endpoints: the receiver while they are installed, the daemon
otherwise. The installation deploys or withdraws them, per ``computer.ingress_receiver``, only at a start, an
install or a restart, so a configuration edit alone never leaves the endpoints without a server.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SYSTEMD_SOCKET = Path("/etc/systemd/system") / "teleclaude-ingress-receiver.socket"


def receiver_units_installed() -> bool:
    """Whether the ingress receiver's service definition is installed on this computer (systemd only)."""
    return sys.platform == "linux" and _SYSTEMD_SOCKET.is_file()
