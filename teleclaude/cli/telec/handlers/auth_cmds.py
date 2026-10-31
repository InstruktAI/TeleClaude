"""Handlers for telec auth commands."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from teleclaude.caller_identity import (
    NoIdentityCliCaller,
    ProjectPath,
    SystemCliCaller,
    authorizing_role,
)
from teleclaude.cli.session_auth import (
    ResolvedCliIdentity,
    clear_current_session_email,
    get_current_session_context,
    no_identity_refusal,
    resolve_cli_identity,
    write_current_session_email,
)
from teleclaude.cli.telec.help import _usage
from teleclaude.paths import invocation_cwd

if TYPE_CHECKING:
    from teleclaude.config.schema import GlobalConfig
    from teleclaude.core.models import Session
    from teleclaude.core.organization import SessionCompanyContext, SessionCompanyState

_NO_IDENTITY_FOR_TTY_MESSAGE = "No identity for current TTY ({tty}): {detail}"
_UNRESOLVED_ROLE = "unresolved"

__all__ = [
    "_handle_auth",
    "_handle_login",
    "_handle_logout",
    "_handle_whoami",
    "_role_for_email",
]


def _load_global_config() -> GlobalConfig:
    loader = importlib.import_module("teleclaude.config.loader")
    return cast("GlobalConfig", loader.load_global_config())


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
            return person.role
    return None


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


def _print_company_line(identity: ResolvedCliIdentity) -> None:
    """Print the company context from the facts resolved by the command gate."""
    facts = identity.session_facts
    if facts is None:
        return
    organization = importlib.import_module("teleclaude.core.organization")
    resolve_context = cast(
        "Callable[[Session], SessionCompanyContext]",
        organization.resolve_session_company_context,
    )
    context = resolve_context(cast("Session", facts))
    state_class = cast("type[SessionCompanyState]", organization.SessionCompanyState)
    if context.state is state_class.RESOLVED:
        print(f"Company: {context.company}")
    elif context.state is state_class.AMBIGUOUS:
        print(f"Company: ambiguous ({', '.join(context.eligible)}) — select one with --company <slug>")
    else:
        print("Company: none")


def _handle_whoami(args: list[str]) -> None:
    """Handle telec auth whoami."""
    if args:
        print(f"Unexpected arguments: {' '.join(args)}")
        print(_usage("auth", "whoami"))
        raise SystemExit(1)

    identity = resolve_cli_identity()
    if identity.in_session or isinstance(identity.caller, SystemCliCaller):
        if isinstance(identity.caller, NoIdentityCliCaller):
            print(no_identity_refusal(identity))
            raise SystemExit(1)
        if identity.principal:
            print(f"Principal: {identity.principal}")
        role = authorizing_role(identity.caller, identity.role, ProjectPath(invocation_cwd()))
        if role:
            print(f"Role: {role}")
        if identity.session_id:
            _print_company_line(identity)
        return

    context = get_current_session_context()
    if context is None:
        print("Error: no terminal session detected (TTY unavailable).")
        raise SystemExit(1)

    if isinstance(identity.caller, NoIdentityCliCaller):
        print(_NO_IDENTITY_FOR_TTY_MESSAGE.format(tty=context.tty, detail=no_identity_refusal(identity)))
        return

    caller = identity.caller
    print(f"Email: {caller.email}")
    print(f"Role: {authorizing_role(caller, identity.role, ProjectPath(invocation_cwd())) or _UNRESOLVED_ROLE}")
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
