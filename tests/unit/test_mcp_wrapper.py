"""Unit tests for the resilient MCP stdio wrapper (bin/mcp-wrapper.py).

These tests avoid real AF_UNIX sockets because some macOS contexts restrict
socket operations (EPERM). We validate logic via in-memory streams/mocks.
"""

import asyncio
import io
import json
import sqlite3
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


def _init_session_db(db_path: Path, session_id: str, tmux_name: str) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                tmux_session_name TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO sessions (session_id, tmux_session_name) VALUES (?, ?)",
            (session_id, tmux_name),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_backend_resync_replays_handshake(monkeypatch: pytest.MonkeyPatch) -> None:
    """Paranoid test that backend resync replays handshake still holds when everything is on fire."""
    wrapper = _load_wrapper_module(monkeypatch)
    proxy = wrapper._impl.MCPProxy()

    proxy.writer = _FakeWriter()
    proxy._needs_backend_resync = True

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
async def test_startup_resync_replays_handshake(monkeypatch: pytest.MonkeyPatch) -> None:
    """Paranoid test that startup resync replays handshake still holds when everything is on fire."""
    wrapper = _load_wrapper_module(monkeypatch)
    proxy = wrapper.MCPProxy()

    proxy.writer = _FakeWriter()
    proxy.connected.set()
    proxy._needs_backend_resync = True

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

    await proxy._startup_resync()

    assert proxy._needs_backend_resync is False
    assert proxy.writer.writes[0] == proxy._client_initialize_request


@pytest.mark.asyncio
async def test_socket_to_stdout_swallows_backend_initialize_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """Paranoid test that socket to stdout swallows backend initialize response still holds when everything is on fire."""
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
    """Paranoid test that cached handshake emits single response still holds when everything is on fire."""
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
    """Paranoid test that handle initialize times out still holds when everything is on fire."""
    wrapper = _load_wrapper_module(monkeypatch)
    wrapper._impl.INIT_TIMEOUT = 0.01
    proxy = wrapper._impl.MCPProxy()

    reader = asyncio.StreamReader()

    ok = await proxy.handle_initialize(reader)
    assert ok is False


@pytest.mark.asyncio
async def test_handle_initialize_schedules_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    """Paranoid test that handle initialize schedules reconnect still holds when everything is on fire."""
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
    """Paranoid test that response timeout sends error still holds when everything is on fire."""
    wrapper = _load_wrapper_module(monkeypatch)
    monkeypatch.setattr(wrapper._impl, "RESPONSE_CHECK_INTERVAL", 0.01)
    proxy = wrapper.MCPProxy()

    now = asyncio.get_running_loop().time()
    proxy._pending_requests = {123: now - 0.1}

    sent: dict[str, object] = {}  # type: boundary - Test fixture data

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
    """Paranoid test that socket to stdout drops late response still holds when everything is on fire."""
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
    """Paranoid test that socket sender exits on shutdown still holds when everything is on fire."""
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


