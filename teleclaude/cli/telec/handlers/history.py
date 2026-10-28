"""Handlers for telec history commands."""

from __future__ import annotations

from teleclaude.cli.history_detail import show_transcript
from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.telec.surface import HISTORY_SEARCH, HISTORY_SHOW
from teleclaude.history.search import display_combined_history, parse_agents
from teleclaude.utils.transcript_discovery import SessionId

__all__ = [
    "_handle_history",
    "_handle_history_search",
    "_handle_history_show",
]


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
    parsed = parse_command_args(HISTORY_SEARCH, args)

    limit_raw = parsed.value(F.FLAG_HISTORY_LIMIT)
    limit = 20
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except ValueError as exc:
            print(f"Invalid value for --limit: {limit_raw}")
            raise SystemExit(1) from exc

    terms = list(parsed.positionals)
    identity = parsed.value(F.FLAG_HISTORY_IDENTITY)
    project = parsed.value(F.FLAG_PROJECT_FILTER)
    if not terms and not identity and not project:
        print("Search terms or an identity/project selector are required.")
        print(_usage("history", "search"))
        raise SystemExit(1)

    agents = parse_agents(parsed.value(F.FLAG_HISTORY_AGENT) or "all")
    display_combined_history(
        agents,
        search_term=" ".join(terms),
        limit=limit,
        computers=list(parsed.values(F.FLAG_COMPUTER_MANY)) or None,
        include_workers=parsed.has(F.FLAG_HISTORY_INCLUDE_FOCUSED),
        identity=identity,
        project=project,
        json_output=parsed.has(F.FLAG_HISTORY_JSON),
    )


def _handle_history_show(args: list[str]) -> None:
    """Handle telec history show."""
    parsed = parse_command_args(HISTORY_SHOW, args)

    if len(parsed.positionals) > 1:
        print(f"Unexpected positional argument: {parsed.positionals[1]}")
        print(_usage("history", "show"))
        raise SystemExit(1)
    session_id = parsed.positionals[0] if parsed.positionals else None
    if not session_id:
        print("Session ID is required.")
        print(_usage("history", "show"))
        raise SystemExit(1)

    try:
        session_id = str(SessionId(session_id))
    except ValueError as exc:
        print(exc)
        raise SystemExit(1) from exc

    agents = parse_agents(parsed.value(F.FLAG_HISTORY_SHOW_AGENT) or "all")
    show_transcript(
        agents,
        session_id,
        include_thinking=parsed.has(F.FLAG_THINKING),
        raw=parsed.has(F.FLAG_HISTORY_RAW),
        computers=list(parsed.values(F.FLAG_COMPUTER_MANY)),
        json_output=parsed.has(F.FLAG_HISTORY_JSON),
    )
