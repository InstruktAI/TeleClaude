"""Characterization tests for teleclaude/cli/api_client.py."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.cli import api_client as api_client_module
from teleclaude.cli.api_client import APIError, TelecAPIClient

# ---------------------------------------------------------------------------
# APIError
# ---------------------------------------------------------------------------


def test_api_error_stores_message() -> None:
    err = APIError("request failed")
    assert str(err) == "request failed"


def test_api_error_stores_status_code() -> None:
    err = APIError("not found", status_code=404)
    assert err.status_code == 404


def test_api_error_status_code_defaults_to_none() -> None:
    err = APIError("oops")
    assert err.status_code is None


def test_api_error_detail_falls_back_to_message_when_not_provided() -> None:
    err = APIError("full message here")
    assert err.detail == "full message here"


def test_api_error_detail_uses_provided_detail() -> None:
    err = APIError("full message", detail="short detail")
    assert err.detail == "short detail"


# ---------------------------------------------------------------------------
# TelecAPIClient.__init__
# ---------------------------------------------------------------------------


def test_telec_api_client_stores_socket_path() -> None:
    client = TelecAPIClient(socket_path="/tmp/test.sock")
    assert client.socket_path == "/tmp/test.sock"


def test_telec_api_client_not_connected_initially() -> None:
    client = TelecAPIClient()
    assert client.is_connected is False


def test_telec_api_client_ws_not_connected_initially() -> None:
    client = TelecAPIClient()
    assert client.ws_connected is False


def test_telec_api_client_subscriptions_empty_initially() -> None:
    client = TelecAPIClient()
    assert client._ws_subscriptions == set()


def test_telec_api_client_ws_not_running_initially() -> None:
    client = TelecAPIClient()
    assert client._ws_running is False


# ---------------------------------------------------------------------------
# TelecAPIClient._read_tmux_session_name
# ---------------------------------------------------------------------------


def test_read_tmux_session_name_returns_name_on_success() -> None:
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "my-session\n"
    client = TelecAPIClient()
    with patch("teleclaude.cli.api_client.subprocess.run", return_value=mock_result):
        result = client._read_tmux_session_name()
    assert result == "my-session"


def test_read_tmux_session_name_returns_none_when_tmux_not_found() -> None:
    client = TelecAPIClient()
    with patch("teleclaude.cli.api_client.subprocess.run", side_effect=FileNotFoundError):
        result = client._read_tmux_session_name()
    assert result is None


def test_read_tmux_session_name_returns_none_on_nonzero_exit() -> None:
    mock_result = MagicMock()
    mock_result.returncode = 1
    client = TelecAPIClient()
    with patch("teleclaude.cli.api_client.subprocess.run", return_value=mock_result):
        result = client._read_tmux_session_name()
    assert result is None


# ---------------------------------------------------------------------------
# TelecAPIClient._build_identity_headers
# ---------------------------------------------------------------------------


def test_build_identity_headers_includes_session_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMPDIR", "")
    with patch("teleclaude.cli.api_client.get_session_token", return_value="tok-abc"):
        with patch("teleclaude.cli.api_client.get_session_id", return_value=None):
            with patch("teleclaude.cli.api_client.read_current_session_email", return_value=None):
                with patch("teleclaude.cli.api_client.subprocess.run", side_effect=FileNotFoundError):
                    client = TelecAPIClient()
                    headers = client._build_identity_headers()
    assert headers.get("x-session-token") == "tok-abc"


def test_build_identity_headers_includes_email(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMPDIR", "")
    with patch("teleclaude.cli.api_client.read_current_session_email", return_value="alice@example.com"):
        with patch("teleclaude.cli.api_client.subprocess.run", side_effect=FileNotFoundError):
            client = TelecAPIClient()
            headers = client._build_identity_headers()
    assert headers.get("x-telec-email") == "alice@example.com"


def test_build_identity_headers_excludes_absent_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEC_SESSION_TOKEN", raising=False)
    monkeypatch.setenv("TMPDIR", "")
    with patch("teleclaude.cli.api_client.get_session_token", return_value=None):
        with patch("teleclaude.cli.api_client.read_current_session_email", return_value=None):
            with patch("teleclaude.cli.api_client.subprocess.run", side_effect=FileNotFoundError):
                client = TelecAPIClient()
                headers = client._build_identity_headers()
    assert "x-session-token" not in headers
    assert "x-telec-email" not in headers


def test_build_identity_headers_omits_stale_session_identity_in_tc_tui(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity_path = tmp_path / "teleclaude_identity.json"
    identity_path.write_text(json.dumps({"session_id": "closed-session", "session_token": "stale-token"}))
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    tmux_result = MagicMock(returncode=0, stdout="tc_tui\n")

    with patch("teleclaude.cli.api_client.read_current_session_email", return_value=None):
        with patch("teleclaude.cli.api_client.subprocess.run", return_value=tmux_result):
            client = TelecAPIClient()
            headers = client._build_identity_headers()

    assert headers == {"x-tmux-session": "tc_tui"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_session_posts_to_sessions_with_supplied_payload() -> None:
    """The daemon-facing client preserves create-session inputs when calling POST /sessions."""
    client = TelecAPIClient()
    response = MagicMock()
    response.text = '{"status":"success","session_id":"sess-edge","tmux_session_name":"tmux-edge","agent":"claude"}'

    with patch.object(client, "_request", new=AsyncMock(return_value=response)) as request_mock:
        result = await client.create_session(
            computer="local",
            project_path="/help-desk",
            agent="claude",
            thinking_mode="slow",
            title="WhatsApp: 15551234567",
            metadata={
                "origin": "whatsapp",
                "origin_metadata": {
                    "phone_number": "15551234567",
                    "platform": "whatsapp",
                },
            },
        )

    assert result.session_id == "sess-edge"
    request_mock.assert_awaited_once()
    method, path = request_mock.await_args.args
    request_options = request_mock.await_args.kwargs["request_options"]
    assert method == "POST"
    assert path == "/sessions"
    assert request_options.json_body == {
        "computer": "local",
        "project_path": "/help-desk",
        "agent": "claude",
        "thinking_mode": "slow",
        "launch_kind": "agent",
        "title": "WhatsApp: 15551234567",
        "message": None,
        "human_email": None,
        "human_role": None,
        "metadata": {
            "origin": "whatsapp",
            "origin_metadata": {
                "phone_number": "15551234567",
                "platform": "whatsapp",
            },
        },
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_session_posts_to_sessions_run_with_slash_command_payload() -> None:
    """The daemon-facing client preserves slash-command inputs when calling POST /sessions/run."""
    client = TelecAPIClient()
    response = MagicMock()
    response.text = '{"status":"success","session_id":"sess-edge","tmux_session_name":"tmux-edge","agent":"claude"}'

    with patch.object(client, "_request", new=AsyncMock(return_value=response)) as request_mock:
        result = await client.run_session(
            command="/next-prepare",
            args="edge-http-migration",
            project_path="/repo/demo",
            detach=True,
        )

    assert result.session_id == "sess-edge"
    request_mock.assert_awaited_once()
    method, path = request_mock.await_args.args
    request_options = request_mock.await_args.kwargs["request_options"]
    assert method == "POST"
    assert path == "/sessions/run"
    assert request_options.json_body == {
        "command": "/next-prepare",
        "args": "edge-http-migration",
        "project": "/repo/demo",
        "computer": "local",
        "agent": "claude",
        "thinking_mode": "slow",
        "detach": True,
        "additional_context": "",
        "subfolder": "",
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_tui_bootstrap_requests_selected_pillars_and_parses_partial_response() -> None:
    """The TUI bootstrap client uses one aggregate request and preserves pillar errors."""
    client = TelecAPIClient()
    response = MagicMock()
    response.text = json.dumps(
        {
            "requested": ["computers", "projects"],
            "data": {
                "computers": [
                    {
                        "name": "MozBook",
                        "status": "online",
                        "user": "morriz",
                        "host": "mozbook",
                        "is_local": True,
                        "tmux_binary": None,
                    }
                ],
            },
            "errors": [
                {
                    "pillar": "projects",
                    "message": "temporary read failure",
                    "retryable": True,
                }
            ],
        }
    )

    with patch.object(client, "_request", new=AsyncMock(return_value=response)) as request_mock:
        result = await client.get_tui_bootstrap(["computers", "projects"])

    request_mock.assert_awaited_once()
    method, path = request_mock.await_args.args
    request_options = request_mock.await_args.kwargs["request_options"]
    assert method == "GET"
    assert path == "/tui/bootstrap"
    assert request_options.params == {"pillars": "computers,projects"}
    assert result.complete is False
    assert result.data.computers[0].name == "MozBook"
    assert result.data.projects_with_todos is None
    assert result.errors[0].pillar == "projects"


# ---------------------------------------------------------------------------
# TelecAPIClient.start_websocket / stop_websocket
# ---------------------------------------------------------------------------


def test_start_websocket_sets_running_flag_and_starts_thread() -> None:
    client = TelecAPIClient()
    callback = MagicMock()
    with patch.object(client, "_ws_loop"):
        client.start_websocket(callback, subscriptions=["sessions"])
    assert client._ws_running is True
    client.stop_websocket()


def test_start_websocket_is_idempotent_when_already_running() -> None:
    client = TelecAPIClient()
    callback = MagicMock()
    with patch.object(client, "_ws_loop"):
        client.start_websocket(callback)
        thread_before = client._ws_thread
        client.start_websocket(callback)  # second call — no-op
        assert client._ws_thread is thread_before
    client.stop_websocket()


def test_stop_websocket_clears_running_flag() -> None:
    client = TelecAPIClient()
    callback = MagicMock()
    with patch.object(client, "_ws_loop"):
        client.start_websocket(callback)
    client.stop_websocket()
    assert client._ws_running is False


def test_ws_connect_and_run_subscribes_configured_remote_computers_on_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TelecAPIClient()

    class FakeWS:
        def __init__(self) -> None:
            self.sent: list[dict[str, dict[str, str | list[str]]]] = []

        def send(self, payload: str) -> None:
            self.sent.append(json.loads(payload))

        def __iter__(self):
            return iter(())

    fake_ws = FakeWS()

    monkeypatch.setattr(api_client_module, "unix_connect", lambda path, uri: fake_ws)
    monkeypatch.setattr(
        api_client_module,
        "config",
        SimpleNamespace(
            remote_computers=[
                SimpleNamespace(name="raspi"),
                SimpleNamespace(name="workstation"),
            ]
        ),
        raising=False,
    )
    client._ws_state.subscriptions = {"sessions", "preparation"}
    client._ws_state.running = True

    client._ws_connect_and_run()

    subscribe_targets = [payload["subscribe"]["computer"] for payload in fake_ws.sent]
    subscribe_types = [set(payload["subscribe"]["types"]) for payload in fake_ws.sent]
    assert subscribe_targets == ["local", "raspi", "workstation"]
    assert subscribe_types == [
        {"sessions", "preparation"},
        {"sessions", "preparation"},
        {"sessions", "preparation"},
    ]


# ---------------------------------------------------------------------------
# TelecAPIClient.subscribe / unsubscribe
# ---------------------------------------------------------------------------


def test_subscribe_sends_correct_payload() -> None:
    client = TelecAPIClient()
    sent: list[str] = []

    def _mock_send(payload: object) -> None:
        sent.append(json.dumps(payload))

    with patch.object(client, "_send_ws", side_effect=_mock_send):
        client.subscribe("local", ["sessions", "todos"])

    assert len(sent) == 1
    data = json.loads(sent[0])
    assert data["subscribe"]["computer"] == "local"
    assert set(data["subscribe"]["types"]) == {"sessions", "todos"}


def test_unsubscribe_sends_correct_payload() -> None:
    client = TelecAPIClient()
    sent: list[str] = []

    def _mock_send(payload: object) -> None:
        sent.append(json.dumps(payload))

    with patch.object(client, "_send_ws", side_effect=_mock_send):
        client.unsubscribe("remote")

    assert len(sent) == 1
    data = json.loads(sent[0])
    assert data["unsubscribe"]["computer"] == "remote"
