"""CLI entrypoint for the OS-managed todo watcher service."""

from __future__ import annotations

import argparse
import os
import sys

from teleclaude.logging_config import setup_logging
from teleclaude.services.todo_watcher import TodoWatcherProcess, WatcherNotification, post_watcher_notification


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Watch todo/worktree files and notify the TeleClaude daemon")
    parser.add_argument("project_root", help="Absolute project root to observe")
    parser.add_argument(
        "--debounce-seconds",
        type=float,
        default=1.0,
        help="Seconds to wait before batching accumulated changes",
    )
    return parser


def main() -> None:
    """Run the OS-managed todo watcher process."""
    args = _build_parser().parse_args()
    watcher_secret = os.environ.get("TELECLAUDE_WATCHER_SECRET", "")
    if not watcher_secret:
        print("TELECLAUDE_WATCHER_SECRET is required", file=sys.stderr)
        raise SystemExit(1)

    setup_logging()
    watcher = TodoWatcherProcess(args.project_root, debounce_seconds=args.debounce_seconds)

    async def _notify(payload: WatcherNotification) -> None:
        await post_watcher_notification(
            payload.project_root,
            payload.changed_paths,
            watcher_secret,
        )

    watcher.on_notification = _notify
    watcher.run()


if __name__ == "__main__":
    main()
