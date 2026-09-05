"""Lazy MCP API routes."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import CallerIdentity, verify_caller
from teleclaude.mcp.protocol import JsonObject
from teleclaude.mcp.runtime import McpRuntime, McpRuntimeError, McpRuntimePool

_PROJECT_ROOT_HEADER = "x-teleclaude-project-root"
_INVALID_PROJECT_CONTEXT_CODE = "invalid_project_context"
_INVALID_PROJECT_CONTEXT_EVENT = "mcp_project_context_rejected"

_RUNTIME: dict[str, McpRuntimePool | None] = {"value": None}

router = APIRouter(prefix="/mcp", tags=["mcp"])
logger = get_logger(__name__)


def configure(runtime: McpRuntimePool | None) -> None:
    """Wire the daemon-owned MCP runtime pool."""
    _RUNTIME["value"] = runtime


@router.get("/servers")
async def list_servers(
    exclude: Annotated[list[str] | None, Query()] = None,
    _identity: CallerIdentity = Depends(verify_caller),
) -> JsonObject:
    """Return configured MCP servers without initializing any lease."""
    runtime = _require_runtime().machine_runtime
    servers = runtime.list_servers(exclude=set(exclude or []))
    return {"servers": servers}


@router.get("/servers/{slug}/tools")
async def list_tools(
    slug: str,
    project_root: Annotated[str | None, Header(alias=_PROJECT_ROOT_HEADER)] = None,
    _identity: CallerIdentity = Depends(verify_caller),
) -> JsonObject:
    """Initialize one server lazily and return its tools."""
    try:
        runtime = _runtime_for(project_root)
        return await runtime.list_tools(slug)
    except McpRuntimeError as exc:
        _log_project_context_rejection(exc, _identity)
        raise _http_error(exc) from exc


@router.post("/servers/{slug}/tools/{tool_name:path}/call")
async def call_tool(
    slug: str,
    tool_name: str,
    arguments: Annotated[object, Body(...)] = None,
    project_root: Annotated[str | None, Header(alias=_PROJECT_ROOT_HEADER)] = None,
    _identity: CallerIdentity = Depends(verify_caller),
) -> JsonObject:
    """Call one MCP tool through the daemon-owned runtime."""
    if not isinstance(arguments, dict):
        raise HTTPException(400, "MCP tool arguments must be a JSON object")
    try:
        runtime = _runtime_for(project_root)
        return await runtime.call_tool(slug, tool_name, dict(arguments))
    except McpRuntimeError as exc:
        _log_project_context_rejection(exc, _identity)
        raise _http_error(exc) from exc


def _require_runtime() -> McpRuntimePool:
    runtime = _RUNTIME["value"]
    if runtime is None:
        raise HTTPException(503, "MCP runtime not available")
    return runtime


def _runtime_for(project_root: str | None) -> McpRuntime:
    """Resolve an MCP runtime from the optional caller-supplied scope."""
    return _require_runtime().runtime_for(Path(project_root) if project_root is not None else None)


def _log_project_context_rejection(exc: McpRuntimeError, identity: CallerIdentity) -> None:
    """Log rejected project scope without exposing its supplied filesystem path."""
    if exc.code != _INVALID_PROJECT_CONTEXT_CODE:
        return
    logger.warning(
        _INVALID_PROJECT_CONTEXT_EVENT,
        reason=exc.code,
        caller_session_id=identity.session_id,
        caller_principal=identity.principal,
    )


def _http_error(exc: McpRuntimeError) -> HTTPException:
    if exc.code in {"unknown_server", "unknown_tool"}:
        return HTTPException(404, exc.to_error_dict())
    if exc.code in {"invalid_arguments", "invalid_server", _INVALID_PROJECT_CONTEXT_CODE}:
        return HTTPException(400, exc.to_error_dict())
    return HTTPException(503, exc.to_error_dict())
