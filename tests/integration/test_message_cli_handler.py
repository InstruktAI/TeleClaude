"""Argument-parsing and dispatch coverage for the ``telec message`` CLI handler.

No feature spec exists for this command-surface-refinement todo (Category B),
so this test carries no ``@pytest.mark.spec`` marker. Only the daemon-socket
call (``tool_api_request``) is faked — the handler's own parsing and request
construction are under test.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from teleclaude.cli.telec.handlers import message as message_handlers

_SLUG = "alex"
_TEXT = "Heads up"
_ATTACHMENT_PATH = "/tmp/report.pdf"
_SUBJECT = "Weekly digest"
_CHANNEL_EMAIL = "email"


def test_slug_and_text_become_the_request_body(monkeypatch: pytest.MonkeyPatch) -> None:
    tool_api_request = MagicMock(return_value={"status": "ok", "channel": "telegram"})
    monkeypatch.setattr(message_handlers, "tool_api_request", tool_api_request)

    message_handlers._handle_message([_SLUG, _TEXT])

    json_body = tool_api_request.call_args.kwargs["json_body"]
    assert json_body["slug"] == _SLUG
    assert json_body["text"] == _TEXT
    assert json_body["file"] is None
    assert json_body["subject"] is None
    assert json_body["channel"] is None


def test_file_subject_and_channel_flags_populate_the_request_body(monkeypatch: pytest.MonkeyPatch) -> None:
    tool_api_request = MagicMock(return_value={"status": "ok", "channel": _CHANNEL_EMAIL})
    monkeypatch.setattr(message_handlers, "tool_api_request", tool_api_request)

    message_handlers._handle_message(
        [_SLUG, _TEXT, "--file", _ATTACHMENT_PATH, "--subject", _SUBJECT, "--channel", _CHANNEL_EMAIL]
    )

    json_body = tool_api_request.call_args.kwargs["json_body"]
    assert json_body["file"] == _ATTACHMENT_PATH
    assert json_body["subject"] == _SUBJECT
    assert json_body["channel"] == _CHANNEL_EMAIL


def test_invalid_channel_exits_without_calling_the_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    tool_api_request = MagicMock()
    monkeypatch.setattr(message_handlers, "tool_api_request", tool_api_request)

    with pytest.raises(SystemExit):
        message_handlers._handle_message([_SLUG, _TEXT, "--channel", "sms"])

    tool_api_request.assert_not_called()


def test_missing_text_argument_exits_without_calling_the_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    tool_api_request = MagicMock()
    monkeypatch.setattr(message_handlers, "tool_api_request", tool_api_request)

    with pytest.raises(SystemExit):
        message_handlers._handle_message([_SLUG])

    tool_api_request.assert_not_called()


def test_daemon_error_response_exits_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    tool_api_request = MagicMock(return_value={"status": "error", "detail": "No person found for slug 'alex'"})
    monkeypatch.setattr(message_handlers, "tool_api_request", tool_api_request)

    with pytest.raises(SystemExit):
        message_handlers._handle_message([_SLUG, _TEXT])
