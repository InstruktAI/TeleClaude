"""Characterization tests for teleclaude.core.feature_flags."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from teleclaude.core.feature_flags import THREADED_OUTPUT_EXPERIMENT, is_threaded_output_enabled


class TestThreadedOutputExperimentConstant:
    @pytest.mark.unit
    def test_constant_value(self):
        assert THREADED_OUTPUT_EXPERIMENT == "threaded_output"


class TestIsThreadedOutputEnabled:
    @pytest.mark.unit
    def test_returns_bool(self):
        with patch("teleclaude.core.feature_flags.config") as mock_config:
            mock_config.is_experiment_enabled.return_value = False
            result = is_threaded_output_enabled("claude")
        assert result is False

    @pytest.mark.unit
    def test_delegates_to_config(self):
        with patch("teleclaude.core.feature_flags.config") as mock_config:
            mock_config.is_experiment_enabled.return_value = True
            result = is_threaded_output_enabled("claude", adapter="telegram")
        assert result is True
        mock_config.is_experiment_enabled.assert_called_once_with(
            THREADED_OUTPUT_EXPERIMENT, "claude", adapter="telegram"
        )

    @pytest.mark.unit
    def test_none_agent_normalized_to_none(self):
        with patch("teleclaude.core.feature_flags.config") as mock_config:
            mock_config.is_experiment_enabled.return_value = False
            is_threaded_output_enabled(None)
            call_args = mock_config.is_experiment_enabled.call_args
            assert call_args.args[1] is None

    @pytest.mark.unit
    def test_empty_agent_normalized_to_none(self):
        with patch("teleclaude.core.feature_flags.config") as mock_config:
            mock_config.is_experiment_enabled.return_value = False
            is_threaded_output_enabled("")
            call_args = mock_config.is_experiment_enabled.call_args
            assert call_args.args[1] is None
