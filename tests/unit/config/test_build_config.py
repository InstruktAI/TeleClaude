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


class TestSummarizerParsing:
    def test_unknown_provider_priority_is_rejected(self, build_config: BuildConfig) -> None:
        with pytest.raises(ValueError):
            build_config({"summarizer": {"provider_priority": ["bogus"]}})

    def test_known_providers_are_accepted(self, build_config: BuildConfig) -> None:
        built = build_config({"summarizer": {"provider_priority": ["google", "openai"]}})
        assert built.summarizer is not None
        assert built.summarizer.provider_priority == ["google", "openai"]


class TestTelegramEnablement:
    def test_enabled_flag_flows_into_config(self, build_config: BuildConfig) -> None:
        built = build_config({"telegram": {"enabled": True}})
        assert built.telegram.enabled is True

    def test_defaults_to_disabled_when_absent(self, build_config: BuildConfig) -> None:
        built = build_config({})
        assert built.telegram.enabled is False


class TestWhatsAppEnablement:
    def test_enabled_flag_is_authoritative_even_with_credentials(self, build_config: BuildConfig) -> None:
        # enabled:false must stay disabled even when credentials are present —
        # presence of (placeholder) creds must never force-enable the adapter.
        built = build_config(
            {
                "whatsapp": {
                    "enabled": False,
                    "phone_number_id": "${WHATSAPP_PHONE_NUMBER_ID}",
                    "access_token": "${WHATSAPP_ACCESS_TOKEN}",
                }
            }
        )
        assert built.whatsapp is not None
        assert built.whatsapp.enabled is False

    def test_enabled_flag_flows_into_config(self, build_config: BuildConfig) -> None:
        built = build_config({"whatsapp": {"enabled": True}})
        assert built.whatsapp is not None
        assert built.whatsapp.enabled is True
