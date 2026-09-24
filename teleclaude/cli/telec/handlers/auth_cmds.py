"""Handlers for telec auth commands."""

from __future__ import annotations

import importlib
from typing import Any

from teleclaude.cli.session_auth import (
    clear_current_session_email,
    get_current_session_context,
    write_current_session_email,
)
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.tool_client import ToolAPIError, get_resolved_caller
from teleclaude.constants import MarkerState
from teleclaude.session_identity import inspect_session_identity_marker

_UNUSABLE_SESSION_IDENTITY_MESSAGE = "The current session carries no usable identity."
_NO_IDENTITY_FOR_TTY_MESSAGE = "No identity for current TTY ({tty}): {detail}"
_UNRESOLVED_ROLE = "unresolved"

__all__ = [
    "_handle_auth",
    "_handle_login",
    "_handle_logout",
    "_handle_whoami",
    "_requires_tui_login",
    "_role_for_email",
]


def _load_global_config() -> Any:
    return importlib.import_module("teleclaude.config.loader").load_global_config()


def _handle_auth(args: list[str]) -> None:
    """Handle telec auth subcommands."""
    if not args:
        print(_usage("auth"))
        return

    # Support conversational spelling: "telec auth who am i"
    if len(args) >= 3 and args[0] == "who" and args[1] == "am" and args[2].lower().rstrip("?") == "i":
        _handle_whoami(args[3:])
        return

    subcommand = args[0]
    sub_args = args[1:]

    if subcommand == "login":
        _handle_login(sub_args)
    elif subcommand == "whoami":
        _handle_whoami(sub_args)
    elif subcommand == "logout":
        _handle_logout(sub_args)
    else:
        print(f"Unknown auth subcommand: {subcommand}")
        print(_usage("auth"))
        raise SystemExit(1)


def _role_for_email(email: str) -> str | None:
    normalized = email.strip().lower()
    if not normalized:
        return None
    try:
        global_cfg = _load_global_config()
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    for person in global_cfg.people:
        if person.email.strip().lower() == normalized:
            return str(person.role)
    return None


def _requires_tui_login() -> bool:
    """Return True when terminal login is required before launching TUI."""
    try:
        global_cfg = _load_global_config()
    except (AttributeError, OSError, TypeError, ValueError):
        return False
    return len(global_cfg.people) > 1


def _handle_login(args: list[str]) -> None:
    """Handle telec auth login <email>."""
    if not args:
        print(_usage("auth", "login"))
        return
    if len(args) != 1 or args[0].startswith("-"):
        print("Error: login expects exactly one positional email.")
        print(_usage("auth", "login"))
        raise SystemExit(1)

    email = args[0]
    try:
        auth_state = write_current_session_email(email)
    except ValueError as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc

    role = _role_for_email(auth_state.email)
    role_suffix = f" ({role})" if role else ""
    print(f"Logged in as {auth_state.email}{role_suffix}.")
    print(f"TTY: {auth_state.context.tty}")
    print(f"Session auth file updated: {auth_state.context.auth_path}")


def _handle_whoami(args: list[str]) -> None:
    """Handle telec auth whoami."""
    if args:
        print(f"Unexpected arguments: {' '.join(args)}")
        print(_usage("auth", "whoami"))
        raise SystemExit(1)

    marker_state, session_id = inspect_session_identity_marker()
    if marker_state is not MarkerState.ABSENT:
        if marker_state is not MarkerState.VALID or not session_id:
            print(_UNUSABLE_SESSION_IDENTITY_MESSAGE)
            raise SystemExit(1)

        try:
            caller = get_resolved_caller()
            if caller.principal:
                print(f"Principal: {caller.principal}")
            if caller.role:
                print(f"Role: {caller.role}")
        except ToolAPIError as exc:
            print(f"Error resolving principal: {exc}")
            raise SystemExit(1) from exc
        return

    context = get_current_session_context()
    if context is None:
        print("Error: no terminal session detected (TTY unavailable).")
        raise SystemExit(1)

    try:
        caller = get_resolved_caller()
    except ToolAPIError as exc:
        if exc.status_code == 401:
            print(_NO_IDENTITY_FOR_TTY_MESSAGE.format(tty=context.tty, detail=exc.message))
            return
        print(f"Error resolving identity: {exc.message}")
        raise SystemExit(1) from exc

    print(f"Email: {caller.email}")
    print(f"Role: {caller.role or _UNRESOLVED_ROLE}")
    print(f"TTY: {context.tty}")
    print(f"Session auth file: {context.auth_path}")


def _handle_logout(args: list[str]) -> None:
    """Handle telec auth logout."""
    if args:
        print(f"Unexpected arguments: {' '.join(args)}")
        print(_usage("auth", "logout"))
        raise SystemExit(1)

    context = get_current_session_context()
    if context is None:
        print("Error: no terminal session detected (TTY unavailable).")
        raise SystemExit(1)

    removed = clear_current_session_email()
    if removed:
        print(f"Cleared login for TTY {context.tty}.")
    else:
        print(f"No login file found for TTY {context.tty}.")
