"""Unit tests for Telegram menus and keyboards."""

from unittest.mock import MagicMock, patch

import pytest
from telegram import InlineKeyboardMarkup

from teleclaude import config as config_module
from teleclaude.adapters.telegram_adapter import TelegramAdapter
from teleclaude.config import TrustedDir


@pytest.fixture
def mock_full_config():
    """Mock full application configuration."""
    return {
        "computer": {
            "name": "test_computer",
            "default_working_dir": "/teleclaude",
            "trusted_dirs": [
                TrustedDir(name="tmp", desc="temp files", path="/tmp"),
            ],
        },
        "telegram": {"enabled": True, "trusted_bots": ["teleclaude_bot1"]},
    }


@pytest.fixture
def mock_env(monkeypatch):
    """Mock environment variables for Telegram."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABC-DEF")
    monkeypatch.setenv("TELEGRAM_SUPERGROUP_ID", "-100123456789")
    monkeypatch.setenv("TELEGRAM_USER_IDS", "12345,67890")


@pytest.fixture
def mock_adapter_client():
    """Mock AdapterClient."""
    client = MagicMock()
    return client


@pytest.fixture
def telegram_adapter(mock_full_config, mock_env, mock_adapter_client):
    """Create TelegramAdapter instance."""
    with patch.object(config_module, "config") as mock_config:
        mock_config.computer.name = mock_full_config["computer"]["name"]
        mock_config.computer.default_working_dir = mock_full_config["computer"]["default_working_dir"]
        mock_config.computer.trusted_dirs = mock_full_config["computer"]["trusted_dirs"]
        mock_config.computer.get_all_trusted_dirs.return_value = mock_full_config["computer"]["trusted_dirs"]
        mock_config.telegram.enabled = mock_full_config["telegram"]["enabled"]
        return TelegramAdapter(mock_adapter_client)


class TestHeartbeatKeyboard:
    """Tests for heartbeat keyboard generation."""

    def test_build_heartbeat_keyboard_has_all_buttons(self, telegram_adapter):
        """Test that heartbeat keyboard contains buttons for all AI models."""
        bot_username = "test_bot"
        markup = telegram_adapter._build_heartbeat_keyboard(bot_username)

        assert isinstance(markup, InlineKeyboardMarkup)
        keyboard = markup.inline_keyboard

        # Verify 4 rows
        assert len(keyboard) == 4

        # Row 1: Tmux Session
        assert len(keyboard[0]) == 1
        assert "Tmux Session" in keyboard[0][0].text
        assert keyboard[0][0].callback_data == f"ssel:{bot_username}"

        # Row 2: Claude
        assert len(keyboard[1]) == 2
        assert "New Claude" in keyboard[1][0].text
        assert keyboard[1][0].callback_data == f"csel:{bot_username}"
        assert "Resume Claude" in keyboard[1][1].text
        assert keyboard[1][1].callback_data == f"crsel:{bot_username}"

        # Row 3: Gemini
        assert len(keyboard[2]) == 2
        assert "New Gemini" in keyboard[2][0].text
        assert keyboard[2][0].callback_data == f"gsel:{bot_username}"
        assert "Resume Gemini" in keyboard[2][1].text
        assert keyboard[2][1].callback_data == f"grsel:{bot_username}"

        # Row 4: Codex
        assert len(keyboard[3]) == 2
        assert "New Codex" in keyboard[3][0].text
        assert keyboard[3][0].callback_data == f"cxsel:{bot_username}"
        assert "Resume Codex" in keyboard[3][1].text
        assert keyboard[3][1].callback_data == f"cxrsel:{bot_username}"


class TestProjectKeyboard:
    """Tests for project selection keyboard generation."""

    def test_build_project_keyboard_uses_prefix(self, telegram_adapter):
        """Project keyboard should use the provided prefix in callback_data."""
        markup = telegram_adapter._build_project_keyboard("s")

        assert isinstance(markup, InlineKeyboardMarkup)
        keyboard = markup.inline_keyboard

        # Ensure callback_data uses prefix with sequential indices
        for idx, row in enumerate(keyboard):
            assert row[0].callback_data == f"s:{idx}"
