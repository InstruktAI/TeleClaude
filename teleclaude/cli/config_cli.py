"""Programmatic CLI for TeleClaude configuration.

Provides subcommands for AI agents and scripts to manage config:
  telec config env list|set
  telec config notify NAME --telegram on|off
  telec config validate

All subcommands support --json for machine-readable output.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from teleclaude.cli.config_handlers import check_env_vars, validate_all
from teleclaude.cli.session_auth import read_current_session_email
from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.help import _maybe_show_help
from teleclaude.cli.telec.surface import CONFIG_ENV_LIST, CONFIG_ENV_SET, CONFIG_NOTIFY, CONFIG_VALIDATE
from teleclaude.config._environment import write_environment_value
from teleclaude.constants import HUMAN_ROLE_CUSTOMER
from teleclaude.core.identity import get_identity_resolver
from teleclaude.paths import PROJECT_ENV_PATH


def _check_customer_guard() -> None:
    """Block customer-role sessions from mutating config commands."""
    email = read_current_session_email()
    role = get_identity_resolver().resolve_by_email(email).person_role if email else None
    if role == HUMAN_ROLE_CUSTOMER:
        print("Error: Permission denied. This operation requires member role or higher.")
        raise SystemExit(1)


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
        "notify": _handle_notify,
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
    statuses = check_env_vars()
    if use_json:
        data = [
            {
                "name": s.info.name,
                "service": s.info.adapter,
                "is_set": s.is_set,
                "description": s.info.description,
            }
            for s in statuses
        ]
        print(json.dumps(data, indent=2))
    else:
        for s in statuses:
            icon = "✓" if s.is_set else "✗"
            print(f"  {icon} {s.info.name} ({s.info.adapter}): {'set' if s.is_set else 'NOT SET'}")


def _env_set(pairs: list[str], use_json: bool) -> None:
    _check_customer_guard()
    if not pairs:
        print("Error: provide KEY=VALUE pairs")
        raise SystemExit(1)

    env_file = PROJECT_ENV_PATH
    results = []

    for pair in pairs:
        key, _, value = pair.partition("=")
        if not key or not value:
            continue
        _write_env_var(env_file, key, value)
        os.environ[key] = value  # fmt: skip  # guard: direct-env-read - allowed: environment-file management
        results.append({"name": key, "set": True})

    if use_json:
        print(json.dumps({"ok": True, "updated": results}))
    else:
        for r in results:
            print(f"  Set {r['name']} in .env")
        print("\n  Restart the daemon (make restart) to pick up changes.")


def _write_env_var(env_file: Path, name: str, value: str) -> None:
    """Set or update a variable in the .env file."""
    write_environment_value(env_file, name, value)


# --- Notify ---


def _handle_notify(args: list[str]) -> None:
    _check_customer_guard()
    parsed = parse_command_args(CONFIG_NOTIFY, args)
    use_json = parsed.has(F.FLAG_JSON_MACHINE_READABLE)
    msg = (
        "Notification toggling has been replaced by per-subscription settings. "
        "Edit subscriptions in person config instead."
    )
    if use_json:
        print(json.dumps({"error": msg}))
    else:
        print(msg)
    raise SystemExit(1)


# --- Validate ---


def handle_validate(args: list[str]) -> None:
    parsed = parse_command_args(CONFIG_VALIDATE, args)
    use_json = parsed.has(F.FLAG_JSON_MACHINE_READABLE)

    results = validate_all()

    if use_json:
        data = [
            {
                "area": r.area,
                "passed": r.passed,
                "errors": r.errors,
                "suggestions": r.suggestions,
            }
            for r in results
        ]
        all_passed = all(r.passed for r in results)
        print(json.dumps({"ok": all_passed, "results": data}, indent=2))
    else:
        for r in results:
            icon = "✓" if r.passed else "✗"
            print(f"  {icon} {r.area}")
            for err in r.errors:
                print(f"    Error: {err}")
            for sug in r.suggestions:
                print(f"    Fix: {sug}")

        all_passed = all(r.passed for r in results)
        if not all_passed:
            raise SystemExit(1)
