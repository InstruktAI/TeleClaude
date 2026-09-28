"""Validate every configuration document for installation.

Installation runs as the machine owner, who already holds every file this
reads, so it validates through this module rather than the caller-gated CLI.
"""

from __future__ import annotations

from teleclaude.cli.config_cli import handle_validate


def main() -> None:
    """Report each configuration area and exit non-zero when any fails."""
    handle_validate([])


if __name__ == "__main__":
    main()