@pytest.mark.asyncio
async def test_long_running_tool_uses_extended_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Paranoid test that long running tool uses extended timeout still holds when everything is on fire."""
    wrapper = _load_wrapper_module(monkeypatch)
    proxy = wrapper.MCPProxy()

    reader = asyncio.StreamReader()
    msg = {
        "jsonrpc": "2.0",
        "id": 42,
        "method": "tools/call",
        "params": {"name": "teleclaude__run_agent_command", "arguments": {}},
    }
    reader.feed_data((json.dumps(msg) + "\n").encode("utf-8"))
    reader.feed_eof()

    await proxy.stdin_to_socket(reader)

    started_at = proxy._pending_started[42]
    deadline = proxy._pending_requests[42]
    assert deadline - started_at >= 59.0


@pytest.mark.asyncio
async def test_acquire_connect_lock_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """Paranoid test that acquire connect lock times out still holds when everything is on fire."""
    wrapper = _load_wrapper_module(monkeypatch)
    proxy = wrapper.MCPProxy()

    monkeypatch.setattr(wrapper._impl, "CONNECT_LOCK_SLOTS", 1)
    monkeypatch.setattr(wrapper._impl, "CONNECT_LOCK_TIMEOUT", 0.0)
    monkeypatch.setattr(wrapper._impl, "CONNECT_LOCK_RETRY_S", 0.0)

    calls: dict[str, int] = {"open": 0, "flock": 0, "close": 0}

    def fake_open(_path: str, _flags: int) -> int:
        calls["open"] += 1
        return 123

    def fake_flock(_fd: int, _flags: int) -> None:
        calls["flock"] += 1
        raise BlockingIOError()

    def fake_close(_fd: int) -> None:
        calls["close"] += 1

    monkeypatch.setattr(wrapper._impl.os, "open", fake_open)
    monkeypatch.setattr(wrapper._impl.fcntl, "flock", fake_flock)
    monkeypatch.setattr(wrapper._impl.os, "close", fake_close)

    fd = await proxy._acquire_connect_lock()

    assert fd is None
    assert calls["open"] == 1
    assert calls["flock"] == 1
    assert calls["close"] == 1


@pytest.mark.asyncio
async def test_connect_guard_enables_after_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    """Paranoid test that connect guard enables after failures still holds when everything is on fire."""
    wrapper = _load_wrapper_module(monkeypatch)
    proxy = wrapper._impl.MCPProxy()

    monkeypatch.setattr(wrapper._impl, "CONNECT_LOCK_FAILS", 2)
    monkeypatch.setattr(wrapper._impl, "CONNECT_LOCK_WINDOW_S", 10.0)

    proxy._note_connect_failure()
    assert proxy._should_use_connect_lock() is False

    proxy._note_connect_failure()
    assert proxy._should_use_connect_lock() is True

    proxy._reset_connect_guard()
    assert proxy._should_use_connect_lock() is False


@pytest.mark.asyncio
async def test_tools_list_uses_cached_response(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Paranoid test that tools list uses cached response still holds when everything is on fire."""
    monkeypatch.setenv("MCP_WRAPPER_TOOL_CACHE_PATH", str(tmp_path / "missing.json"))
    wrapper = _load_wrapper_module(monkeypatch)
    proxy = wrapper._impl.MCPProxy()

    dummy_stdout = _DummyStdout()
    monkeypatch.setattr(sys, "stdout", dummy_stdout)

    wrapper._impl.TOOL_LIST_CACHE = [
        {
            "name": "teleclaude__noop",
            "description": "",
            "inputSchema": {"type": "object", "properties": {}},
        }
    ]

    reader = asyncio.StreamReader()
    request = {"jsonrpc": "2.0", "id": 9, "method": "tools/list"}
    reader.feed_data((json.dumps(request) + "\n").encode("utf-8"))
    reader.feed_eof()

    await proxy.stdin_to_socket(reader)

    output = dummy_stdout.buffer.getvalue().decode("utf-8").strip()
    response = json.loads(output)
    assert response["id"] == 9
    assert response["result"]["tools"] == wrapper._impl.TOOL_LIST_CACHE


@pytest.mark.asyncio
async def test_tools_list_errors_without_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Paranoid test that tools list errors without cache still holds when everything is on fire."""
    monkeypatch.setenv("MCP_WRAPPER_TOOL_CACHE_PATH", str(tmp_path / "missing.json"))
    wrapper = _load_wrapper_module(monkeypatch)
    proxy = wrapper._impl.MCPProxy()

    dummy_stdout = _DummyStdout()
    monkeypatch.setattr(sys, "stdout", dummy_stdout)

    wrapper._impl.TOOL_LIST_CACHE = None

    reader = asyncio.StreamReader()
    request = {"jsonrpc": "2.0", "id": 10, "method": "tools/list"}
    reader.feed_data((json.dumps(request) + "\n").encode("utf-8"))
    reader.feed_eof()

    await proxy.stdin_to_socket(reader)

    output = dummy_stdout.buffer.getvalue().decode("utf-8").strip()
    response = json.loads(output)
    assert response["id"] == 10
    assert response["error"]["code"] == wrapper._impl._ERR_BACKEND_UNAVAILABLE


@pytest.mark.asyncio
async def test_tools_list_forwards_when_connected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Paranoid test that tools list forwards when connected still holds when everything is on fire."""
    wrapper = _load_wrapper_module(monkeypatch)
    proxy = wrapper._impl.MCPProxy()

    class _DummyWriter:
        def write(self, _data: bytes) -> None:
            pass

        async def drain(self) -> None:
            return None

    proxy.writer = _DummyWriter()
    proxy.connected.set()

    dummy_stdout = _DummyStdout()
    monkeypatch.setattr(sys, "stdout", dummy_stdout)

    reader = asyncio.StreamReader()
    request = {"jsonrpc": "2.0", "id": 11, "method": "tools/list"}
    reader.feed_data((json.dumps(request) + "\n").encode("utf-8"))
    reader.feed_eof()

    await proxy.stdin_to_socket(reader)

    assert dummy_stdout.buffer.getvalue() == b""
    assert proxy._outbound.qsize() == 1
    assert 11 in proxy._pending_requests


