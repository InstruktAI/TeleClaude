"""Shared CLI argument parsing helpers for telec handlers."""

from __future__ import annotations

from collections.abc import Callable


def parse_slug_after_args(args: list[str], usage_text: Callable[[], str]) -> tuple[str, list[str] | None]:
    """Parse a required slug plus optional ``--after`` dependency list."""
    slug: str | None = None
    after: list[str] | None = None
    index = 0

    while index < len(args):
        arg = args[index]
        if arg == "--after" and index + 1 < len(args):
            after = [part.strip() for part in args[index + 1].split(",") if part.strip()]
            index += 2
            continue
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(usage_text())
            raise SystemExit(1)
        if slug is not None:
            print("Only one slug is allowed.")
            print(usage_text())
            raise SystemExit(1)
        slug = arg
        index += 1

    if not slug:
        print("Missing required slug.")
        print(usage_text())
        raise SystemExit(1)
    return slug, after
