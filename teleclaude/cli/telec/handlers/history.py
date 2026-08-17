"""Handlers for telec history commands."""

from __future__ import annotations

import importlib

from teleclaude.cli.session_auth import read_current_session_email
from teleclaude.cli.telec.help import _usage
from teleclaude.history.search import display_combined_history, parse_agents, show_transcript
from teleclaude.utils.transcript_discovery import SessionId

__all__ = [
    "_handle_history",
    "_handle_history_search",
    "_handle_history_show",
]


def resolve_cli_caller_role() -> str | None:
    """Resolve the caller's role from terminal auth email via people config."""
    email = read_current_session_email()
    if not email:
        return None
    try:
        global_cfg = importlib.import_module("teleclaude.config.loader").load_global_config()
    except (AttributeError, ImportError, OSError, TypeError, ValueError):
        return None
    normalized = email.strip().lower()
    for person in global_cfg.people:
        if person.email.strip().lower() == normalized:
            return str(person.role)
    return None


def _handle_history(args: list[str]) -> None:
    """Handle telec history commands."""
    if not args:
        print(_usage("history"))
        return
    if args[0] in ("-h", "--help"):
        print(_usage("history"))
        return

    subcommand = args[0]
    if subcommand == "search":
        _handle_history_search(args[1:])
    elif subcommand == "show":
        _handle_history_show(args[1:])
    else:
        print(f"Unknown history subcommand: {subcommand}")
        print(_usage("history"))
        raise SystemExit(1)


def _handle_history_search(args: list[str]) -> None:
    """Handle telec history search."""
    agent_arg = "all"
    limit = 20
    computers: list[str] = []
    terms: list[str] = []
    include_workers = False
    identity: str | None = None
    project: str | None = None
    json_output = False

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-h", "--help"):
            print(_usage("history", "search"))
            return
        if arg in ("--agent", "-a") and i + 1 < len(args):
            agent_arg = args[i + 1]
            i += 2
        elif arg in ("--agent", "-a"):
            print("Missing value for --agent.")
            print(_usage("history", "search"))
            raise SystemExit(1)
        elif arg in ("--limit", "-l") and i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError as exc:
                print(f"Invalid value for --limit: {args[i + 1]}")
                raise SystemExit(1) from exc
            i += 2
        elif arg in ("--limit", "-l"):
            print("Missing value for --limit.")
            print(_usage("history", "search"))
            raise SystemExit(1)
        elif arg == "--computer":
            i += 1
            while i < len(args) and not args[i].startswith("-"):
                computers.append(args[i])
                i += 1
            if not computers:
                print("Missing value for --computer.")
                print(_usage("history", "search"))
                raise SystemExit(1)
        elif arg == "--include-workers":
            include_workers = True
            i += 1
        elif arg == "--json":
            json_output = True
            i += 1
        elif arg == "--identity" and i + 1 < len(args):
            identity = args[i + 1]
            i += 2
        elif arg == "--identity":
            print("Missing value for --identity.")
            print(_usage("history", "search"))
            raise SystemExit(1)
        elif arg == "--project" and i + 1 < len(args):
            project = args[i + 1]
            i += 2
        elif arg == "--project":
            print("Missing value for --project.")
            print(_usage("history", "search"))
            raise SystemExit(1)
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("history", "search"))
            raise SystemExit(1)
        else:
            terms.append(arg)
            i += 1

    if not terms and not identity and not project:
        print("Search terms or an identity/project selector are required.")
        print(_usage("history", "search"))
        raise SystemExit(1)

    agents = parse_agents(agent_arg)
    display_combined_history(
        agents,
        search_term=" ".join(terms),
        limit=limit,
        computers=computers or None,
        include_workers=include_workers,
        identity=identity,
        project=project,
        json_output=json_output,
    )


def _handle_history_show(args: list[str]) -> None:
    """Handle telec history show."""
    agent_arg = "all"
    thinking = False
    raw = False
    json_output = False
    computers: list[str] = []
    session_id: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-h", "--help"):
            print(_usage("history", "show"))
            return
        if arg in ("--agent", "-a") and i + 1 < len(args):
            agent_arg = args[i + 1]
            i += 2
        elif arg in ("--agent", "-a"):
            print("Missing value for --agent.")
            print(_usage("history", "show"))
            raise SystemExit(1)
        elif arg == "--thinking":
            thinking = True
            i += 1
        elif arg == "--raw":
            raw = True
            i += 1
        elif arg == "--json":
            json_output = True
            i += 1
        elif arg == "--computer":
            i += 1
            while i < len(args) and not args[i].startswith("-"):
                computers.append(args[i])
                i += 1
            if not computers:
                print("Missing value for --computer.")
                print(_usage("history", "show"))
                raise SystemExit(1)
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("history", "show"))
            raise SystemExit(1)
        else:
            if session_id is None:
                session_id = arg
            else:
                print(f"Unexpected positional argument: {arg}")
                print(_usage("history", "show"))
                raise SystemExit(1)
            i += 1

    if not session_id:
        print("Session ID is required.")
        print(_usage("history", "show"))
        raise SystemExit(1)

    try:
        session_id = str(SessionId(session_id))
    except ValueError as exc:
        print(exc)
        raise SystemExit(1) from exc

    caller_email = read_current_session_email()
    caller_role = resolve_cli_caller_role()
    agents = parse_agents(agent_arg)
    show_transcript(
        agents,
        session_id,
        include_thinking=thinking,
        raw=raw,
        computers=computers,
        caller_email=caller_email,
        caller_role=caller_role,
        json_output=json_output,
    )
