"""Unit tests for identity resolution."""

from pathlib import Path
from unittest.mock import patch

from teleclaude.config.schema import CredsConfig, GlobalConfig, PersonConfig, PersonEntry, TelegramCreds
from teleclaude.core.identity import IdentityResolver


def _make_global_config(people: list[PersonEntry]) -> GlobalConfig:
    return GlobalConfig(
        database={"path": ":memory:"},
        computer={
            "name": "test",
            "user": "test",
            "role": "test",
            "timezone": "UTC",
            "default_working_dir": "/tmp",
            "is_master": False,
            "trusted_dirs": [],
        },
        redis={
            "enabled": False,
            "url": "redis://localhost:6379/0",
            "password": None,
            "max_connections": 10,
            "socket_timeout": 5,
            "message_stream_maxlen": 1000,
            "output_stream_maxlen": 1000,
            "output_stream_ttl": 3600,
        },
        telegram={"trusted_bots": []},
        ui={"animations_enabled": False, "animations_periodic_interval": 60, "animations_subset": []},
        people=people,
    )


@patch("teleclaude.core.identity.Path.glob")
@patch("teleclaude.core.identity.load_person_config")
@patch("teleclaude.core.identity.load_global_config")
def test_resolve_known_telegram_user(
    mock_load_global_config,
    mock_load_person_config,
    mock_glob,
) -> None:
    """Maps Telegram user_id from per-person config to known identity."""
    person = PersonEntry(name="alice", email="alice@example.com", role="admin")
    mock_load_global_config.return_value = _make_global_config([person])
    mock_glob.return_value = [Path("/tmp/.teleclaude/people/alice/teleclaude.yml")]
    mock_load_person_config.return_value = PersonConfig(
        creds=CredsConfig(telegram=TelegramCreds(user_name="alice", user_id=12345))
    )

    resolver = IdentityResolver()
    ctx = resolver.resolve("telegram", {"user_id": "12345"})

    assert ctx is not None
    assert ctx.person_name == "alice"
    assert ctx.person_email == "alice@example.com"
    assert ctx.person_role == "admin"
    assert ctx.platform == "telegram"
    assert ctx.platform_user_id == "12345"


@patch("teleclaude.core.identity.Path.glob")
@patch("teleclaude.core.identity.load_global_config")
def test_resolve_known_web_email(mock_load_global_config, mock_glob) -> None:
    """Maps web email to known person."""
    person = PersonEntry(name="bob", email="bob@example.com", role="member")
    mock_load_global_config.return_value = _make_global_config([person])
    mock_glob.return_value = []

    resolver = IdentityResolver()
    ctx = resolver.resolve("web", {"email": "bob@example.com"})

    assert ctx is not None
    assert ctx.person_name == "bob"
    assert ctx.person_role == "member"
    assert ctx.platform == "web"
    assert ctx.platform_user_id == "bob@example.com"


@patch("teleclaude.core.identity.Path.glob")
@patch("teleclaude.core.identity.load_global_config")
def test_unknown_signals_return_none(mock_load_global_config, mock_glob) -> None:
    """Unknown metadata remains unauthorized."""
    mock_load_global_config.return_value = _make_global_config([])
    mock_glob.return_value = []

    resolver = IdentityResolver()

    assert resolver.resolve("telegram", {"user_id": "99999"}) is None
    assert resolver.resolve("web", {"email": "unknown@example.com"}) is None
    assert resolver.resolve("mcp", {}) is None


@patch("teleclaude.core.identity.Path.glob")
@patch("teleclaude.core.identity.load_global_config")
def test_tui_origin_requires_boundary_identity(mock_load_global_config, mock_glob) -> None:
    """TUI-local trust must be injected at boundary metadata, not inferred in resolver."""
    mock_load_global_config.return_value = _make_global_config([])
    mock_glob.return_value = []

    resolver = IdentityResolver()
    ctx = resolver.resolve("tui", {})

    assert ctx is None
