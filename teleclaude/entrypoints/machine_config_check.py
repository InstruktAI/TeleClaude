"""Answer whether this computer's machine configuration loads, before the daemon is started on it.

The daemon cannot boot on a machine configuration that does not load, so service start and
restart ask this first and leave a running daemon running when the answer is no.
"""

from __future__ import annotations

import sys

from teleclaude.config import config
from teleclaude.config.errors import ConfigLoadError

_REFUSAL = "Machine configuration does not load; the daemon was not (re)started: {error}"
_FAILURE_EXIT = 1


def main() -> None:
    """Exit zero when the machine configuration loads, otherwise print why and exit non-zero."""
    try:
        _ = config.computer.name
    except (ConfigLoadError, FileNotFoundError) as error:
        print(_REFUSAL.format(error=error), file=sys.stderr)
        raise SystemExit(_FAILURE_EXIT) from error


if __name__ == "__main__":
    main()