def test_inject_context_does_not_use_tmux_lookup_for_caller_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Paranoid test that inject context does not use tmux lookup for caller session."""
    wrapper = _load_wrapper_module(monkeypatch)

    db_path = tmp_path / "teleclaude.db"
    session_id = "session-123"
    tmux_name = "tc_session"
    _init_session_db(db_path, session_id, tmux_name)

    tmpdir = "/tmp/teleclaude-test-tmux"
    monkeypatch.setenv("TMPDIR", tmpdir)
    monkeypatch.setenv("TMP", tmpdir)
    monkeypatch.setenv("TEMP", tmpdir)
    monkeypatch.setenv("WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("TMUX", "/tmp/tmux-1/default,123,0")

    params = {"arguments": {}}
    out = wrapper.inject_context(params)
    assert "caller_session_id" not in out["arguments"]


def test_inject_context_uses_tmpdir_marker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Paranoid test that inject context uses tmpdir marker still holds when everything is on fire."""
    wrapper = _load_wrapper_module(monkeypatch)

    session_id = "fe4aff3e-8f3b-483f-bd3d-4a09811bb3ba"
    tmpdir = tmp_path / "session_tmp"
    tmpdir.mkdir()
    (tmpdir / "teleclaude_session_id").write_text(session_id, encoding="utf-8")
    monkeypatch.setenv("TMPDIR", str(tmpdir))
    monkeypatch.delenv("TMUX", raising=False)

    params = {"arguments": {}}
    out = wrapper.inject_context(params)
    assert out["arguments"]["caller_session_id"] == session_id


def test_inject_context_does_not_use_tmpdir_path_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Paranoid test that inject context does not use tmpdir path fallback still holds when everything is on fire."""
    wrapper = _load_wrapper_module(monkeypatch)

    session_id = "fe4aff3e-8f3b-483f-bd3d-4a09811bb3ba"
    monkeypatch.setenv("TMPDIR", f"/Users/morriz/.teleclaude/tmp/sessions/{session_id}")
    monkeypatch.delenv("TMP", raising=False)
    monkeypatch.delenv("TEMP", raising=False)
    monkeypatch.delenv("TMUX", raising=False)

    params = {"arguments": {}}
    out = wrapper.inject_context(params)
    assert "caller_session_id" not in out["arguments"]


def test_inject_context_overrides_blank_caller_session_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Paranoid test that inject context overrides blank caller session id still holds when everything is on fire."""
    wrapper = _load_wrapper_module(monkeypatch)

    session_id = "session-123"
    tmpdir = tmp_path / "session_tmp"
    tmpdir.mkdir()
    (tmpdir / "teleclaude_session_id").write_text(session_id, encoding="utf-8")
    monkeypatch.setenv("TMPDIR", str(tmpdir))
    monkeypatch.delenv("TMP", raising=False)
    monkeypatch.delenv("TEMP", raising=False)

    params_empty = {"arguments": {"caller_session_id": ""}}
    out_empty = wrapper.inject_context(params_empty)
    assert out_empty["arguments"]["caller_session_id"] == session_id

    params_none = {"arguments": {"caller_session_id": None}}
    out_none = wrapper.inject_context(params_none)
    assert out_none["arguments"]["caller_session_id"] == session_id
