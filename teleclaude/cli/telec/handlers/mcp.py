"""Handlers for telec mcp commands."""

from __future__ import annotations

import json
import sys
from enum import StrEnum
from pathlib import Path
from typing import NoReturn

from instrukt_ai_logging import get_logger

from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.telec.surface import MCP_CALL, MCP_LIST, MCP_LIST_TOOLS
from teleclaude.cli.tool_client import print_json, tool_api_call
from teleclaude.config.context_root import resolve_context_root
from teleclaude.mcp.registry import (
    TELECLAUDE_MCP_CONFIG_FILE,
    RegistryError,
    load_effective_registry,
    project_mcp_root,
)
from teleclaude.mcp.timeouts import (
    MCP_LIST_TOOLS_CLIENT_TIMEOUT_SECONDS,
    MCP_TOOL_CALL_CLIENT_TIMEOUT_SECONDS,
)
from teleclaude.paths import REPO_ROOT
from teleclaude.project_root import resolve_invocation_cwd, resolve_project_root

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
    parsed = parse_command_args(MCP_LIST, args)
    if parsed.positionals:
        _fail_usage("mcp list")
    excludes = list(parsed.values(F.FLAG_MCP_EXCLUDE))
    raw_json = parsed.has(F.FLAG_MCP_JSON)
    invocation_project: str | None = None
    project_scope = False
    try:
        context = resolve_context_root(resolve_invocation_cwd())
        invocation_project = context.path.name if context is not None else None
        project_root = project_mcp_root(context.path) if context is not None else None
        project_scope = project_root is not None
        registry = load_effective_registry(resolve_project_root(REPO_ROOT), project_root=project_root)
    except (FileNotFoundError, RegistryError) as exc:
        logger.info(
            _MCP_REGISTRY_LIST_RESOLUTION_EVENT,
            outcome=McpRegistryListOutcome.UNRESOLVED.value,
            resolution_path=McpRegistryListResolutionPath.IN_PROCESS_REGISTRY.value,
            registry_authority=McpRegistryListAuthority.TELECLAUDE_REPOSITORY.value,
            registry_filename=TELECLAUDE_MCP_CONFIG_FILE,
            invocation_project=invocation_project,
            project_scope=project_scope,
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
        project_scope=project_scope,
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
    parsed = parse_command_args(MCP_LIST_TOOLS, args)
    positionals = parsed.positionals
    if len(positionals) != 1:
        _fail_usage("mcp list-tools")
    raw_json = parsed.has(F.FLAG_MCP_JSON)
    response = tool_api_call(
        "GET",
        f"/mcp/servers/{positionals[0]}/tools",
        timeout=MCP_LIST_TOOLS_CLIENT_TIMEOUT_SECONDS,
        project_root=_tool_project_root(),
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
    parsed = parse_command_args(MCP_CALL, args)
    positionals = parsed.positionals
    raw_arguments = parsed.value(F.FLAG_MCP_CALL_JSON)
    if len(positionals) != 2 or raw_arguments is None:
        _fail_usage("mcp call")
    slug, tool_name = positionals
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
        project_root=_tool_project_root(),
    )
    print_json(response)


def _fail_usage(command: str) -> NoReturn:
    print(_usage(command))
    raise SystemExit(1)


def _tool_project_root() -> Path | None:
    """Return the eligible canonical project root for tool API requests."""
    context = resolve_context_root(resolve_invocation_cwd())
    return project_mcp_root(context.path) if context is not None else None
