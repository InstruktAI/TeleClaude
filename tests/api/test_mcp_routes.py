"""Lazy MCP API route tests."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from syrupy.assertion import SnapshotAssertion

import teleclaude.api_server as api_server_module
from teleclaude.api.auth import CallerIdentity, verify_caller
from teleclaude.api.mcp_routes import configure, router
from teleclaude.api_server import APIServer
from teleclaude.mcp.protocol import JsonObject
from teleclaude.mcp.runtime import McpRuntimeError

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/agent_runtime/lazy-mcp-runtime"


class _FakeRuntime:
    def __init__(self) -> None:
        self.started: list[str] = []
        self.calls: list[JsonObject] = []

    def list_servers(self, *, exclude: set[str] | None = None) -> list[JsonObject]:
        excluded = exclude or set()
        return [
            {"slug": slug, "transport": "stdio", "requiresEnv": []}
            for slug in ("alpha", "beta")
            if slug not in excluded
        ]

    async def list_tools(self, slug: str) -> JsonObject:
        if slug == "missing":
            raise McpRuntimeError("Unknown MCP server: missing", code="unknown_server", slug=slug)
        if slug == "needs-env":
            raise McpRuntimeError(
                "MCP server is missing required environment values",
                code="missing_env",
                slug=slug,
                missing_env=("SECRET_TOKEN",),
            )
        self.started.append(slug)
        return {"server": slug, "tools": [{"name": "echo/tool", "inputSchema": {"type": "object"}}]}

    async def call_tool(self, slug: str, tool_name: str, arguments: JsonObject) -> JsonObject:
        self.calls.append({"slug": slug, "tool": tool_name, "arguments": arguments})
        return {"server": slug, "tool": tool_name, "result": {"content": [], "isError": False}}


@pytest.fixture
def app() -> FastAPI:
    fake = _FakeRuntime()
    configure(fake)
    api = FastAPI()
    api.dependency_overrides[verify_caller] = lambda: CallerIdentity(
        session_id="test-session",
        system_role="worker",
        human_role=None,
        tmux_session_name=None,
    )
    api.include_router(router)
    api.state.fake_runtime = fake
    return api


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-LMCP-1")
async def test_server_catalog_does_not_start_runtime(app: FastAPI, snapshot: SnapshotAssertion) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/mcp/servers", params=[("exclude", "beta")])

    assert response.status_code == 200
    assert response.json() == snapshot
    assert app.state.fake_runtime.started == []


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-LMCP-2")
async def test_list_tools_delegates_to_selected_server(app: FastAPI, snapshot: SnapshotAssertion) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/mcp/servers/alpha/tools")

    assert response.status_code == 200
    assert response.json() == snapshot
    assert app.state.fake_runtime.started == ["alpha"]


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-LMCP-3")
async def test_call_tool_forwards_url_encoded_tool_name_and_json_body(
    app: FastAPI, snapshot: SnapshotAssertion
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/mcp/servers/alpha/tools/echo%2Ftool/call", json={"enabled": True})

    assert response.status_code == 200
    assert {
        "response": response.json(),
        "calls": app.state.fake_runtime.calls,
    } == snapshot


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-LMCP-6")
async def test_route_translates_runtime_errors_without_secret_values(app: FastAPI, snapshot: SnapshotAssertion) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        unknown = await client.get("/mcp/servers/missing/tools")
        missing_env = await client.get("/mcp/servers/needs-env/tools")
        invalid_arguments = await client.post("/mcp/servers/alpha/tools/echo/call", json=[])

    assert {
        "unknown": {"status": unknown.status_code, "body": unknown.json()},
        "missing_env": {"status": missing_env.status_code, "body": missing_env.json()},
        "invalid_arguments": {"status": invalid_arguments.status_code, "body": invalid_arguments.json()},
    } == snapshot


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-LMCP-5")
async def test_api_server_reaper_invokes_runtime_idle_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    class _ReapedRuntime:
        def __init__(self) -> None:
            self.reaped = asyncio.Event()

        async def reap_idle(self) -> None:
            self.reaped.set()

    runtime = _ReapedRuntime()
    server = cast(Any, object.__new__(APIServer))
    server._running = True
    server.task_registry = None
    server._mcp_reaper_task = None
    server.mcp_runtime = runtime
    monkeypatch.setattr(api_server_module, "API_MCP_REAPER_INTERVAL_S", 0.01)

    server._start_mcp_reaper_task()
    await asyncio.wait_for(runtime.reaped.wait(), timeout=1)
    server._running = False
    await server._stop_mcp_reaper_task()

    assert server._mcp_reaper_task is None
