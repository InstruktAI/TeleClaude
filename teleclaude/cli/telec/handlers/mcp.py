"""Handlers for telec mcp commands."""

from __future__ import annotations

import json
import sys
from enum import StrEnum

from instrukt_ai_logging import get_logger

from teleclaude.cli.telec.help import _usage
from teleclaude.cli.tool_client import print_json, tool_api_call
from teleclaude.mcp.registry import TELECLAUDE_MCP_CONFIG_FILE, RegistryError, load_effective_registry
from teleclaude.mcp.timeouts import (
    MCP_LIST_TOOLS_CLIENT_TIMEOUT_SECONDS,
    MCP_TOOL_CALL_CLIENT_TIMEOUT_SECONDS,
)
from teleclaude.paths import REPO_ROOT
from teleclaude.project_root import resolve_invocation_project_root

__all__ = ["_handle_mcp"]

logger = get_logger(__name__)

_MCP_REGISTRY_LIST_RESOLUTION_EVENT = "mcp_registry_list_resolution"


class McpRegistryListOutcome(StrEnum):
    """Terminal result vocabulary for in-process MCP registry resolution."""

    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


class McpRegistryListResolutionPath(StrEnum):
    """Registry resolution mechanism vocabulary for MCP server listing."""

    IN_PROCESS_REGISTRY = "in_process_registry"


class McpRegistryListAuthority(StrEnum):
    """Registry authority vocabulary for MCP server listing."""

    TELECLAUDE_REPOSITORY = "teleclaude_repository"


class McpRegistryListFailureReason(StrEnum):
    """Stable failure reason vocabulary for MCP server listing."""

    REGISTRY_LOAD_FAILED = "registry_load_failed"


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
    invocation_project: str | None = None
    try:
        invocation_project = resolve_invocation_project_root().name
        registry = load_effective_registry(REPO_ROOT)
    except (FileNotFoundError, RegistryError) as exc:
        logger.info(
            _MCP_REGISTRY_LIST_RESOLUTION_EVENT,
            outcome=McpRegistryListOutcome.UNRESOLVED.value,
            resolution_path=McpRegistryListResolutionPath.IN_PROCESS_REGISTRY.value,
            registry_authority=McpRegistryListAuthority.TELECLAUDE_REPOSITORY.value,
            registry_filename=TELECLAUDE_MCP_CONFIG_FILE,
            invocation_project=invocation_project,
            reason=McpRegistryListFailureReason.REGISTRY_LOAD_FAILED.value,
        )
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    servers = [server.to_catalog_dict() for server in registry.enabled_servers(exclude=set(excludes))]
    logger.info(
        _MCP_REGISTRY_LIST_RESOLUTION_EVENT,
        outcome=McpRegistryListOutcome.RESOLVED.value,
        resolution_path=McpRegistryListResolutionPath.IN_PROCESS_REGISTRY.value,
        registry_authority=McpRegistryListAuthority.TELECLAUDE_REPOSITORY.value,
        registry_filename=TELECLAUDE_MCP_CONFIG_FILE,
        invocation_project=invocation_project,
        enabled_server_count=len(servers),
    )
    if raw_json:
        print_json({"servers": servers})
        return
    for item in servers:
        slug = item.get("slug")
        if not isinstance(slug, str) or not slug:
            continue
        trigger = item.get("trigger")
        if isinstance(trigger, str) and trigger.strip():
            print(f"- {slug}: {trigger.strip()}")
        else:
            print(f"- {slug}")


def _handle_list_tools(args: list[str]) -> None:
    raw_json = "--json" in args
    positionals = [arg for arg in args if arg != "--json"]
    if len(positionals) != 1:
        _fail_usage("mcp list-tools")
    response = tool_api_call(
        "GET",
        f"/mcp/servers/{positionals[0]}/tools",
        timeout=MCP_LIST_TOOLS_CLIENT_TIMEOUT_SECONDS,
    )
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
    response = tool_api_call(
        "POST",
        f"/mcp/servers/{slug}/tools/{tool_name}/call",
        json_body=arguments,
        timeout=MCP_TOOL_CALL_CLIENT_TIMEOUT_SECONDS,
    )
    print_json(response)


def _fail_usage(command: str) -> None:
    print(_usage(command))
    raise SystemExit(1)
