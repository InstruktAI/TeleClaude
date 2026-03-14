"""Handlers for telec history commands."""

from __future__ import annotations

from teleclaude.cli.telec.help import _usage

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
    from teleclaude.history.search import display_combined_history, parse_agents

    agent_arg = "all"
    limit = 20
    computers: list[str] = []
    terms: list[str] = []

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-h", "--help"):
            print(_usage("history", "search"))
            return
        elif arg in ("--agent", "-a") and i + 1 < len(args):
            agent_arg = args[i + 1]
            i += 2
        elif arg in ("--agent", "-a"):
            print("Missing value for --agent.")
            print(_usage("history", "search"))
            raise SystemExit(1)
        elif arg in ("--limit", "-l") and i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError:
                print(f"Invalid value for --limit: {args[i + 1]}")
                raise SystemExit(1)
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
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("history", "search"))
            raise SystemExit(1)
        else:
            terms.append(arg)
            i += 1

    if not terms:
        print("Search terms are required.")
        print(_usage("history", "search"))
        raise SystemExit(1)

    agents = parse_agents(agent_arg)
    display_combined_history(agents, search_term=" ".join(terms), limit=limit, computers=computers or None)


def _handle_history_show(args: list[str]) -> None:
    """Handle telec history show."""
    from teleclaude.history.search import parse_agents, show_transcript

    agent_arg = "all"
    thinking = False
    raw = False
    tail = 0
    computers: list[str] = []
    session_id: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-h", "--help"):
            print(_usage("history", "show"))
            return
        elif arg in ("--agent", "-a") and i + 1 < len(args):
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
        elif arg == "--tail" and i + 1 < len(args):
            try:
                tail = int(args[i + 1])
            except ValueError:
                print(f"Invalid value for --tail: {args[i + 1]}")
                raise SystemExit(1)
            i += 2
        elif arg == "--tail":
            print("Missing value for --tail.")
            print(_usage("history", "show"))
            raise SystemExit(1)
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

    agents = parse_agents(agent_arg)
    show_transcript(agents, session_id, tail_chars=tail, include_thinking=thinking, raw=raw, computers=computers)
