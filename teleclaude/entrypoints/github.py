"""Native GitHub command entry; registration and installation are owned separately."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Sequence

from teleclaude.github.posting import execute_native_github
from teleclaude.project_root import resolve_invocation_cwd

_EXIT_CANCELLED = 130


def main(argv: Sequence[str] | None = None) -> int:
    """Execute this native invocation without exposing actor or transport selectors."""
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    try:
        return asyncio.run(
            execute_native_github(
                arguments,
                directory=resolve_invocation_cwd(),
                stdin=sys.stdin.buffer,
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        return _EXIT_CANCELLED


if __name__ == "__main__":
    raise SystemExit(main())
