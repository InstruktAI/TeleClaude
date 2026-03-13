"""Infrastructure subcommand handlers for telec computers/projects/agents/channels.

All commands call the daemon REST API via tool_api_call() and print JSON to stdout.
Errors go to stderr with exit code 1 (handled by tool_api_call).
"""

from __future__ import annotations

import sys

from teleclaude.cli.tool_client import print_json, tool_api_call

__all__ = [
    "handle_agents",
    "handle_agents_availability",
    "handle_agents_status",
    "handle_channels",
    "handle_channels_list",
    "handle_channels_publish",
    "handle_computers",
    "handle_projects",
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
    if "--help" in args or "-h" in args:
        print(handle_projects.__doc__ or "")
        return

    params: dict[str, str] = {}
    i = 0
    while i < len(args):
        if args[i] == "--computer" and i + 1 < len(args):
            params["computer"] = args[i + 1]
            i += 2
        else:
            i += 1

    data = tool_api_call("GET", "/projects", params=params)
    print_json(data)


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
                               [--until <ISO8601>]
                               OR
           telec agents status <agent> --clear

    Marks an agent as available, unavailable (temporarily blocked from
    dispatch), or degraded (excluded from automatic fallback selection).
    Use --clear to reset to available immediately.

    Options:
      <agent>          Agent name: claude, gemini, codex
      --status <s>     Status: available, unavailable, degraded
      --reason <text>  Reason (required for unavailable)
      --until <ts>     ISO8601 UTC expiry for unavailable status
      --clear          Reset to available immediately

    Examples:
      telec agents status claude --status unavailable --reason rate_limited
      telec agents status claude --status unavailable --reason quota_exhausted --until 2024-01-01T12:00:00Z
      telec agents status claude --status degraded --reason "slow responses"
      telec agents status claude --clear
    """
    if "--help" in args or "-h" in args:
        print(handle_agents_status.__doc__ or "")
        return

    agent: str | None = None
    body: dict[str, object] = {}  # guard: loose-dict - JSON request body

    if args and not args[0].startswith("-"):
        agent = args[0]
        args = args[1:]

    i = 0
    while i < len(args):
        if args[i] == "--status" and i + 1 < len(args):
            body["status"] = args[i + 1]
            i += 2
        elif args[i] == "--reason" and i + 1 < len(args):
            body["reason"] = args[i + 1]
            i += 2
        elif args[i] == "--until" and i + 1 < len(args):
            body["unavailable_until"] = args[i + 1]
            i += 2
        elif args[i] == "--clear":
            body["clear"] = True
            i += 1
        else:
            i += 1

    if not agent:
        print("Error: agent name required (claude, gemini, codex)", file=sys.stderr)
        raise SystemExit(1)

    data = tool_api_call("POST", f"/agents/{agent}/status", json_body=body)
    print_json(data)


# =============================================================================
# Channels group
# =============================================================================


def handle_channels(args: list[str]) -> None:
    """Manage internal Redis Stream channels.

    Usage: telec channels <subcommand> [args]

    Subcommands:
      list     List active channels (optionally filtered by project)
      publish  Publish a message to a channel

    Examples:
      telec channels list
      telec channels list --project myproject
      telec channels publish channel:myproject:events --data '{"type":"update"}'
    """
    if not args or args[0] in ("-h", "--help"):
        print(handle_channels.__doc__ or "")
        return

    sub = args[0]
    rest = args[1:]

    if sub == "list":
        handle_channels_list(rest)
    elif sub == "publish":
        handle_channels_publish(rest)
    else:
        print(f"Unknown channels subcommand: {sub}", file=sys.stderr)
        print("Run 'telec channels --help' for usage.", file=sys.stderr)
        raise SystemExit(1)


def handle_channels_list(args: list[str]) -> None:
    """List active internal Redis Stream channels.

    Usage: telec channels list [--project <name>]

    Returns all active channels, optionally filtered by project name.
    Channel names follow the convention: channel:{project}:{topic}

    Options:
      --project <name>   Filter by project name

    Examples:
      telec channels list
      telec channels list --project myproject
    """
    if "--help" in args or "-h" in args:
        print(handle_channels_list.__doc__ or "")
        return

    params: dict[str, str] = {}
    i = 0
    while i < len(args):
        if args[i] == "--project" and i + 1 < len(args):
            params["project"] = args[i + 1]
            i += 2
        else:
            i += 1

    data = tool_api_call("GET", "/api/channels/", params=params)
    print_json(data)


def handle_channels_publish(args: list[str]) -> None:
    """Publish a message to an internal Redis Stream channel.

    Usage: telec channels publish <channel> --data <json>

    Publishes a JSON payload to the specified channel. Publishing to a
    non-existent channel creates it automatically.

    Channel naming convention: channel:{project}:{topic}

    Options:
      <channel>      Full channel key (e.g. channel:myproject:events)
      --data <json>  JSON payload to publish

    Examples:
      telec channels publish channel:myproject:events --data '{"type":"update"}'
      telec channels publish channel:ai:notifications --data '{"msg":"done"}'
    """
    if "--help" in args or "-h" in args:
        print(handle_channels_publish.__doc__ or "")
        return

    import json

    channel: str | None = None
    payload_str: str | None = None

    if args and not args[0].startswith("-"):
        channel = args[0]
        args = args[1:]

    i = 0
    while i < len(args):
        if args[i] == "--data" and i + 1 < len(args):
            payload_str = args[i + 1]
            i += 2
        elif args[i] == "--channel" and i + 1 < len(args):
            channel = args[i + 1]
            i += 2
        else:
            i += 1

    if not channel:
        print("Error: channel name required", file=sys.stderr)
        raise SystemExit(1)
    if not payload_str:
        print("Error: --data is required", file=sys.stderr)
        raise SystemExit(1)

    try:
        payload = json.loads(payload_str)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON for --data: {e}", file=sys.stderr)
        raise SystemExit(1)

    data = tool_api_call(
        "POST",
        f"/api/channels/{channel}/publish",
        json_body={"payload": payload},
    )
    print_json(data)
