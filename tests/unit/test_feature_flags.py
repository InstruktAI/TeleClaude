"""Unit tests for threaded-output feature-flag helpers."""

from unittest.mock import patch

from teleclaude.config import ExperimentConfig
from teleclaude.core.feature_flags import is_threaded_output_enabled


def _make_experiments(*entries: ExperimentConfig) -> list[ExperimentConfig]:
    return list(entries)


def test_agent_only_entry_matches_agent():
    """Entry with agents=[gemini] matches gemini on any adapter."""
    exps = _make_experiments(ExperimentConfig(name="threaded_output", agents=["gemini"]))
    with patch("teleclaude.core.feature_flags.config") as mock_config:
        mock_config.is_experiment_enabled.side_effect = lambda name, agent, adapter=None: any(
            e.name == name
            and (not e.agents or (agent and agent in e.agents))
            and (not e.adapters or not adapter or adapter in e.adapters)
            for e in exps
        )
        assert is_threaded_output_enabled("gemini") is True
        assert is_threaded_output_enabled("gemini", adapter="discord") is True
        assert is_threaded_output_enabled("gemini", adapter="telegram") is True
        assert is_threaded_output_enabled("claude") is False
        assert is_threaded_output_enabled("claude", adapter="discord") is False


def test_adapter_only_entry_matches_any_agent_on_that_adapter():
    """Entry with adapters=[discord] matches any agent on discord."""
    exps = _make_experiments(ExperimentConfig(name="threaded_output", adapters=["discord"]))
    with patch("teleclaude.core.feature_flags.config") as mock_config:
        mock_config.is_experiment_enabled.side_effect = lambda name, agent, adapter=None: any(
            e.name == name
            and (not e.agents or (agent and agent in e.agents))
            and (not e.adapters or not adapter or adapter in e.adapters)
            for e in exps
        )
        assert is_threaded_output_enabled("claude", adapter="discord") is True
        assert is_threaded_output_enabled("codex", adapter="discord") is True
        assert is_threaded_output_enabled("claude", adapter="telegram") is False


def test_optimistic_match_when_adapter_omitted():
    """Coordinator check (no adapter) matches adapter-only entries optimistically."""
    exps = _make_experiments(ExperimentConfig(name="threaded_output", adapters=["discord"]))
    with patch("teleclaude.core.feature_flags.config") as mock_config:
        mock_config.is_experiment_enabled.side_effect = lambda name, agent, adapter=None: any(
            e.name == name
            and (not e.agents or (agent and agent in e.agents))
            and (not e.adapters or not adapter or adapter in e.adapters)
            for e in exps
        )
        # No adapter specified → optimistic match
        assert is_threaded_output_enabled("claude") is True
        assert is_threaded_output_enabled("gemini") is True


def test_multi_entry_or_semantics():
    """Multiple entries for same experiment are OR'd together."""
    exps = _make_experiments(
        ExperimentConfig(name="threaded_output", agents=["gemini"]),
        ExperimentConfig(name="threaded_output", adapters=["discord"]),
    )
    with patch("teleclaude.core.feature_flags.config") as mock_config:
        mock_config.is_experiment_enabled.side_effect = lambda name, agent, adapter=None: any(
            e.name == name
            and (not e.agents or (agent and agent in e.agents))
            and (not e.adapters or not adapter or adapter in e.adapters)
            for e in exps
        )
        # Gemini on any adapter
        assert is_threaded_output_enabled("gemini", adapter="telegram") is True
        assert is_threaded_output_enabled("gemini", adapter="discord") is True
        # Claude on discord (adapter entry)
        assert is_threaded_output_enabled("claude", adapter="discord") is True
        # Claude on telegram → no matching entry
        assert is_threaded_output_enabled("claude", adapter="telegram") is False


def test_claude_telegram_returns_false():
    """Claude+Telegram has no matching entry in the target config."""
    exps = _make_experiments(
        ExperimentConfig(name="threaded_output", agents=["gemini"]),
        ExperimentConfig(name="threaded_output", adapters=["discord"]),
    )
    with patch("teleclaude.core.feature_flags.config") as mock_config:
        mock_config.is_experiment_enabled.side_effect = lambda name, agent, adapter=None: any(
            e.name == name
            and (not e.agents or (agent and agent in e.agents))
            and (not e.adapters or not adapter or adapter in e.adapters)
            for e in exps
        )
        assert is_threaded_output_enabled("claude", adapter="telegram") is False


def test_normalizes_agent_key():
    """Agent key is normalized (lowered, stripped)."""
    with patch("teleclaude.core.feature_flags.config.is_experiment_enabled", return_value=True):
        assert is_threaded_output_enabled("Gemini") is True
        assert is_threaded_output_enabled("  CLAUDE  ") is True


def test_none_agent_key():
    """None or empty agent key returns False when entries require agents."""
    with patch("teleclaude.core.feature_flags.config.is_experiment_enabled", return_value=False):
        assert is_threaded_output_enabled(None) is False
        assert is_threaded_output_enabled("") is False
