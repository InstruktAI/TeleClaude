"""Print the canonical agent list from ``teleclaude.agent_registry``.

The shell-consumable membership export ``bin/install.sh`` and
``src/Launcher/build.sh`` compare their own hand-listed agents against: an
unhandled canonical definition fails loudly instead of silently omitting the
new agent.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from teleclaude.agent_registry import AgentName


def print_canonical_list() -> None:
    """Print each canonical agent key on its own line."""
    for name in AgentName:
        print(name.value)


def main(argv: Sequence[str] | None = None) -> int:
    """Print the canonical agent list with `--list`."""
    args = list(argv) if argv is not None else sys.argv[1:]
    if not args or args[0] != "--list":
        print("usage: python -m teleclaude.codegen.agent_registry --list", file=sys.stderr)
        return 1
    print_canonical_list()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
