"""Functional bindings for the telec mcp command group."""

from __future__ import annotations

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.cli.telec.handlers import mcp as mcp_handler
from teleclaude.cli.telec.help import _maybe_show_help
from teleclaude.cli.telec.surface import CLI_SURFACE
from teleclaude.cli.telec.surface_types import TelecCommand

pytestmark = pytest.mark.functional

ApiCall = tuple[str, str, object | None, object | None, float]

_SPEC = "project/spec/feature/agent_runtime/lazy-mcp-runtime"
_LIST_TOOLS_PATH = "/mcp/servers/alpha/tools"


@pytest.fixture
def api_calls(monkeypatch: pytest.MonkeyPatch) -> list[ApiCall]:
    calls: list[ApiCall] = []

    def tool_api_call(
        method: str,
        path: str,
        *,
        params: object | None = None,
        json_body: object | None = None,
        timeout: float = 30.0,
    ) -> object:
        calls.append((method, path, params, json_body, timeout))
        if path == "/mcp/servers":
            return {
                "servers": [
                    {"slug": "alpha", "transport": "stdio", "requiresEnv": []},
                    {"slug": "secret", "transport": "stdio", "requiresEnv": ["TOKEN"]},
                ],
                "commands": {
                    "listTools": "telec mcp list-tools <slug>",
                    "callTool": "telec mcp call <slug> <tool> --json '<arguments-json>'",
                },
            }
        if path == _LIST_TOOLS_PATH:
            return {"server": "alpha", "tools": [{"name": "alpha-tool"}, {"name": "echo/tool"}]}
        return {"server": "alpha", "tool": "alpha-tool", "result": {"content": [], "isError": False}}

    monkeypatch.setattr(mcp_handler, "tool_api_call", tool_api_call)
    monkeypatch.setattr(mcp_handler, "print_json", lambda data: print(data))
    return calls


@pytest.mark.spec(_SPEC, "UC-LMCP-1")
def test_mcp_list_forwards_repeated_excludes_and_prints_guidance(
    api_calls: list[ApiCall], capsys: pytest.CaptureFixture[str], snapshot: SnapshotAssertion
) -> None:
    mcp_handler._handle_mcp(["list", "--exclude", "firecrawl", "--exclude", "context7"])

    assert api_calls == snapshot(name="api")
    assert capsys.readouterr().out == snapshot(name="stdout")


@pytest.mark.spec(_SPEC, "UC-LMCP-2")
def test_mcp_list_tools_selects_server(
    api_calls: list[ApiCall], capsys: pytest.CaptureFixture[str], snapshot: SnapshotAssertion
) -> None:
    mcp_handler._handle_mcp(["list-tools", "alpha"])

    assert api_calls == snapshot(name="api")
    assert capsys.readouterr().out == snapshot(name="stdout")


@pytest.mark.spec(_SPEC, "UC-LMCP-3")
def test_mcp_call_parses_json_and_posts_tool_arguments(api_calls: list[ApiCall], snapshot: SnapshotAssertion) -> None:
    mcp_handler._handle_mcp(["call", "alpha", "alpha-tool", "--json", '{"enabled": true}'])

    assert api_calls == snapshot


@pytest.mark.spec(_SPEC, "UC-LMCP-3")
def test_mcp_call_rejects_invalid_json_before_api_call(
    api_calls: list[ApiCall], capsys: pytest.CaptureFixture[str], snapshot: SnapshotAssertion
) -> None:
    with pytest.raises(SystemExit):
        mcp_handler._handle_mcp(["call", "alpha", "alpha-tool", "--json", "{"])

    assert api_calls == []
    assert capsys.readouterr().err == snapshot


@pytest.mark.spec(_SPEC, "UC-LMCP-7")
def test_mcp_surface_declares_help(capsys: pytest.CaptureFixture[str], snapshot: SnapshotAssertion) -> None:
    assert CLI_SURFACE.get(TelecCommand.MCP.value) is not None
    assert _maybe_show_help("mcp", ["list", "--help"]) is True
    assert capsys.readouterr().out == snapshot
