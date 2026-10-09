"""Entry point for ``python -m teleclaude.cli.telec``: the one seam where the identity gate is loaded on demand."""

from __future__ import annotations

from teleclaude.cli.telec.router import CommandClearance, main


def _clear(request: CommandClearance) -> None:
    from teleclaude.cli.telec.gate import (  # noqa: PLC0415 - entry seam: help and completion never load identity
        clear_command,
    )

    clear_command(request)


if __name__ == "__main__":
    main(_clear)
