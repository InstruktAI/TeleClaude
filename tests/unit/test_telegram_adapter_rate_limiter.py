"""Tests for Telegram PTB rate-limiter wiring."""

import os
from unittest.mock import MagicMock, patch

import pytest

from teleclaude.adapters.telegram_adapter import TelegramAdapter


@pytest.fixture
def adapter_client() -> MagicMock:
    client = MagicMock()
    client.pre_handle_command = MagicMock()
    client.post_handle_command = MagicMock()
    client.broadcast_command_action = MagicMock()
    return client


@pytest.fixture
def telegram_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_SUPERGROUP_ID", "-100123")
    monkeypatch.setenv("TELEGRAM_USER_IDS", "123")


def test_create_ptb_rate_limiter_success(adapter_client: MagicMock, telegram_env: None) -> None:
    """Adapter should instantiate PTB AIORateLimiter when dependency is available."""
    adapter = TelegramAdapter(adapter_client)

    class FakeLimiter:  # pragma: no cover - simple constructor test double
        def __init__(self) -> None:
            self.kind = "ok"

    with patch("teleclaude.adapters.telegram_adapter._load_ptb_rate_limiter_cls", return_value=FakeLimiter):
        limiter = adapter._create_ptb_rate_limiter()

    assert isinstance(limiter, FakeLimiter)


def test_create_ptb_rate_limiter_missing_dependency_raises_clear_error(
    adapter_client: MagicMock,
    telegram_env: None,
) -> None:
    """Missing PTB rate-limiter extra should fail startup with actionable error."""
    adapter = TelegramAdapter(adapter_client)

    with patch(
        "teleclaude.adapters.telegram_adapter._load_ptb_rate_limiter_cls",
        side_effect=ImportError("missing aiolimiter"),
    ):
        with pytest.raises(RuntimeError, match="python-telegram-bot\\[rate-limiter\\]"):
            adapter._create_ptb_rate_limiter()
