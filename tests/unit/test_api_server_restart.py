"""Unit tests for API server server exit handling."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from teleclaude.api_server import API_TIMEOUT_KEEP_ALIVE_S, APIServer, _get_fd_count


class _DummyClient:
    def on(self, *_args: object, **_kwargs: object) -> None:
        return None


class _DummyTask:
    def exception(self) -> Exception | None:
        return None


class _TestAPIServer(APIServer):
    async def create_channel(self, *_args, **_kwargs):  # type: ignore[override]
        return ""

    async def update_channel_title(self, *_args, **_kwargs):  # type: ignore[override]
        return True

    async def close_channel(self, *_args, **_kwargs):  # type: ignore[override]
        return True

    async def reopen_channel(self, *_args, **_kwargs):  # type: ignore[override]
        return True

    async def delete_channel(self, *_args, **_kwargs):  # type: ignore[override]
        return True

    async def send_message(self, *_args, **_kwargs):  # type: ignore[override]
        return None

    async def edit_message(self, *_args, **_kwargs):  # type: ignore[override]
        return None

    async def delete_message(self, *_args, **_kwargs):  # type: ignore[override]
        return True

    async def send_file(self, *_args, **_kwargs):  # type: ignore[override]
        return None

    async def poll_output_stream(self, *_args, **_kwargs):  # type: ignore[override]
        return None

    async def discover_peers(self, *_args, **_kwargs):  # type: ignore[override]
        return []


def test_api_server_done_calls_exit_handler_when_running() -> None:
    adapter = _TestAPIServer(_DummyClient())
    adapter._running = True

    class _Server:
        def __init__(self) -> None:
            self.started = True
            self.should_exit = True

    adapter.server = _Server()
    handler = MagicMock()
    adapter.set_on_server_exit(handler)

    adapter._on_server_task_done(_DummyTask())

    handler.assert_called_once()
    exc, started, should_exit, socket_exists = handler.call_args.args
    assert exc is None
    assert started is True
    assert should_exit is True
    assert isinstance(socket_exists, bool)


def test_api_server_done_noop_when_stopped() -> None:
    adapter = _TestAPIServer(_DummyClient())
    adapter._running = False
    handler = MagicMock()
    adapter.set_on_server_exit(handler)

    adapter._on_server_task_done(_DummyTask())

    handler.assert_not_called()


@pytest.mark.asyncio
async def test_stop_server_sets_should_exit_when_started() -> None:
    adapter = _TestAPIServer(_DummyClient())

    class _Server:
        def __init__(self) -> None:
            self.started = True
            self.should_exit = False

    adapter.server = _Server()
    adapter.server_task = None

    await adapter._stop_server()

    assert adapter.server.should_exit is True


@pytest.mark.asyncio
async def test_start_configures_ws_keepalive(monkeypatch) -> None:
    captured = {}

    def fake_config(*_args, **kwargs):
        captured.update(kwargs)
        return MagicMock()

    class _FakeServer:
        def __init__(self, _config) -> None:
            self.started = True

        async def serve(self) -> None:
            return None

    monkeypatch.setattr("teleclaude.api_server.uvicorn.Config", fake_config)
    monkeypatch.setattr("teleclaude.api_server.uvicorn.Server", _FakeServer)
    adapter = _TestAPIServer(_DummyClient())

    monkeypatch.setattr(adapter, "_cleanup_socket", lambda _reason: None)
    await adapter._start_server()

    assert captured["ws_ping_interval"] == 20.0
    assert captured["ws_ping_timeout"] == 20.0
    assert captured["timeout_keep_alive"] == API_TIMEOUT_KEEP_ALIVE_S


def test_get_fd_count_uses_dev_fd(monkeypatch) -> None:
    monkeypatch.setattr("teleclaude.api_server.os.listdir", lambda _path: ["0", "1", "2", "3"])

    assert _get_fd_count() == 4
