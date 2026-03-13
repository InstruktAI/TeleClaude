"""Handlers for telec auth commands."""
from __future__ import annotations

import asyncio
import os

from teleclaude.cli.api_client import TelecAPIClient
from teleclaude.cli.session_auth import (
    clear_current_session_email,
    get_current_session_context,
    read_current_session_email,
    write_current_session_email,
)
from teleclaude.cli.telec._shared import TMUX_ENV_KEY
from teleclaude.cli.telec.help import _usage



__all__ = [
    "_handle_auth",
    "_role_for_email",
    "_requires_tui_login",
    "_handle_login",
    "_handle_whoami",
    "_handle_logout",
]

def _handle_auth(args: list[str]) -> None:
    """Handle telec auth subcommands."""
    if os.environ.get(TMUX_ENV_KEY):
        print("Error: telec auth is unavailable inside tmux sessions.")
        print("Run it from a plain SSH terminal before starting telec.")
        raise SystemExit(1)

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
        # Import lazily so CLI commands that do not require config can start
        # even when runtime config is invalid or unavailable.
        from teleclaude.config.loader import load_global_config

        global_cfg = load_global_config()
    except Exception:
        return None
    for person in global_cfg.people:
        if person.email.strip().lower() == normalized:
            return person.role
    return None


def _requires_tui_login() -> bool:
    """Return True when terminal login is required before launching TUI."""
    try:
        from teleclaude.config.loader import load_global_config

        global_cfg = load_global_config()
    except Exception:
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

    # Agent session path: resolve principal from daemon via session token.
    session_token = os.environ.get("TELEC_SESSION_TOKEN")
    if session_token:

        async def _resolve_principal() -> None:
            api = TelecAPIClient()
            await api.connect()
            try:
                data = await api.get_auth_whoami()
            finally:
                await api.close()
            principal = data.get("principal")
            role = data.get("role")
            if principal:
                print(f"Principal: {principal}")
            if role:
                print(f"Role: {role}")

        try:
            asyncio.run(_resolve_principal())
        except Exception as exc:
            print(f"Error resolving principal: {exc}")
            raise SystemExit(1) from exc
        return

    # Terminal/TUI path: read email from TTY auth file.
    context = get_current_session_context()
    if context is None:
        print("Error: no terminal session detected (TTY unavailable).")
        raise SystemExit(1)

    email = read_current_session_email()
    if not email:
        print(f"No login set for current TTY ({context.tty}).")
        return

    role = _role_for_email(email) or "unresolved"
    print(f"Email: {email}")
    print(f"Role: {role}")
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
