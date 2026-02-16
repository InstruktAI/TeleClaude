"""Unit tests for threaded-output feature-flag helpers."""

from unittest.mock import patch

from teleclaude.core.feature_flags import (
    is_threaded_output_enabled,
    is_threaded_output_enabled_for_session,
    is_threaded_output_include_tools_enabled,
)
from teleclaude.core.models import Session


def _session(*, origin: str = "telegram", agent: str | None = "gemini") -> Session:
    return Session(
        session_id="test-sess",
        computer_name="local",
        tmux_session_name="tc_test",
        title="Test",
        last_input_origin=origin,
        active_agent=agent,
    )


def test_threaded_output_enabled_respects_experiment_config():
    """Threaded output enabled check defers to experiment config, no hardcoded agent gate."""
    with patch("teleclaude.core.feature_flags.config.is_experiment_enabled", return_value=True):
        assert is_threaded_output_enabled("gemini") is True
        assert is_threaded_output_enabled("Gemini") is True
        assert is_threaded_output_enabled("claude") is True
        assert is_threaded_output_enabled("codex") is True


def test_threaded_output_disabled_when_experiment_off():
    with patch("teleclaude.core.feature_flags.config.is_experiment_enabled", return_value=False):
        assert is_threaded_output_enabled("gemini") is False
        assert is_threaded_output_enabled("claude") is False


def test_session_aware_check_returns_true_for_discord_origin():
    """Any Discord-origin session has threaded output enabled, regardless of agent."""
    session = _session(origin="discord", agent="claude")
    assert is_threaded_output_enabled_for_session(session) is True

    session_no_agent = _session(origin="discord", agent=None)
    assert is_threaded_output_enabled_for_session(session_no_agent) is True


def test_session_aware_check_falls_back_to_experiment_for_non_discord():
    """Non-Discord sessions check the experiment flag."""
    session = _session(origin="telegram", agent="gemini")
    with patch("teleclaude.core.feature_flags.config.is_experiment_enabled", return_value=True):
        assert is_threaded_output_enabled_for_session(session) is True

    with patch("teleclaude.core.feature_flags.config.is_experiment_enabled", return_value=False):
        assert is_threaded_output_enabled_for_session(session) is False


def test_session_aware_check_standard_poller_for_telegram_non_threaded():
    """Telegram non-threaded sessions (experiment off) use standard poller."""
    session = _session(origin="telegram", agent="claude")
    with patch("teleclaude.core.feature_flags.config.is_experiment_enabled", return_value=False):
        assert is_threaded_output_enabled_for_session(session) is False


def test_threaded_output_include_tools_requires_base_experiment():
    def is_enabled(name: str, agent: str | None = None) -> bool:
        _ = agent
        if name == "ui_threaded_agent_stop_output":
            return True
        if name == "ui_threaded_agent_stop_output_include_tools":
            return True
        return False

    with patch("teleclaude.core.feature_flags.config.is_experiment_enabled", side_effect=is_enabled):
        assert is_threaded_output_include_tools_enabled("gemini") is True
        assert is_threaded_output_include_tools_enabled("claude") is True


def test_threaded_output_include_tools_false_when_base_off():
    def is_enabled(name: str, agent: str | None = None) -> bool:
        _ = agent
        if name == "ui_threaded_agent_stop_output":
            return False
        return True

    with patch("teleclaude.core.feature_flags.config.is_experiment_enabled", side_effect=is_enabled):
        assert is_threaded_output_include_tools_enabled("gemini") is False
