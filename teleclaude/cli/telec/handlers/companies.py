"""Handler for ``telec companies`` — company onboarding."""

from __future__ import annotations

from teleclaude.cli.telec.help import _usage
from teleclaude.company_setup import run_company_onboard

__all__ = ["_handle_companies"]


def _parse_onboard_args(args: list[str]) -> tuple[str | None, str | None]:
    """Parse ``<name> [--slug <slug>]`` into ``(name, slug)``."""
    name: str | None = None
    slug: str | None = None
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--slug":
            slug = args[index + 1] if index + 1 < len(args) else None
            index += 2
            continue
        if name is None:
            name = token
        index += 1
    return name, slug


def _handle_companies(args: list[str]) -> None:
    """Handle telec companies commands."""
    if not args or args[0] in ("-h", "--help"):
        print(_usage("companies"))
        return

    subcommand = args[0]
    if subcommand == "onboard":
        if len(args) > 1 and args[1] in ("-h", "--help"):
            print(_usage("companies", "onboard"))
            return
        name, slug = _parse_onboard_args(args[1:])
        if not name:
            print("Usage: telec companies onboard <name> [--slug <value>]")
            raise SystemExit(1)
        run_company_onboard(name, slug)
        return

    print(f"Unknown companies subcommand: {subcommand}")
    print(_usage("companies"))
    raise SystemExit(1)
