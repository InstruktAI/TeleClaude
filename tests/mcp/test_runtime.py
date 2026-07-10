"""Lazy MCP runtime tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.mcp.registry import McpRegistry, McpServerConfig, McpTransport
from teleclaude.mcp.runtime import McpRuntime, McpRuntimeError
from tests.mcp.fakes import fake_server_command, write_fake_mcp_server

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/agent_runtime/lazy-mcp-runtime"


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _registry(*servers: McpServerConfig) -> McpRegistry:
    return McpRegistry(servers={server.slug: server for server in servers})


def _read_log(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-LMCP-2")
async def test_list_tools_initializes_only_selected_server(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
    script = write_fake_mcp_server(tmp_path / "fake_mcp.py")
    log_path = tmp_path / "mcp.log"
    alpha_command, alpha_args = fake_server_command(script, name="alpha", log_path=log_path)
    beta_command, beta_args = fake_server_command(script, name="beta", log_path=log_path)
    runtime = McpRuntime(
        repo_root=tmp_path,
        registry=_registry(
            McpServerConfig(slug="alpha", command=alpha_command, args=tuple(alpha_args)),
            McpServerConfig(slug="beta", command=beta_command, args=tuple(beta_args)),
        ),
    )

    assert runtime.list_servers() == snapshot(name="catalog")
    result = await runtime.list_tools("alpha")
    cached_result = await runtime.list_tools("alpha")

    assert result == snapshot(name="tools")
    assert cached_result == result
    assert runtime.active_lease_slugs() == ["alpha"]
    assert _read_log(log_path) == snapshot(name="log")
    await runtime.close()


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-LMCP-3")
async def test_call_tool_reuses_warm_lease(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
    script = write_fake_mcp_server(tmp_path / "fake_mcp.py")
    log_path = tmp_path / "mcp.log"
    command, args = fake_server_command(script, name="alpha", log_path=log_path)
    runtime = McpRuntime(
        repo_root=tmp_path,
        registry=_registry(McpServerConfig(slug="alpha", command=command, args=tuple(args))),
    )

    await runtime.list_tools("alpha")
    result = await runtime.call_tool("alpha", "alpha-tool", {"value": True})

    assert result == snapshot(name="result")
    assert _read_log(log_path) == snapshot(name="log")
    await runtime.close()


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-LMCP-4")
async def test_serialized_calls_keep_responses_isolated(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
    script = write_fake_mcp_server(tmp_path / "fake_mcp.py")
    log_path = tmp_path / "mcp.log"
    command, args = fake_server_command(script, name="alpha", log_path=log_path, sleep_call=0.05)
    runtime = McpRuntime(
        repo_root=tmp_path,
        registry=_registry(McpServerConfig(slug="alpha", command=command, args=tuple(args))),
    )

    results = await asyncio.gather(
        runtime.call_tool("alpha", "first", {}),
        runtime.call_tool("alpha", "second", {}),
    )

    assert results == snapshot(name="results")
    assert _read_log(log_path) == snapshot(name="log")
    await runtime.close()


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-LMCP-2")
async def test_tool_list_changed_notification_invalidates_cached_catalog(tmp_path: Path, snapshot: object) -> None:
    script = write_fake_mcp_server(tmp_path / "fake_mcp.py")
    log_path = tmp_path / "mcp.log"
    command, args = fake_server_command(script, name="alpha", log_path=log_path)
    runtime = McpRuntime(
        repo_root=tmp_path,
        registry=_registry(McpServerConfig(slug="alpha", command=command, args=tuple(args))),
    )

    await runtime.list_tools("alpha")
    await runtime.call_tool("alpha", "emit-list-changed", {})
    await runtime.list_tools("alpha")

    assert _read_log(log_path) == snapshot
    await runtime.close()


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-LMCP-4")
async def test_tool_failure_does_not_poison_later_queued_call(tmp_path: Path, snapshot: object) -> None:
    script = write_fake_mcp_server(tmp_path / "fake_mcp.py")
    log_path = tmp_path / "mcp.log"
    command, args = fake_server_command(script, name="alpha", log_path=log_path, fail_tool="fail")
    runtime = McpRuntime(
        repo_root=tmp_path,
        registry=_registry(McpServerConfig(slug="alpha", command=command, args=tuple(args))),
    )

    with pytest.raises(McpRuntimeError) as exc_info:
        await runtime.call_tool("alpha", "fail", {})
    later = await runtime.call_tool("alpha", "later", {})

    assert {
        "error": exc_info.value.to_error_dict(),
        "later": later,
        "log": _read_log(log_path),
    } == snapshot
    await runtime.close()


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-LMCP-4")
async def test_cancelled_waiting_call_does_not_poison_later_call(tmp_path: Path, snapshot: object) -> None:
    script = write_fake_mcp_server(tmp_path / "fake_mcp.py")
    log_path = tmp_path / "mcp.log"
    command, args = fake_server_command(script, name="alpha", log_path=log_path, sleep_call=0.05)
    runtime = McpRuntime(
        repo_root=tmp_path,
        registry=_registry(McpServerConfig(slug="alpha", command=command, args=tuple(args))),
    )

    first = asyncio.create_task(runtime.call_tool("alpha", "first", {}))
    waiting = asyncio.create_task(runtime.call_tool("alpha", "cancelled", {}))
    await asyncio.sleep(0)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    await first
    later = await runtime.call_tool("alpha", "later", {})

    assert {"later": later, "log": _read_log(log_path)} == snapshot
    await runtime.close()


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-LMCP-4")
async def test_tool_timeout_closes_lease(tmp_path: Path, snapshot: SnapshotAssertion) -> None:
    script = write_fake_mcp_server(tmp_path / "fake_mcp.py")
    log_path = tmp_path / "mcp.log"
    command, args = fake_server_command(script, name="alpha", log_path=log_path, sleep_call=0.2)
    runtime = McpRuntime(
        repo_root=tmp_path,
        registry=_registry(McpServerConfig(slug="alpha", command=command, args=tuple(args), tool_timeout_seconds=0.01)),
    )

    with pytest.raises(McpRuntimeError) as exc_info:
        await runtime.call_tool("alpha", "slow", {})

    assert exc_info.value.to_error_dict() == snapshot(name="error")
    assert runtime.active_lease_slugs() == []
    assert _read_log(log_path) == snapshot(name="log")


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-LMCP-5")
async def test_idle_reaper_closes_expired_lease(tmp_path: Path, snapshot: object) -> None:
    script = write_fake_mcp_server(tmp_path / "fake_mcp.py")
    log_path = tmp_path / "mcp.log"
    command, args = fake_server_command(script, name="alpha", log_path=log_path)
    clock = _Clock()
    runtime = McpRuntime(
        repo_root=tmp_path,
        clock=clock,
        registry=_registry(McpServerConfig(slug="alpha", command=command, args=tuple(args), idle_ttl_seconds=5)),
    )

    await runtime.list_tools("alpha")
    clock.advance(6)
    await runtime.reap_idle()

    assert runtime.active_lease_slugs() == []
    assert _read_log(log_path) == snapshot


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-LMCP-7")
async def test_missing_env_fails_before_subprocess_start(tmp_path: Path, snapshot: object) -> None:
    script = write_fake_mcp_server(tmp_path / "fake_mcp.py")
    log_path = tmp_path / "mcp.log"
    command, args = fake_server_command(script, name="alpha", log_path=log_path)
    runtime = McpRuntime(
        repo_root=tmp_path,
        env_path=tmp_path / ".env",
        registry=_registry(
            McpServerConfig(
                slug="alpha",
                command=command,
                args=tuple(args),
                env={"FAKE_TOKEN": "${FAKE_TOKEN}"},
            )
        ),
    )

    with pytest.raises(McpRuntimeError) as exc_info:
        await runtime.list_tools("alpha")

    assert exc_info.value.to_error_dict() == snapshot
    assert _read_log(log_path) == []


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-LMCP-6")
async def test_env_drift_restarts_warm_lease_with_new_fingerprint(tmp_path: Path, snapshot: object) -> None:
    script = write_fake_mcp_server(tmp_path / "fake_mcp.py")
    env_path = tmp_path / ".env"
    log_path = tmp_path / "mcp.log"
    env_path.write_text("FAKE_TOKEN=one\n", encoding="utf-8")
    command, args = fake_server_command(script, name="alpha", log_path=log_path, require_env="FAKE_TOKEN")
    runtime = McpRuntime(
        repo_root=tmp_path,
        env_path=env_path,
        registry=_registry(
            McpServerConfig(
                slug="alpha",
                command=command,
                args=tuple(args),
                env={"FAKE_TOKEN": "${FAKE_TOKEN}"},
            )
        ),
    )

    await runtime.list_tools("alpha")
    env_path.write_text("FAKE_TOKEN=two\n", encoding="utf-8")
    await runtime.list_tools("alpha")

    assert runtime.active_lease_slugs() == ["alpha"]
    assert _read_log(log_path) == snapshot
    await runtime.close()


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-LMCP-7")
async def test_child_process_receives_only_server_env_and_process_basics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot: object
) -> None:
    script = write_fake_mcp_server(tmp_path / "fake_mcp.py")
    env_path = tmp_path / ".env"
    log_path = tmp_path / "mcp.log"
    env_path.write_text("FAKE_TOKEN=allowed\n", encoding="utf-8")
    monkeypatch.setenv("TELECLAUDE_SHOULD_NOT_LEAK", "secret")
    command, args = fake_server_command(
        script,
        name="alpha",
        log_path=log_path,
        forbid_env="TELECLAUDE_SHOULD_NOT_LEAK",
        require_env="FAKE_TOKEN",
    )
    runtime = McpRuntime(
        repo_root=tmp_path,
        env_path=env_path,
        registry=_registry(
            McpServerConfig(
                slug="alpha",
                command=command,
                args=tuple(args),
                env={"FAKE_TOKEN": "${FAKE_TOKEN}"},
            )
        ),
    )

    await runtime.list_tools("alpha")

    assert _read_log(log_path) == snapshot
    await runtime.close()


@pytest.mark.asyncio
@pytest.mark.spec(_SPEC, "UC-LMCP-7")
async def test_remote_headers_with_secret_placeholders_fail_closed(tmp_path: Path, snapshot: object) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("SECRET_TOKEN=value\n", encoding="utf-8")
    runtime = McpRuntime(
        repo_root=tmp_path,
        env_path=env_path,
        registry=_registry(
            McpServerConfig(
                slug="remote",
                transport=McpTransport.HTTP,
                url="https://example.test/mcp",
                headers={"Authorization": "Bearer ${SECRET_TOKEN}"},
            )
        ),
    )

    with pytest.raises(McpRuntimeError) as exc_info:
        await runtime.list_tools("remote")

    assert exc_info.value.to_error_dict() == snapshot
