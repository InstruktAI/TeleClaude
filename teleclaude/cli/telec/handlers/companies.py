"""Handler for ``telec companies`` — company onboarding."""

from __future__ import annotations

from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.telec.surface import COMPANIES_ONBOARD
from teleclaude.company_setup import run_company_onboard

__all__ = ["_handle_companies"]


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
        parsed = parse_command_args(COMPANIES_ONBOARD, args[1:])
        positionals = parsed.positionals
        if len(positionals) > 1:
            print("Usage: telec companies onboard <name> [--slug <value>]")
            raise SystemExit(1)
        name = positionals[0] if positionals else None
        if not name:
            print("Usage: telec companies onboard <name> [--slug <value>]")
            raise SystemExit(1)
        run_company_onboard(name, parsed.value(F.FLAG_COMPANY_SLUG))
        return

    print(f"Unknown companies subcommand: {subcommand}")
    print(_usage("companies"))
    raise SystemExit(1)
