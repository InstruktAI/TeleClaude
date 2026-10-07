"""CLI entrypoint for macOS launcher/config setup tasks."""

from __future__ import annotations

import argparse
from pathlib import Path

from teleclaude.core.reconciliation.launcher_identity import LauncherIdentityIntent
from teleclaude.install.launcher_identity import run_and_present_launcher_identity
from teleclaude.project_setup.macos_setup import (
    install_tmux_server_service,
    is_macos,
    run_permissions_probe,
)

_DEFER_CHANGES_FLAG = "--defer-changes"
_STORE_TRUE_ACTION = "store_true"
_DEFER_CHANGES_HELP = "Deploy no changed service definition and reload no running service; name each drift instead"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="macOS setup helpers for TeleClaude init flows")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project root containing bin/*.app launchers",
    )
    parser.add_argument(
        _DEFER_CHANGES_FLAG,
        action=_STORE_TRUE_ACTION,
        help=_DEFER_CHANGES_HELP,
    )
    parser.add_argument(
        "action",
        choices=("install-launchers", "install-tmux-server", "permissions-probe", "run-all"),
        help="Action to execute",
    )
    return parser


def main() -> int:
    """Run the selected macOS setup action against the requested project root.

    Returns 1 when the permission probe found denied paths, so the caller can
    surface the grants the human still has to give.
    """
    parser = _build_parser()
    args = parser.parse_args()

    if not is_macos():
        print("macos-setup: non-macOS host; nothing to do")
        return 0

    project_root: Path = args.project_root.resolve()

    if args.action in ("install-launchers", "run-all"):
        result = run_and_present_launcher_identity(LauncherIdentityIntent.CONVERGE, project_root)
        if result.failure_cause is not None:
            return 1

    if args.action in ("install-tmux-server", "run-all"):
        install_tmux_server_service(defer_changes=args.defer_changes)

    if args.action in ("permissions-probe", "run-all"):
        if not run_permissions_probe(project_root):
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
