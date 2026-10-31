"""Report the optional components the running daemon serves without, as the invoking caller may see them.

`bin/daemon-control.sh status` delegates here. The health answer is read with the invoking caller's carried
identity, so a degraded project is reported to a caller whose reach admits it and to no one else.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from teleclaude.caller_identity import CarriedIdentity
from teleclaude.cli.session_auth import resolve_cli_identity
from teleclaude.runtime.daemon_shutdown_control import ControlOutcome, ControlRefusal, read_health


def report_degraded(socket_path: str) -> int:
    """Print each optional component the daemon serves without; exit OK only when there is none."""
    headers = CarriedIdentity.from_cli_identity(resolve_cli_identity()).to_headers()
    degraded = read_health(socket_path, headers).degraded
    if degraded is None:
        raise ControlRefusal(ControlOutcome.UNSUPPORTED)
    for line in degraded:
        print(line)
    return int(ControlOutcome.DEGRADED) if degraded else int(ControlOutcome.OK)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True)
    args = parser.parse_args(argv)
    try:
        return report_degraded(args.socket)
    except ControlRefusal as refusal:
        print(refusal, file=sys.stderr)
        return int(refusal.outcome)


if __name__ == "__main__":
    sys.exit(main())
