"""Handler for telec config commands."""

from __future__ import annotations

import sys

from teleclaude.cli.telec.help import _usage

__all__ = [
    "_handle_config",
]


def _handle_config(args: list[str]) -> None:
    """Handle telec config command.

    Requires explicit subcommands. Use `telec config wizard` to open the
    interactive configuration UI.
    """

    if not args:
        print(_usage("config"))
        return

    subcommand = args[0]
    if subcommand == "wizard":
        if len(args) > 1:
            print(f"Unexpected arguments for config wizard: {' '.join(args[1:])}")
            print(_usage("config", "wizard"))
            raise SystemExit(1)
        if not sys.stdin.isatty():
            print("Error: Interactive config requires a terminal.")
            raise SystemExit(1)
        from teleclaude.cli.telec._run_tui import _run_tui_config_mode

        _run_tui_config_mode(guided=True)
    elif subcommand in ("get", "patch"):
        from teleclaude.cli.config_cmd import handle_config_command

        handle_config_command(args)
    elif subcommand == "cartridges":
        from teleclaude.cli.cartridge_cli import handle_cartridge_cli

        handle_cartridge_cli(args[1:])
    elif subcommand in ("people", "env", "notify", "validate", "invite"):
        from teleclaude.cli.config_cli import handle_config_cli

        handle_config_cli(args)
    else:
        print(f"Unknown config subcommand: {subcommand}")
        print(_usage("config"))
        raise SystemExit(1)
