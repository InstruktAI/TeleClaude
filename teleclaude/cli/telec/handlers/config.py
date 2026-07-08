"""Handler for telec config commands."""

from __future__ import annotations

import asyncio
import importlib
import sys

from teleclaude.cli.api_client import APIError, TelecAPIClient
from teleclaude.cli.telec.help import _usage

__all__ = [
    "_handle_config",
]

TTS_DEPROVISION_CONFIRM = "TTS disabled and TTS-exclusive dependencies removed."


def _run_tui_config_mode(*, guided: bool) -> None:
    run_tui_config_mode = importlib.import_module("teleclaude.cli.telec._run_tui")._run_tui_config_mode
    run_tui_config_mode(guided=guided)


def _handle_config_command(args: list[str]) -> None:
    importlib.import_module("teleclaude.cli.config_cmd").handle_config_command(args)


def _handle_legacy_config_cli(args: list[str]) -> None:
    importlib.import_module("teleclaude.cli.config_cli").handle_config_cli(args)


async def _deprovision_tts() -> None:
    """Call the daemon's TTS deprovision action."""
    api = TelecAPIClient()
    await api.connect()
    try:
        await api.deprovision_tts()
    finally:
        await api.close()


def _handle_config_tts(args: list[str]) -> None:
    """Handle telec config tts commands."""
    if not args or args[0] != "deprovision":
        print(_usage("config", "tts"))
        raise SystemExit(1)

    tts_args = args[1:]
    if "--yes" not in tts_args:
        print(
            "This disables TTS, removes the TTS-exclusive optional dependencies "
            "(elevenlabs, the mlx text pipeline), and leaves dependencies shared "
            "with STT/summarization installed. Re-enabling TTS afterward lazily "
            "re-provisions the removed dependencies.\n"
            "Rerun with --yes to confirm: telec config tts deprovision --yes"
        )
        raise SystemExit(1)

    try:
        asyncio.run(_deprovision_tts())
    except APIError as exc:
        print(f"Error: {exc.detail}")
        raise SystemExit(1) from exc
    print(TTS_DEPROVISION_CONFIRM)


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
        _run_tui_config_mode(guided=True)
    elif subcommand in ("get", "patch"):
        _handle_config_command(args)
    elif subcommand == "tts":
        _handle_config_tts(args[1:])
    elif subcommand in ("people", "env", "notify", "validate"):
        _handle_legacy_config_cli(args)
    else:
        print(f"Unknown config subcommand: {subcommand}")
        print(_usage("config"))
        raise SystemExit(1)
