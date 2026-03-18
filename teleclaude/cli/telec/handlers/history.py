"""Handlers for telec history commands."""

from __future__ import annotations

from importlib import import_module

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
        return
    if subcommand == "show":
        _handle_history_show(args[1:])
        return
    print(f"Unknown history subcommand: {subcommand}")
    print(_usage("history"))
    raise SystemExit(1)


def _load_history_search_module():
    return import_module("teleclaude.history.search")


def _handle_history_search(args: list[str]) -> None:
    """Handle telec history search."""
    parsed = _parse_history_search_args(args)
    if parsed is None:
        return

    history_search = _load_history_search_module()
    agents = history_search.parse_agents(parsed["agent_arg"])
    history_search.display_combined_history(
        agents,
        search_term=" ".join(parsed["terms"]),
        limit=parsed["limit"],
        computers=parsed["computers"] or None,
    )


def _handle_history_show(args: list[str]) -> None:
    """Handle telec history show."""
    parsed = _parse_history_show_args(args)
    if parsed is None:
        return

    history_search = _load_history_search_module()
    agents = history_search.parse_agents(parsed["agent_arg"])
    history_search.show_transcript(
        agents,
        parsed["session_id"],
        tail_chars=parsed["tail"],
        include_thinking=parsed["thinking"],
        raw=parsed["raw"],
        computers=parsed["computers"],
    )


def _parse_history_search_args(args: list[str]) -> dict[str, object] | None:
    parsed: dict[str, object] = {
        "agent_arg": "all",
        "limit": 20,
        "computers": [],
        "terms": [],
    }
    index = 0

    while index < len(args):
        index = _consume_history_search_arg(args, index, parsed)
        if index < 0:
            return None

    terms = parsed["terms"]
    if terms:
        return parsed

    print("Search terms are required.")
    print(_usage("history", "search"))
    raise SystemExit(1)


def _consume_history_search_arg(args: list[str], index: int, parsed: dict[str, object]) -> int:
    arg = args[index]
    if arg in ("-h", "--help"):
        print(_usage("history", "search"))
        return -1
    if arg in ("--agent", "-a"):
        parsed["agent_arg"] = _require_option_value(args, index, "history", "search", "--agent")
        return index + 2
    if arg in ("--limit", "-l"):
        parsed["limit"] = _parse_int_option(args, index, "history", "search", "--limit")
        return index + 2
    if arg == "--computer":
        computers, next_index = _parse_computers(args, index, "search")
        parsed["computers"].extend(computers)
        return next_index
    if arg.startswith("-"):
        _raise_history_usage_error(f"Unknown option: {arg}", "search")
    parsed["terms"].append(arg)
    return index + 1


def _parse_history_show_args(args: list[str]) -> dict[str, object] | None:
    parsed: dict[str, object] = {
        "agent_arg": "all",
        "thinking": False,
        "raw": False,
        "tail": 0,
        "computers": [],
        "session_id": None,
    }
    index = 0

    while index < len(args):
        index = _consume_history_show_arg(args, index, parsed)
        if index < 0:
            return None

    if parsed["session_id"]:
        return parsed

    print("Session ID is required.")
    print(_usage("history", "show"))
    raise SystemExit(1)


def _consume_history_show_arg(args: list[str], index: int, parsed: dict[str, object]) -> int:
    arg = args[index]
    if arg in ("-h", "--help"):
        print(_usage("history", "show"))
        return -1
    if arg in ("--agent", "-a"):
        parsed["agent_arg"] = _require_option_value(args, index, "history", "show", "--agent")
        return index + 2
    next_index = index + 1
    if arg == "--thinking":
        parsed["thinking"] = True
    elif arg == "--raw":
        parsed["raw"] = True
    elif arg == "--tail":
        parsed["tail"] = _parse_int_option(args, index, "history", "show", "--tail")
        next_index = index + 2
    elif arg == "--computer":
        computers, next_index = _parse_computers(args, index, "show")
        parsed["computers"].extend(computers)
    elif arg.startswith("-"):
        _raise_history_usage_error(f"Unknown option: {arg}", "show")
    else:
        next_index = _consume_session_id(arg, index, parsed)
    return next_index


def _require_option_value(args: list[str], index: int, command: str, subcommand: str, option: str) -> str:
    if index + 1 < len(args):
        return args[index + 1]
    print(f"Missing value for {option}.")
    print(_usage(command, subcommand))
    raise SystemExit(1)


def _parse_int_option(args: list[str], index: int, command: str, subcommand: str, option: str) -> int:
    value = _require_option_value(args, index, command, subcommand, option)
    try:
        return int(value)
    except ValueError as exc:
        print(f"Invalid value for {option}: {value}")
        raise SystemExit(1) from exc


def _parse_computers(args: list[str], index: int, subcommand: str) -> tuple[list[str], int]:
    computers: list[str] = []
    index += 1
    while index < len(args) and not args[index].startswith("-"):
        computers.append(args[index])
        index += 1

    if computers:
        return computers, index

    print("Missing value for --computer.")
    print(_usage("history", subcommand))
    raise SystemExit(1)


def _consume_session_id(arg: str, index: int, parsed: dict[str, object]) -> int:
    if parsed["session_id"] is None:
        parsed["session_id"] = arg
        return index + 1

    print(f"Unexpected positional argument: {arg}")
    print(_usage("history", "show"))
    raise SystemExit(1)


def _raise_history_usage_error(message: str, subcommand: str) -> None:
    print(message)
    print(_usage("history", subcommand))
    raise SystemExit(1)
