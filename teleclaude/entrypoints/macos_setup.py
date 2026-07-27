"""CLI entrypoint for macOS launcher/config setup tasks."""

from __future__ import annotations

import argparse
from pathlib import Path

from teleclaude.project_setup.macos_setup import (
    install_launchers,
    install_tmux_server_service,
    is_macos,
    run_permissions_probe,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="macOS setup helpers for TeleClaude init flows")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project root containing bin/*.app launchers",
    )
    parser.add_argument(
        "action",
        choices=("install-launchers", "install-tmux-server", "permissions-probe", "run-all"),
        help="Action to execute",
    )
    return parser


def main() -> int:
    """Run the selected macOS setup action against the requested project root."""
    parser = _build_parser()
    args = parser.parse_args()

    if not is_macos():
        print("macos-setup: non-macOS host; nothing to do")
        return 0

    project_root: Path = args.project_root.resolve()

    if args.action in ("install-launchers", "run-all"):
        install_launchers(project_root)

    if args.action in ("install-tmux-server", "run-all"):
        install_tmux_server_service()

    if args.action in ("permissions-probe", "run-all"):
        run_permissions_probe(project_root)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
