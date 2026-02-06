"""Unit tests for threaded-output feature-flag helpers."""

from unittest.mock import patch

from teleclaude.core.feature_flags import is_threaded_output_enabled, is_threaded_output_include_tools_enabled


def test_threaded_output_enabled_is_gemini_only():
    with patch("teleclaude.core.feature_flags.config.is_experiment_enabled", return_value=True):
        assert is_threaded_output_enabled("gemini") is True
        assert is_threaded_output_enabled("Gemini") is True
        assert is_threaded_output_enabled("codex") is False
        assert is_threaded_output_enabled("claude") is False


def test_threaded_output_include_tools_requires_base_experiment():
    def is_enabled(name: str, agent: str | None = None) -> bool:
        if name == "ui_threaded_agent_stop_output":
            return True
        if name == "ui_threaded_agent_stop_output_include_tools":
            return True
        return False

    with patch("teleclaude.core.feature_flags.config.is_experiment_enabled", side_effect=is_enabled):
        assert is_threaded_output_include_tools_enabled("gemini") is True
        assert is_threaded_output_include_tools_enabled("codex") is False
