"""Handlers for telec mcp commands."""

from __future__ import annotations

import json
import sys

from teleclaude.cli.telec.help import _usage
from teleclaude.cli.tool_client import print_json, tool_api_call

__all__ = ["_handle_mcp"]


def _handle_mcp(args: list[str]) -> None:
    """Handle telec mcp subcommands."""
    if not args:
        print(_usage("mcp"))
        return
    subcommand = args[0]
    rest = args[1:]
    if subcommand == "list":
        _handle_list(rest)
        return
    if subcommand == "list-tools":
        _handle_list_tools(rest)
        return
    if subcommand == "call":
        _handle_call(rest)
        return
    print(f"Unknown mcp subcommand: {subcommand}")
    print(_usage("mcp"))
    raise SystemExit(1)


def _handle_list(args: list[str]) -> None:
    excludes: list[str] = []
    raw_json = False
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--json":
            raw_json = True
            index += 1
            continue
        if token == "--exclude" and index + 1 < len(args):
            excludes.append(args[index + 1])
            index += 2
            continue
        _fail_usage("mcp list")
    response = tool_api_call("GET", "/mcp/servers", params=[("exclude", slug) for slug in excludes])
    if raw_json:
        print_json(response)
        return
    if not isinstance(response, dict):
        print_json(response)
        return
    servers = response.get("servers", [])
    if not isinstance(servers, list):
        print_json(response)
        return
    for item in servers:
        if not isinstance(item, dict):
            continue
        slug = item.get("slug", "")
        transport = item.get("transport", "")
        required_env = item.get("requiresEnv", [])
        env_note = f" env={','.join(str(name) for name in required_env)}" if required_env else ""
        print(f"{slug}\t{transport}{env_note}")
    commands = response.get("commands", {})
    if isinstance(commands, dict):
        list_tools = commands.get("listTools")
        call_tool = commands.get("callTool")
        if isinstance(list_tools, str):
            print(list_tools)
        if isinstance(call_tool, str):
            print(call_tool)


def _handle_list_tools(args: list[str]) -> None:
    raw_json = "--json" in args
    positionals = [arg for arg in args if arg != "--json"]
    if len(positionals) != 1:
        _fail_usage("mcp list-tools")
    response = tool_api_call("GET", f"/mcp/servers/{positionals[0]}/tools")
    if raw_json:
        print_json(response)
        return
    if not isinstance(response, dict):
        print_json(response)
        return
    tools = response.get("tools", [])
    if not isinstance(tools, list):
        print_json(response)
        return
    for tool in tools:
        if isinstance(tool, dict):
            print(str(tool.get("name", "")))


def _handle_call(args: list[str]) -> None:
    if len(args) < 4 or args[2] != "--json":
        _fail_usage("mcp call")
    slug = args[0]
    tool_name = args[1]
    raw_arguments = args[3]
    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON arguments: {exc.msg}", file=sys.stderr)
        raise SystemExit(1) from exc
    if not isinstance(arguments, dict):
        print("Invalid JSON arguments: expected an object", file=sys.stderr)
        raise SystemExit(1)
    response = tool_api_call("POST", f"/mcp/servers/{slug}/tools/{tool_name}/call", json_body=arguments, timeout=120)
    print_json(response)


def _fail_usage(command: str) -> None:
    print(_usage(command))
    raise SystemExit(1)
