"""Behavioral tests for daemon `_build_config` agent and adapter parsing."""

from __future__ import annotations

import pytest

from tests.unit.config.conftest import BuildConfig

pytestmark = [pytest.mark.unit]

GEMINI_AGENT_KEY = "gemini"


class TestAgentKeyParsing:
    def test_gemini_is_an_accepted_agent_key(self, build_config: BuildConfig) -> None:
        built = build_config({"agents": {"default": "claude", GEMINI_AGENT_KEY: {"enabled": True}}})
        assert GEMINI_AGENT_KEY in built.agents

    def test_unknown_agent_key_is_rejected(self, build_config: BuildConfig) -> None:
        with pytest.raises(ValueError):
            build_config({"agents": {"default": "claude", "agy": {"enabled": True}}})


class TestTelegramEnablement:
    def test_enabled_flag_flows_into_config(self, build_config: BuildConfig) -> None:
        built = build_config({"telegram": {"enabled": True}})
        assert built.telegram.enabled is True

    def test_defaults_to_disabled_when_absent(self, build_config: BuildConfig) -> None:
        built = build_config({})
        assert built.telegram.enabled is False
