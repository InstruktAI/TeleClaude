"""Unit tests for Telegram menus and keyboards."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import InlineKeyboardMarkup

from teleclaude import config as config_module
from teleclaude.adapters.telegram.callback_handlers import (
    LEGACY_ACTION_MAP,
    CallbackAction,
)
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


class TestCallbackActionEnum:
    """Tests for the refactored CallbackAction enum."""

    def test_generic_actions_exist(self):
        """New generic action types must be present."""
        assert hasattr(CallbackAction, "AGENT_SELECT")
        assert hasattr(CallbackAction, "AGENT_RESUME_SELECT")
        assert hasattr(CallbackAction, "AGENT_START")
        assert hasattr(CallbackAction, "AGENT_RESUME_START")

    def test_generic_action_values(self):
        """Generic action values must match canonical format."""
        assert CallbackAction.AGENT_SELECT.value == "asel"
        assert CallbackAction.AGENT_RESUME_SELECT.value == "arsel"
        assert CallbackAction.AGENT_START.value == "as"
        assert CallbackAction.AGENT_RESUME_START.value == "ars"

    def test_per_agent_actions_removed(self):
        """Old per-agent enum members must no longer exist."""
        assert not hasattr(CallbackAction, "CLAUDE_SELECT")
        assert not hasattr(CallbackAction, "CLAUDE_RESUME_SELECT")
        assert not hasattr(CallbackAction, "GEMINI_SELECT")
        assert not hasattr(CallbackAction, "GEMINI_RESUME_SELECT")
        assert not hasattr(CallbackAction, "CODEX_SELECT")
        assert not hasattr(CallbackAction, "CODEX_RESUME_SELECT")
        assert not hasattr(CallbackAction, "CLAUDE_START")
        assert not hasattr(CallbackAction, "CLAUDE_RESUME_START")
        assert not hasattr(CallbackAction, "GEMINI_START")
        assert not hasattr(CallbackAction, "GEMINI_RESUME_START")
        assert not hasattr(CallbackAction, "CODEX_START")
        assert not hasattr(CallbackAction, "CODEX_RESUME_START")

    def test_unchanged_actions_present(self):
        """Non-agent actions must remain unchanged."""
        assert CallbackAction.DOWNLOAD_FULL.value == "download_full"
        assert CallbackAction.SESSION_SELECT.value == "ssel"
        assert CallbackAction.SESSION_START.value == "s"
        assert CallbackAction.CANCEL.value == "ccancel"


class TestLegacyActionMap:
    """Tests for LEGACY_ACTION_MAP backward-compatibility entries."""

    def test_claude_select_legacy(self):
        assert LEGACY_ACTION_MAP["csel"] == ("asel", "claude")

    def test_claude_resume_select_legacy(self):
        assert LEGACY_ACTION_MAP["crsel"] == ("arsel", "claude")

    def test_gemini_select_legacy(self):
        assert LEGACY_ACTION_MAP["gsel"] == ("asel", "gemini")

    def test_gemini_resume_select_legacy(self):
        assert LEGACY_ACTION_MAP["grsel"] == ("arsel", "gemini")

    def test_codex_select_legacy(self):
        assert LEGACY_ACTION_MAP["cxsel"] == ("asel", "codex")

    def test_codex_resume_select_legacy(self):
        assert LEGACY_ACTION_MAP["cxrsel"] == ("arsel", "codex")

    def test_claude_start_legacy(self):
        assert LEGACY_ACTION_MAP["c"] == ("as", "claude")

    def test_claude_resume_start_legacy(self):
        assert LEGACY_ACTION_MAP["cr"] == ("ars", "claude")

    def test_gemini_start_legacy(self):
        assert LEGACY_ACTION_MAP["g"] == ("as", "gemini")

    def test_gemini_resume_start_legacy(self):
        assert LEGACY_ACTION_MAP["gr"] == ("ars", "gemini")

    def test_codex_start_legacy(self):
        assert LEGACY_ACTION_MAP["cx"] == ("as", "codex")

    def test_codex_resume_start_legacy(self):
        assert LEGACY_ACTION_MAP["cxr"] == ("ars", "codex")

    def test_all_twelve_legacy_entries_present(self):
        """All 12 legacy entries (6 select + 6 start) must be mapped."""
        assert len(LEGACY_ACTION_MAP) == 12


class TestHeartbeatKeyboard:
    """Tests for heartbeat keyboard generation."""

    def test_build_heartbeat_keyboard_all_agents_enabled(self, telegram_adapter):
        """Keyboard has one row per enabled agent plus the Tmux Session row."""
        bot_username = "test_bot"
        with patch("teleclaude.core.agents.get_enabled_agents", return_value=("claude", "gemini", "codex")):
            markup = telegram_adapter._build_heartbeat_keyboard(bot_username)

        assert isinstance(markup, InlineKeyboardMarkup)
        keyboard = markup.inline_keyboard

        # Row 0: Tmux Session
        assert len(keyboard) == 4
        assert "Tmux Session" in keyboard[0][0].text
        assert keyboard[0][0].callback_data == f"ssel:{bot_username}"

        # Row 1: Claude
        assert len(keyboard[1]) == 2
        assert "New Claude" in keyboard[1][0].text
        assert keyboard[1][0].callback_data == f"asel:claude:{bot_username}"
        assert "Resume Claude" in keyboard[1][1].text
        assert keyboard[1][1].callback_data == f"arsel:claude:{bot_username}"

        # Row 2: Gemini
        assert len(keyboard[2]) == 2
        assert "New Gemini" in keyboard[2][0].text
        assert keyboard[2][0].callback_data == f"asel:gemini:{bot_username}"
        assert "Resume Gemini" in keyboard[2][1].text
        assert keyboard[2][1].callback_data == f"arsel:gemini:{bot_username}"

        # Row 3: Codex
        assert len(keyboard[3]) == 2
        assert "New Codex" in keyboard[3][0].text
        assert keyboard[3][0].callback_data == f"asel:codex:{bot_username}"
        assert "Resume Codex" in keyboard[3][1].text
        assert keyboard[3][1].callback_data == f"arsel:codex:{bot_username}"

    def test_build_heartbeat_keyboard_subset_of_agents(self, telegram_adapter):
        """When only some agents are enabled, only those rows appear."""
        bot_username = "test_bot"
        with patch("teleclaude.core.agents.get_enabled_agents", return_value=("claude",)):
            markup = telegram_adapter._build_heartbeat_keyboard(bot_username)

        keyboard = markup.inline_keyboard
        # Only Tmux Session row + 1 agent row
        assert len(keyboard) == 2
        assert "Tmux Session" in keyboard[0][0].text
        assert "New Claude" in keyboard[1][0].text

    def test_build_heartbeat_keyboard_no_agents_enabled(self, telegram_adapter):
        """When no agents are enabled, only the Tmux Session row appears."""
        bot_username = "test_bot"
        with patch("teleclaude.core.agents.get_enabled_agents", return_value=()):
            markup = telegram_adapter._build_heartbeat_keyboard(bot_username)

        keyboard = markup.inline_keyboard
        assert len(keyboard) == 1
        assert "Tmux Session" in keyboard[0][0].text

    def test_build_heartbeat_keyboard_new_callback_format(self, telegram_adapter):
        """Agent buttons use the new asel/arsel format, not legacy csel/crsel."""
        bot_username = "test_bot"
        with patch("teleclaude.core.agents.get_enabled_agents", return_value=("claude",)):
            markup = telegram_adapter._build_heartbeat_keyboard(bot_username)

        keyboard = markup.inline_keyboard
        new_btn = keyboard[1][0].callback_data
        resume_btn = keyboard[1][1].callback_data
        assert new_btn == f"asel:claude:{bot_username}"
        assert resume_btn == f"arsel:claude:{bot_username}"
        # Confirm old format is gone
        assert "csel" not in new_btn
        assert "crsel" not in resume_btn


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

    def test_build_project_keyboard_new_agent_prefix(self, telegram_adapter):
        """Project keyboard uses new agent:name prefix for agent selections."""
        # Ensure at least one trusted dir so the keyboard is non-empty.
        telegram_adapter.trusted_dirs = [TrustedDir(name="proj", desc="test project", path="/tmp")]

        markup = telegram_adapter._build_project_keyboard("as:claude")

        keyboard = markup.inline_keyboard
        assert len(keyboard) == 1
        assert keyboard[0][0].callback_data == "as:claude:0"


class TestCallbackDispatch:
    """Behavioral tests for _handle_callback_query dispatch and handler routing."""

    @pytest.fixture
    def stub_adapter(self):
        """Minimal stub implementing CallbackHandlersMixin protocol."""
        from teleclaude.adapters.telegram.callback_handlers import CallbackHandlersMixin

        class StubAdapter(CallbackHandlersMixin):
            user_whitelist = {12345}
            trusted_dirs = [TrustedDir(name="tmp", desc="test", path="/tmp")]
            computer_name = "test"
            client = MagicMock()

            @property
            def bot(self):
                return MagicMock()

            def _build_project_keyboard(self, prefix):
                return MagicMock()

            def _build_heartbeat_keyboard(self, bot_username):
                return MagicMock()

            async def _send_document_with_retry(self, **kwargs):
                return MagicMock()

            def _metadata(self, **kwargs):
                return MagicMock(channel_metadata=None)

        return StubAdapter()

    @staticmethod
    def _make_query(data: str, user_id: int = 12345):
        """Create a mock CallbackQuery with given callback data."""
        import telegram

        query = MagicMock(spec=telegram.CallbackQuery)
        query.data = data
        query.answer = AsyncMock()
        query.from_user = MagicMock()
        query.from_user.id = user_id
        query.message = MagicMock()
        return query

    @staticmethod
    def _make_update(query):
        update = MagicMock()
        update.callback_query = query
        return update

    async def test_new_payload_dispatches_to_agent_select(self, stub_adapter):
        """asel:claude:bot dispatches to _handle_agent_select with is_resume=False."""
        stub_adapter._handle_agent_select = AsyncMock()
        query = self._make_query("asel:claude:test_bot")

        await stub_adapter._handle_callback_query(self._make_update(query), MagicMock())

        stub_adapter._handle_agent_select.assert_awaited_once_with(query, "claude", is_resume=False)

    async def test_resume_payload_dispatches_with_is_resume_true(self, stub_adapter):
        """arsel:gemini:bot dispatches to _handle_agent_select with is_resume=True."""
        stub_adapter._handle_agent_select = AsyncMock()
        query = self._make_query("arsel:gemini:test_bot")

        await stub_adapter._handle_callback_query(self._make_update(query), MagicMock())

        stub_adapter._handle_agent_select.assert_awaited_once_with(query, "gemini", is_resume=True)

    async def test_legacy_csel_rewrites_and_dispatches(self, stub_adapter):
        """csel:bot (legacy) rewrites to asel:claude:bot and dispatches correctly."""
        stub_adapter._handle_agent_select = AsyncMock()
        query = self._make_query("csel:test_bot")

        await stub_adapter._handle_callback_query(self._make_update(query), MagicMock())

        stub_adapter._handle_agent_select.assert_awaited_once_with(query, "claude", is_resume=False)

    async def test_unknown_agent_select_warns_and_returns(self, stub_adapter):
        """asel:unknown_agent:bot logs warning and returns without raising."""
        query = self._make_query("asel:unknown_agent:test_bot")

        with patch("teleclaude.adapters.telegram.callback_handlers.logger") as mock_logger:
            await stub_adapter._handle_callback_query(self._make_update(query), MagicMock())

        mock_logger.warning.assert_called_once()
        assert "unknown_agent" in str(mock_logger.warning.call_args)

    async def test_agent_start_auto_command_construction(self, stub_adapter):
        """as:gemini:0 produces auto_command='agent gemini' passed to _metadata."""
        query = self._make_query("as:gemini:0")

        with (
            patch("teleclaude.adapters.telegram.callback_handlers.get_command_service") as mock_svc,
            patch("teleclaude.adapters.telegram.callback_handlers.CommandMapper"),
            patch.object(stub_adapter, "_restore_heartbeat_menu", new_callable=AsyncMock),
            patch.object(stub_adapter, "_metadata") as mock_metadata,
        ):
            mock_svc.return_value.create_session = AsyncMock()
            mock_metadata.return_value = MagicMock(channel_metadata=None)

            await stub_adapter._handle_callback_query(self._make_update(query), MagicMock())

            mock_metadata.assert_called_once_with(project_path="/tmp", auto_command="agent gemini")
