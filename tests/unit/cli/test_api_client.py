"""Characterization tests for teleclaude/cli/api_client.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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
# TelecAPIClient._read_caller_session_id
# ---------------------------------------------------------------------------


def test_read_caller_session_id_reads_from_tmpdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    marker = tmp_path / "teleclaude_session_id"
    marker.write_text("my-session-id\n")
    client = TelecAPIClient()
    result = client._read_caller_session_id()
    assert result == "my-session-id"


def test_read_caller_session_id_returns_none_when_no_tmpdir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMPDIR", "")
    client = TelecAPIClient()
    result = client._read_caller_session_id()
    assert result is None


def test_read_caller_session_id_returns_none_when_file_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    client = TelecAPIClient()
    result = client._read_caller_session_id()
    assert result is None


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
    monkeypatch.setenv("TELEC_SESSION_TOKEN", "tok-abc")
    monkeypatch.setenv("TMPDIR", "")
    with patch("teleclaude.cli.api_client.read_current_session_email", return_value=None):
        with patch("teleclaude.cli.api_client.subprocess.run", side_effect=FileNotFoundError):
            client = TelecAPIClient()
            headers = client._build_identity_headers()
    assert headers.get("x-session-token") == "tok-abc"


def test_build_identity_headers_includes_email(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEC_SESSION_TOKEN", raising=False)
    monkeypatch.setenv("TMPDIR", "")
    with patch("teleclaude.cli.api_client.read_current_session_email", return_value="alice@example.com"):
        with patch("teleclaude.cli.api_client.subprocess.run", side_effect=FileNotFoundError):
            client = TelecAPIClient()
            headers = client._build_identity_headers()
    assert headers.get("x-telec-email") == "alice@example.com"


def test_build_identity_headers_excludes_absent_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEC_SESSION_TOKEN", raising=False)
    monkeypatch.setenv("TMPDIR", "")
    with patch("teleclaude.cli.api_client.read_current_session_email", return_value=None):
        with patch("teleclaude.cli.api_client.subprocess.run", side_effect=FileNotFoundError):
            client = TelecAPIClient()
            headers = client._build_identity_headers()
    assert "x-session-token" not in headers
    assert "x-telec-email" not in headers


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


# ---------------------------------------------------------------------------
# TelecAPIClient.subscribe / unsubscribe
# ---------------------------------------------------------------------------


def test_subscribe_sends_correct_payload() -> None:
    client = TelecAPIClient()
    sent: list[str] = []

    def _mock_send(payload: object) -> None:
        import json as _json

        sent.append(_json.dumps(payload))

    with patch.object(client, "_send_ws", side_effect=_mock_send):
        client.subscribe("local", ["sessions", "todos"])

    assert len(sent) == 1
    import json as _json

    data = _json.loads(sent[0])
    assert data["subscribe"]["computer"] == "local"
    assert set(data["subscribe"]["types"]) == {"sessions", "todos"}


def test_unsubscribe_sends_correct_payload() -> None:
    client = TelecAPIClient()
    sent: list[str] = []

    def _mock_send(payload: object) -> None:
        import json as _json

        sent.append(_json.dumps(payload))

    with patch.object(client, "_send_ws", side_effect=_mock_send):
        client.unsubscribe("remote")

    assert len(sent) == 1
    import json as _json

    data = _json.loads(sent[0])
    assert data["unsubscribe"]["computer"] == "remote"
