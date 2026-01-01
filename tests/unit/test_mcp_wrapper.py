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


class _InstantQueue:
    def __init__(self, item: dict) -> None:
        self._item = item
        self._used = False

    def empty(self) -> bool:
        return self._used

    async def get(self) -> dict:
        if self._used:
            await asyncio.sleep(0)
            raise asyncio.TimeoutError
        self._used = True
        return self._item


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

    ok = await proxy._resync_backend_handshake(1.0)
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


@pytest.mark.asyncio
async def test_cached_handshake_emits_single_response(monkeypatch: pytest.MonkeyPatch) -> None:
    wrapper = _load_wrapper_module(monkeypatch)
    proxy = wrapper.MCPProxy()

    dummy_stdout = _DummyStdout()
    monkeypatch.setattr(sys, "stdout", dummy_stdout)

    async def _never_ready() -> None:
        await asyncio.sleep(1)

    monkeypatch.setattr(proxy.connected, "wait", _never_ready)

    reader = asyncio.StreamReader()
    init = {
        "jsonrpc": "2.0",
        "id": 42,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0"},
        },
    }
    reader.feed_data((json.dumps(init) + "\n").encode("utf-8"))
    reader.feed_eof()

    ok = await proxy.handle_initialize(reader)
    assert ok is True

    output = dummy_stdout.buffer.getvalue().decode("utf-8")
    lines = [line for line in output.splitlines() if line.strip()]
    assert len(lines) == 1
    message = json.loads(lines[0])
    assert message.get("id") == 42


@pytest.mark.asyncio
async def test_handle_initialize_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    wrapper = _load_wrapper_module(monkeypatch)
    wrapper.INIT_TIMEOUT = 0.01
    proxy = wrapper.MCPProxy()

    reader = asyncio.StreamReader()

    ok = await proxy.handle_initialize(reader)
    assert ok is False


@pytest.mark.asyncio
async def test_handle_initialize_schedules_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    wrapper = _load_wrapper_module(monkeypatch)
    proxy = wrapper.MCPProxy()

    called = {"value": False}

    def _schedule(_reason: str) -> None:
        called["value"] = True

    async def _ready() -> None:
        return None

    proxy._schedule_reconnect = _schedule
    monkeypatch.setattr(proxy.connected, "wait", _ready)

    reader = asyncio.StreamReader()
    init = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "pytest"}},
    }
    reader.feed_data((json.dumps(init) + "\n").encode("utf-8"))
    reader.feed_eof()

    ok = await proxy.handle_initialize(reader)
    assert ok is True
    assert called["value"] is True


@pytest.mark.asyncio
async def test_response_timeout_sends_error(monkeypatch: pytest.MonkeyPatch) -> None:
    wrapper = _load_wrapper_module(monkeypatch)
    monkeypatch.setattr(wrapper, "RESPONSE_CHECK_INTERVAL", 0.01)
    proxy = wrapper.MCPProxy()

    now = asyncio.get_running_loop().time()
    proxy._pending_requests = {123: now - 0.1}

    sent: dict[str, object] = {}  # noqa: loose-dict - Test fixture data

    async def _send_error(request_id: object, message: str) -> None:
        sent["id"] = request_id
        sent["message"] = message
        proxy.shutdown.set()

    proxy._send_error = _send_error  # type: ignore[assignment]

    task = asyncio.create_task(proxy._response_timeout_watcher())
    await asyncio.wait_for(proxy.shutdown.wait(), 1.0)
    await asyncio.wait_for(task, 1.0)

    assert sent["id"] == 123
    assert 123 not in proxy._pending_requests
    assert 123 in proxy._timed_out_requests


@pytest.mark.asyncio
async def test_socket_to_stdout_drops_late_response(monkeypatch: pytest.MonkeyPatch) -> None:
    wrapper = _load_wrapper_module(monkeypatch)
    proxy = wrapper.MCPProxy()

    dummy_stdout = _DummyStdout()
    monkeypatch.setattr(sys, "stdout", dummy_stdout)

    proxy.connected.set()
    proxy.reader = asyncio.StreamReader()
    proxy._timed_out_requests[5] = asyncio.get_running_loop().time()

    task = asyncio.create_task(proxy.socket_to_stdout())
    try:
        response = {"jsonrpc": "2.0", "id": 5, "result": {"ok": True}}
        proxy.reader.feed_data((json.dumps(response) + "\n").encode("utf-8"))
        await asyncio.sleep(0.01)
        assert dummy_stdout.buffer.getvalue() == b""
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_socket_sender_exits_on_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    wrapper = _load_wrapper_module(monkeypatch)
    proxy = wrapper.MCPProxy()

    proxy.shutdown.set()
    proxy._outbound = _InstantQueue(  # type: ignore[assignment]
        {
            "raw": b"{}",
            "request_id": None,
            "method": None,
            "enqueued_at": asyncio.get_running_loop().time(),
            "attempts": 0,
        }
    )

    await proxy._socket_sender()
