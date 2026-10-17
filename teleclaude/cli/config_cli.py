"""Programmatic CLI for TeleClaude configuration.

Provides subcommands for AI agents and scripts to manage config:
  telec config env list|set
  telec config validate

All subcommands support --json for machine-readable output.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, cast

from teleclaude.cli.config_cmd import run_config_request
from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.help import _maybe_show_help
from teleclaude.cli.telec.surface import CONFIG_ENV_LIST, CONFIG_ENV_SET, CONFIG_VALIDATE
from teleclaude.config.operation_requests import VALIDATE_NOTES_KEY, ConfigRequest, ConfigVerb


def handle_config_cli(args: list[str]) -> None:
    """Route config subcommands to handlers."""
    if not args:
        print("Error: subcommand required. Use 'telec config --help'.")
        raise SystemExit(1)

    sub = args[0]
    rest = args[1:]

    # Intercept --help/-h at any level
    if sub in ("--help", "-h") or "--help" in rest or "-h" in rest:
        _maybe_show_help("config", args)
        return

    handlers = {
        "env": _handle_env,
        "validate": handle_validate,
    }

    handler = handlers.get(sub)
    if not handler:
        print(f"Unknown config subcommand: {sub}")
        raise SystemExit(1)

    handler(rest)


# --- Env ---


def _handle_env(args: list[str]) -> None:
    if not args:
        print("Usage: telec config env <list|set> [options]")
        raise SystemExit(1)

    action = args[0]
    rest = args[1:]

    if action == "list":
        parsed = parse_command_args(CONFIG_ENV_LIST, rest)
        _env_list(parsed.has(F.FLAG_JSON_MACHINE_READABLE))
    elif action == "set":
        parsed = parse_command_args(CONFIG_ENV_SET, rest)
        pairs = [token for token in parsed.positionals if "=" in token]
        _env_set(pairs, parsed.has(F.FLAG_JSON_MACHINE_READABLE))
    else:
        print(f"Unknown env action: {action}")
        raise SystemExit(1)


def _env_list(use_json: bool) -> None:
    payload = run_config_request(ConfigRequest(verb=ConfigVerb.ENV_LIST, request_id=str(uuid.uuid4())))
    variables = cast(list[dict[str, object]], payload["variables"])  # guard: loose-dict - wire payload rows
    if use_json:
        print(json.dumps(variables, indent=2))
    else:
        for variable in variables:
            icon = "✓" if variable["is_set"] else "✗"
            state = "set" if variable["is_set"] else "NOT SET"
            print(f"  {icon} {variable['name']} ({variable['service']}): {state}")


def _env_set(pairs: list[str], use_json: bool) -> None:
    if not pairs:
        print("Error: provide KEY=VALUE pairs")
        raise SystemExit(1)

    request = ConfigRequest(
        verb=ConfigVerb.ENV_SET,
        request_id=str(uuid.uuid4()),
        env_pairs=[list(pair.partition("=")[::2]) for pair in pairs],
    )
    updated = cast(list[str], run_config_request(request)["updated"])

    if use_json:
        print(json.dumps({"ok": True, "updated": [{"name": name, "set": True} for name in updated]}))
    else:
        for name in updated:
            print(f"  Set {name} in .env")
        print("\n  Restart the daemon (make restart) to pick up changes.")


# --- Validate ---

_NOTE_LINE = "    Note: {note}"


def handle_validate(args: list[str]) -> None:
    parsed = parse_command_args(CONFIG_VALIDATE, args)
    use_json = parsed.has(F.FLAG_JSON_MACHINE_READABLE)

    payload = run_config_request(ConfigRequest(verb=ConfigVerb.VALIDATE, request_id=str(uuid.uuid4())))
    results = cast(list[dict[str, Any]], payload["results"])  # guard: loose-dict - wire payload rows
    all_passed = all(result["passed"] for result in results)

    if use_json:
        print(json.dumps({"ok": all_passed, "results": results}, indent=2))
    else:
        for result in results:
            icon = "✓" if result["passed"] else "✗"
            print(f"  {icon} {result['area']}")
            for error in result["errors"]:
                print(f"    Error: {error}")
            for suggestion in result["suggestions"]:
                print(f"    Fix: {suggestion}")
            for note in result[VALIDATE_NOTES_KEY]:
                print(_NOTE_LINE.format(note=note))

        if not all_passed:
            raise SystemExit(1)
