"""Lazy MCP API routes."""

from __future__ import annotations

from typing import Annotated, Protocol

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from teleclaude.api.auth import CallerIdentity, verify_caller
from teleclaude.mcp.protocol import JsonObject
from teleclaude.mcp.runtime import McpRuntime, McpRuntimeError


class _McpRuntime(Protocol):
    def list_servers(self, *, exclude: set[str] | None = None) -> list[JsonObject]:
        """Return configured MCP servers without starting leases."""
        ...

    async def list_tools(self, slug: str) -> JsonObject:
        """Return a selected server's tool catalog."""
        ...

    async def call_tool(self, slug: str, tool_name: str, arguments: JsonObject) -> JsonObject:
        """Call a selected server tool."""
        ...


_RUNTIME: dict[str, _McpRuntime | None] = {"value": None}

router = APIRouter(prefix="/mcp", tags=["mcp"])


def configure(runtime: McpRuntime | _McpRuntime | None) -> None:
    """Wire the daemon-owned MCP runtime."""
    _RUNTIME["value"] = runtime


@router.get("/servers")
async def list_servers(
    exclude: Annotated[list[str] | None, Query()] = None,
    _identity: CallerIdentity = Depends(verify_caller),
) -> JsonObject:
    """Return configured MCP servers without initializing any lease."""
    runtime = _require_runtime()
    servers = runtime.list_servers(exclude=set(exclude or []))
    return {"servers": servers}


@router.get("/servers/{slug}/tools")
async def list_tools(
    slug: str,
    _identity: CallerIdentity = Depends(verify_caller),
) -> JsonObject:
    """Initialize one server lazily and return its tools."""
    runtime = _require_runtime()
    try:
        return await runtime.list_tools(slug)
    except McpRuntimeError as exc:
        raise _http_error(exc) from exc


@router.post("/servers/{slug}/tools/{tool_name:path}/call")
async def call_tool(
    slug: str,
    tool_name: str,
    arguments: Annotated[object, Body(...)] = None,
    _identity: CallerIdentity = Depends(verify_caller),
) -> JsonObject:
    """Call one MCP tool through the daemon-owned runtime."""
    if not isinstance(arguments, dict):
        raise HTTPException(400, "MCP tool arguments must be a JSON object")
    runtime = _require_runtime()
    try:
        return await runtime.call_tool(slug, tool_name, dict(arguments))
    except McpRuntimeError as exc:
        raise _http_error(exc) from exc


def _require_runtime() -> _McpRuntime:
    runtime = _RUNTIME["value"]
    if runtime is None:
        raise HTTPException(503, "MCP runtime not available")
    return runtime


def _http_error(exc: McpRuntimeError) -> HTTPException:
    if exc.code in {"unknown_server", "unknown_tool"}:
        return HTTPException(404, exc.to_error_dict())
    if exc.code in {"invalid_arguments", "invalid_server"}:
        return HTTPException(400, exc.to_error_dict())
    return HTTPException(503, exc.to_error_dict())
