"""Characterization tests for teleclaude/cli/tool_client.py."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from teleclaude.cli.tool_client import (
    ToolAPIError,
    _extract_detail,
    _read_tmux_session_name,
    print_json,
    tool_api_call,
    tool_api_request,
)

# ---------------------------------------------------------------------------
# ToolAPIError
# ---------------------------------------------------------------------------


def test_tool_api_error_stores_message() -> None:
    err = ToolAPIError("connection refused")
    assert err.message == "connection refused"
    assert str(err) == "connection refused"


def test_tool_api_error_stores_status_code() -> None:
    err = ToolAPIError("forbidden", status_code=403)
    assert err.status_code == 403


def test_tool_api_error_status_code_defaults_to_none() -> None:
    err = ToolAPIError("timeout")
    assert err.status_code is None


def test_tool_api_error_is_timeout_flag() -> None:
    err = ToolAPIError("timed out", is_timeout=True)
    assert err.is_timeout is True


def test_tool_api_error_is_timeout_defaults_false() -> None:
    err = ToolAPIError("other error")
    assert err.is_timeout is False


# ---------------------------------------------------------------------------
# _read_tmux_session_name
# ---------------------------------------------------------------------------


def test_read_tmux_session_name_returns_name_on_success() -> None:
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "my-session\n"
    with patch("teleclaude.cli.tool_client.subprocess.run", return_value=mock_result):
        result = _read_tmux_session_name()
    assert result == "my-session"


def test_read_tmux_session_name_returns_none_when_tmux_not_found() -> None:
    with patch("teleclaude.cli.tool_client.subprocess.run", side_effect=FileNotFoundError):
        result = _read_tmux_session_name()
    assert result is None


def test_read_tmux_session_name_returns_none_on_nonzero_exit() -> None:
    mock_result = MagicMock()
    mock_result.returncode = 1
    with patch("teleclaude.cli.tool_client.subprocess.run", return_value=mock_result):
        result = _read_tmux_session_name()
    assert result is None


def test_tool_api_request_omits_stale_session_headers_in_tc_tui(
    tmp_path: Path,
) -> None:
    """The dedicated TUI must authenticate as a terminal, not a stale session."""
    identity_path = tmp_path / "teleclaude_identity.json"
    identity_path.write_text(json.dumps({"session_id": "closed-session", "session_token": "stale-token"}))
    tmux_result = MagicMock(returncode=0, stdout="tc_tui\n")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "ok"}

    with (
        patch.dict("os.environ", {"TMPDIR": str(tmp_path)}, clear=False),
        patch("teleclaude.cli.tool_client.read_current_session_email", return_value=None),
        patch("teleclaude.cli.tool_client.subprocess.run", return_value=tmux_result),
        patch("teleclaude.cli.tool_client.httpx.Client") as mock_client_cls,
    ):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        tool_api_request("GET", "/sessions")

    headers = mock_client.request.call_args.kwargs["headers"]
    assert headers == {"x-tmux-session": "tc_tui"}


# ---------------------------------------------------------------------------
# _extract_detail
# ---------------------------------------------------------------------------


def test_extract_detail_from_json_dict_response() -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"detail": "access denied"}
    result = _extract_detail(mock_resp)
    assert result == "access denied"


def test_extract_detail_falls_back_to_text_when_no_detail_key() -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"error": "other"}
    mock_resp.text = "plain error text"
    result = _extract_detail(mock_resp)
    assert result == "plain error text"


def test_extract_detail_falls_back_to_text_on_json_error() -> None:
    mock_resp = MagicMock()
    mock_resp.json.side_effect = Exception("not json")
    mock_resp.text = "raw body"
    result = _extract_detail(mock_resp)
    assert result == "raw body"


# ---------------------------------------------------------------------------
# print_json
# ---------------------------------------------------------------------------


def test_print_json_outputs_formatted_json(capsys: pytest.CaptureFixture[str]) -> None:
    print_json({"key": "value"})
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed == {"key": "value"}


def test_print_json_handles_list(capsys: pytest.CaptureFixture[str]) -> None:
    print_json([1, 2, 3])
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed == [1, 2, 3]


# ---------------------------------------------------------------------------
# tool_api_request — socket unavailable raises ToolAPIError
# ---------------------------------------------------------------------------


def test_tool_api_request_raises_on_connect_error() -> None:
    with patch("teleclaude.cli.tool_client.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.side_effect = httpx.ConnectError("socket not found")
        mock_client_cls.return_value = mock_client
        with pytest.raises(ToolAPIError) as exc_info:
            tool_api_request("GET", "/sessions", socket_path="/nonexistent.sock")
    assert exc_info.value.status_code is None


def test_tool_api_request_raises_on_401() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.json.return_value = {"detail": "unauthorized"}
    mock_resp.text = "unauthorized"
    with patch("teleclaude.cli.tool_client.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.return_value = mock_resp
        mock_client_cls.return_value = mock_client
        with pytest.raises(ToolAPIError) as exc_info:
            tool_api_request("GET", "/sessions")
    assert exc_info.value.status_code == 401


def test_tool_api_request_raises_on_403() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.json.return_value = {"detail": "forbidden"}
    mock_resp.text = "forbidden"
    with patch("teleclaude.cli.tool_client.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.return_value = mock_resp
        mock_client_cls.return_value = mock_client
        with pytest.raises(ToolAPIError) as exc_info:
            tool_api_request("GET", "/sessions")
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# tool_api_call — exits on ToolAPIError
# ---------------------------------------------------------------------------


def test_tool_api_call_raises_system_exit_on_error() -> None:
    with patch("teleclaude.cli.tool_client.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.side_effect = httpx.ConnectError("no socket")
        mock_client_cls.return_value = mock_client
        with pytest.raises(SystemExit):
            tool_api_call("GET", "/sessions", socket_path="/nonexistent.sock")
