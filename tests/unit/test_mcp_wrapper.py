"""Unit tests for the resilient MCP stdio wrapper (bin/mcp-wrapper.py).

These tests avoid real AF_UNIX sockets because some macOS contexts restrict
socket operations (EPERM). We validate logic via in-memory streams/mocks.
"""

import asyncio
import io
import json
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


class _DummyStdout:
    def __init__(self) -> None:
        self.buffer = io.BytesIO()

    def flush(self) -> None:  # pragma: no cover
        return


class _FakeWriter:
    def __init__(self) -> None:
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        await asyncio.sleep(0)

    def close(self) -> None:  # pragma: no cover
        return

    async def wait_closed(self) -> None:  # pragma: no cover
        await asyncio.sleep(0)


def _load_wrapper_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MCP_WRAPPER_LOG_LEVEL", "CRITICAL")
    wrapper_path = Path(__file__).resolve().parents[2] / "bin" / "mcp-wrapper.py"
    spec = spec_from_file_location("teleclaude_test_mcp_wrapper", wrapper_path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@pytest.mark.asyncio
async def test_backend_resync_replays_handshake(monkeypatch: pytest.MonkeyPatch) -> None:
    wrapper = _load_wrapper_module(monkeypatch)
    proxy = wrapper.MCPProxy()

    proxy.writer = _FakeWriter()

    proxy._client_initialize_id = 1
    proxy._client_initialize_request = (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "0"},
                },
            }
        )
        + "\n"
    ).encode("utf-8")
    proxy._client_initialized_notification = (
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
    ).encode("utf-8")

    async def _signal_backend_init() -> None:
        await asyncio.sleep(0)
        proxy._backend_init_response.set()

    asyncio.create_task(_signal_backend_init())

    ok = await proxy._resync_backend_handshake()
    assert ok is True
    assert proxy.writer.writes[0] == proxy._client_initialize_request
    assert proxy.writer.writes[1] == proxy._client_initialized_notification


@pytest.mark.asyncio
async def test_socket_to_stdout_swallows_backend_initialize_response(monkeypatch: pytest.MonkeyPatch) -> None:
    wrapper = _load_wrapper_module(monkeypatch)
    proxy = wrapper.MCPProxy()

    dummy_stdout = _DummyStdout()
    monkeypatch.setattr(sys, "stdout", dummy_stdout)

    proxy.connected.set()
    proxy.reader = asyncio.StreamReader()
    proxy._client_initialize_id = 1
    proxy._suppress_backend_init_messages = True

    task = asyncio.create_task(proxy.socket_to_stdout())
    try:
        init_resp = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "teleclaude", "version": "test"},
            },
        }
        proxy.reader.feed_data((json.dumps(init_resp) + "\n").encode("utf-8"))

        await asyncio.sleep(0.01)
        assert proxy._backend_init_response.is_set() is True
        assert dummy_stdout.buffer.getvalue() == b""
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
