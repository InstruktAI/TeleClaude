"""Characterization tests for teleclaude/cli/config_cli.py."""

from __future__ import annotations

import json
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.cli.config_cli import (
    PersonInfo,
    _parse_kv_args,
    handle_config_cli,
)

# ---------------------------------------------------------------------------
# PersonInfo dataclass
# ---------------------------------------------------------------------------


def test_person_info_stores_name_and_role() -> None:
    info = PersonInfo(name="Alice", role="admin")
    assert info.name == "Alice"
    assert info.role == "admin"


def test_person_info_optional_fields_default_to_none() -> None:
    info = PersonInfo(name="Bob", role="member")
    assert info.email is None
    assert info.username is None
    assert info.expertise is None
    assert info.telegram is None
    assert info.telegram_id is None


def test_person_info_interests_defaults_to_empty_list() -> None:
    info = PersonInfo(name="Carol", role="member")
    assert info.interests == []


# ---------------------------------------------------------------------------
# _parse_kv_args
# ---------------------------------------------------------------------------


def test_parse_kv_args_extracts_key_value_pairs() -> None:
    args = ["--name", "Alice", "--role", "admin"]
    result = _parse_kv_args(args)
    assert result == {"name": "Alice", "role": "admin"}


def test_parse_kv_args_converts_hyphens_to_underscores() -> None:
    args = ["--telegram-user", "alice_bot"]
    result = _parse_kv_args(args)
    assert result == {"telegram_user": "alice_bot"}


def test_parse_kv_args_ignores_positional_args() -> None:
    args = ["positional", "--key", "value"]
    result = _parse_kv_args(args)
    assert "positional" not in result
    assert result.get("key") == "value"


def test_parse_kv_args_returns_empty_for_no_flags() -> None:
    result = _parse_kv_args(["positional-only"])
    assert result == {}


def test_parse_kv_args_ignores_dangling_flag() -> None:
    # Flag with no following value is skipped
    args = ["--key", "value", "--dangling"]
    result = _parse_kv_args(args)
    assert result.get("key") == "value"
    assert "dangling" not in result


# ---------------------------------------------------------------------------
# handle_config_cli
# ---------------------------------------------------------------------------


def test_handle_config_cli_exits_on_empty_args() -> None:
    with pytest.raises(SystemExit):
        handle_config_cli([])


def test_handle_config_cli_exits_on_unknown_subcommand() -> None:
    with pytest.raises(SystemExit):
        handle_config_cli(["nonexistent"])


def test_handle_config_cli_routes_to_people_handler() -> None:
    with patch("teleclaude.cli.config_cli._handle_people") as mock_people:
        handle_config_cli(["people", "list"])
    mock_people.assert_called_once_with(["list"])


def test_handle_config_cli_routes_to_env_handler() -> None:
    with patch("teleclaude.cli.config_cli._handle_env") as mock_env:
        handle_config_cli(["env", "list"])
    mock_env.assert_called_once_with(["list"])


def test_handle_config_cli_routes_to_validate_handler() -> None:
    with patch("teleclaude.cli.config_cli._handle_validate") as mock_validate:
        handle_config_cli(["validate"])
    mock_validate.assert_called_once_with([])


def test_handle_config_cli_routes_to_notify_handler() -> None:
    with patch("teleclaude.cli.config_cli._handle_notify") as mock_notify:
        handle_config_cli(["notify"])
    mock_notify.assert_called_once_with([])


def test_handle_config_cli_routes_to_invite_handler() -> None:
    with patch("teleclaude.cli.config_cli._handle_invite") as mock_invite:
        handle_config_cli(["invite", "Alice"])
    mock_invite.assert_called_once_with(["Alice"])


# ---------------------------------------------------------------------------
# _handle_invite — email-not-delivered link relay
# ---------------------------------------------------------------------------


def _patch_invite_flow(*, links: dict[str, str | None], email_sent: bool) -> object:
    """Patch the invite dependencies so the handler runs without I/O.

    email_sent=False is driven by send_invite_email raising (email disabled/unconfigured).
    """
    stack = ExitStack()
    stack.enter_context(
        patch(
            "teleclaude.cli.config_cli.list_people",
            return_value=[PersonInfo(name="Alice", role="admin", email="alice@example.com")],
        )
    )
    stack.enter_context(patch("teleclaude.cli.config_cli.set_invite_token", return_value="tok-1"))
    stack.enter_context(
        patch("teleclaude.cli.config_cli.resolve_telegram_bot_username", new=AsyncMock(return_value="bot"))
    )
    stack.enter_context(
        patch("teleclaude.cli.config_cli.resolve_discord_bot_user_id", new=AsyncMock(return_value="42"))
    )
    stack.enter_context(patch("teleclaude.cli.config_cli.generate_invite_links", return_value=links))
    if email_sent:
        stack.enter_context(patch("teleclaude.cli.config_cli.send_invite_email", new=AsyncMock(return_value=None)))
    else:
        stack.enter_context(
            patch(
                "teleclaude.cli.config_cli.send_invite_email", new=AsyncMock(side_effect=RuntimeError("email disabled"))
            )
        )
    return stack


def test_invite_relays_links_when_email_not_delivered(
    capsys: pytest.CaptureFixture[str], snapshot: SnapshotAssertion
) -> None:
    links = {"telegram": "https://t.me/bot?start=tok-1", "discord": None, "whatsapp": None}
    with _patch_invite_flow(links=links, email_sent=False):
        handle_config_cli(["invite", "Alice"])
    assert capsys.readouterr().out == snapshot


def test_invite_reports_no_links_when_email_not_delivered_and_none_generated(
    capsys: pytest.CaptureFixture[str], snapshot: SnapshotAssertion
) -> None:
    links: dict[str, str | None] = {"telegram": None, "discord": None, "whatsapp": None}
    with _patch_invite_flow(links=links, email_sent=False):
        handle_config_cli(["invite", "Alice"])
    assert capsys.readouterr().out == snapshot


def test_invite_json_returns_links_when_email_not_delivered(capsys: pytest.CaptureFixture[str]) -> None:
    links = {"telegram": "https://t.me/bot?start=tok-1", "discord": None, "whatsapp": None}
    with _patch_invite_flow(links=links, email_sent=False):
        handle_config_cli(["invite", "Alice", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["email_sent"] is False
    assert payload["links"]["telegram"] == "https://t.me/bot?start=tok-1"
