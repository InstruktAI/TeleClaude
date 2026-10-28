"""Infrastructure subcommand handlers for telec computers/projects/agents.

All commands call the daemon REST API via tool_api_call() and print JSON to stdout.
Errors go to stderr with exit code 1 (handled by tool_api_call).
"""

from __future__ import annotations

import sys
from enum import StrEnum

from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.telec.surface import (
    AGENTS_STATUS,
    PROJECTS_ACTIVE_COMPUTER_SET,
    PROJECTS_ACTIVE_COMPUTER_SHOW,
    PROJECTS_LIST,
)
from teleclaude.cli.tool_client import print_json, tool_api_call
from teleclaude.project_root import resolve_invocation_cwd

_PROJECTS_COMMAND = "projects"
_ACTIVE_COMPUTER_COMMAND = "active-computer"
_ACTIVE_COMPUTER_ROUTE = "/projects/active-computer"
_CWD_FIELD = "cwd"
_COMPUTER_FIELD = "computer"
_GET = "GET"
_POST = "POST"


class _ActiveComputerVerb(StrEnum):
    SHOW = "show"
    SET = "set"


__all__ = [
    "handle_agents",
    "handle_agents_availability",
    "handle_agents_status",
    "handle_computers",
    "handle_projects",
    "handle_projects_active_computer",
]


# =============================================================================
# Top-level commands: computers, projects
# =============================================================================


def handle_computers(args: list[str]) -> None:
    """List available computers (local + cached remote computers).

    Usage: telec computers list

    Returns all known computers with their status, user, host, and whether
    they are the local computer. Remote computers are populated from the
    Redis peer cache and may be stale if connectivity is lost.

    Examples:
      telec computers list
    """
    if "--help" in args or "-h" in args:
        print(handle_computers.__doc__ or "")
        return

    data = tool_api_call("GET", "/computers")
    print_json(data)


def handle_projects(args: list[str]) -> None:
    """List projects (local + cached remote projects).

    Usage: telec projects list [--computer <name>]

    Returns all known projects with their name, path, description, and
    which computer they are on. Local projects are served from cache when
    available (warmed at startup). Remote projects come from the Redis cache.

    Options:
      --computer <name>  Filter to a specific computer (optional)

    Examples:
      telec projects list
      telec projects list --computer macbook
    """
    parsed = parse_command_args(PROJECTS_LIST, args)
    params: dict[str, str] = {}
    computer = parsed.value(F.FLAG_COMPUTER)
    if computer is not None:
        params["computer"] = computer

    data = tool_api_call("GET", "/projects", params=params)
    print_json(data)


def handle_projects_active_computer(args: list[str]) -> None:
    """Show or set the GitHub-backed project's active computer, for the project in the current directory."""
    if not args or args[0] not in _ActiveComputerVerb:
        print(_usage(_PROJECTS_COMMAND, _ACTIVE_COMPUTER_COMMAND))
        raise SystemExit(0 if not args else 1)
    cwd = str(resolve_invocation_cwd())
    if args[0] == _ActiveComputerVerb.SHOW:
        parse_command_args(PROJECTS_ACTIVE_COMPUTER_SHOW, args[1:])
        print_json(tool_api_call(_GET, _ACTIVE_COMPUTER_ROUTE, params={_CWD_FIELD: cwd}))
        return
    parsed = parse_command_args(PROJECTS_ACTIVE_COMPUTER_SET, args[1:])
    body: dict[str, str] = {_CWD_FIELD: cwd}
    computer = parsed.value(F.FLAG_COMPUTER)
    if computer is not None:
        body[_COMPUTER_FIELD] = computer
    print_json(tool_api_call(_POST, _ACTIVE_COMPUTER_ROUTE, json_body=body))


# =============================================================================
# Agents group
# =============================================================================


def handle_agents(args: list[str]) -> None:
    """Manage agent dispatch status and availability.

    Usage: telec agents <subcommand> [args]

    Subcommands:
      availability  Get current availability for all agents
      status        Set dispatch status for a specific agent

    Examples:
      telec agents availability
      telec agents status claude --status unavailable --reason rate_limited
    """
    if not args or args[0] in ("-h", "--help"):
        print(handle_agents.__doc__ or "")
        return

    sub = args[0]
    rest = args[1:]

    if sub == "availability":
        handle_agents_availability(rest)
    elif sub == "status":
        handle_agents_status(rest)
    else:
        print(f"Unknown agents subcommand: {sub}", file=sys.stderr)
        print("Run 'telec agents --help' for usage.", file=sys.stderr)
        raise SystemExit(1)


def handle_agents_availability(args: list[str]) -> None:
    """Get current availability for all agents.

    Usage: telec agents availability

    Returns availability status for claude, gemini, and codex, including
    whether each is available, its current status, the reason for any
    unavailability, and when it becomes available again.

    Examples:
      telec agents availability
    """
    if "--help" in args or "-h" in args:
        print(handle_agents_availability.__doc__ or "")
        return

    data = tool_api_call("GET", "/agents/availability")
    print_json(data)


def handle_agents_status(args: list[str]) -> None:
    """Set agent dispatch status (available/unavailable/degraded).

    Usage: telec agents status <agent> --status <status>
                               [--reason <text>]
                               [--model <model>]
                               [--until <ISO8601>]
                               OR
           telec agents status <agent> --clear

    Marks an agent as available, unavailable (temporarily blocked from
    dispatch), or degraded (excluded from automatic fallback selection).
    Use --clear to reset to available immediately.

    Options:
      <agent>          Agent name: claude, gemini, codex, deepseek
      --status <s>     Status: available, unavailable, degraded
      --reason <text>  Reason (required for unavailable)
      --model <model>  Scope the status to one declared model
      --until <ts>     ISO8601 UTC expiry for unavailable or degraded status
      --clear          Reset to available immediately

    Examples:
      telec agents status claude --status unavailable --reason rate_limited
      telec agents status claude --status unavailable --reason quota_exhausted --until 2024-01-01T12:00:00Z
      telec agents status claude --status degraded --reason "slow responses"
      telec agents status claude --model sonnet --status degraded --reason "slow responses" --until 2024-01-01T12:00:00Z
      telec agents status claude --status degraded --reason "slow responses" --until 2024-01-01T12:00:00Z
      telec agents status claude --clear
    """
    parsed = parse_command_args(AGENTS_STATUS, args)
    positionals = parsed.positionals
    if len(positionals) > 1:
        print(f"Error: unexpected argument: {positionals[1]}", file=sys.stderr)
        raise SystemExit(1)
    agent = positionals[0] if positionals else None
    if not agent:
        print("Error: agent name required (claude, gemini, codex, deepseek)", file=sys.stderr)
        raise SystemExit(1)

    body: dict[str, object] = {}  # guard: loose-dict - JSON request body
    status = parsed.value(F.FLAG_AGENT_STATUS)
    if status is not None:
        body["status"] = status
    reason = parsed.value(F.FLAG_AGENT_STATUS_REASON)
    if reason is not None:
        body["reason"] = reason
    model = parsed.value(F.FLAG_AGENT_STATUS_MODEL)
    if model is not None:
        body["model"] = model
    until = parsed.value(F.FLAG_AGENT_STATUS_UNTIL)
    if until is not None:
        body["until"] = until
    if parsed.has(F.FLAG_AGENT_STATUS_CLEAR):
        body["clear"] = True

    data = tool_api_call("POST", f"/agents/{agent}/status", json_body=body)
    print_json(data)
