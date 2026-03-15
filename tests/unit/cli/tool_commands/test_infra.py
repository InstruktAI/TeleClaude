from __future__ import annotations

import importlib
from unittest.mock import MagicMock

import pytest

infra = importlib.import_module("teleclaude.cli.tool_commands.infra")


def test_handle_computers_requests_inventory(monkeypatch: pytest.MonkeyPatch) -> None:
    tool_api_call = MagicMock(return_value=[{"name": "local"}])
    print_json = MagicMock()

    monkeypatch.setattr(infra, "tool_api_call", tool_api_call)
    monkeypatch.setattr(infra, "print_json", print_json)

    infra.handle_computers([])

    tool_api_call.assert_called_once_with("GET", "/computers")
    print_json.assert_called_once()


def test_handle_projects_passes_optional_computer_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    tool_api_call = MagicMock(return_value=[])
    print_json = MagicMock()

    monkeypatch.setattr(infra, "tool_api_call", tool_api_call)
    monkeypatch.setattr(infra, "print_json", print_json)

    infra.handle_projects(["--computer", "remote"])

    tool_api_call.assert_called_once_with("GET", "/projects", params={"computer": "remote"})


def test_handle_agents_routes_availability(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[list[str]] = []

    monkeypatch.setattr(infra, "handle_agents_availability", lambda args: received.append(args))

    infra.handle_agents(["availability"])

    assert received == [[]]


def test_handle_channels_publish_posts_decoded_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    tool_api_call = MagicMock(return_value={"ok": True})
    print_json = MagicMock()

    monkeypatch.setattr(infra, "tool_api_call", tool_api_call)
    monkeypatch.setattr(infra, "print_json", print_json)

    infra.handle_channels_publish(["channel:demo:events", "--data", '{"type":"update"}'])

    tool_api_call.assert_called_once_with(
        "POST",
        "/api/channels/channel:demo:events/publish",
        json_body={"payload": {"type": "update"}},
    )


def test_handle_channels_publish_rejects_invalid_json(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        infra.handle_channels_publish(["channel:demo:events", "--data", "{bad"])

    assert exc_info.value.code == 1
    assert "invalid JSON" in capsys.readouterr().err
