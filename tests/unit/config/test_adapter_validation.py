"""Tests for teleclaude.config.adapter_validation."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from teleclaude.config.adapter_validation import is_unresolved_placeholder, validate_adapter_config


@pytest.mark.unit
class TestIsUnresolvedPlaceholder:
    def test_none_is_unresolved(self) -> None:
        assert is_unresolved_placeholder(None) is True

    def test_empty_string_is_unresolved(self) -> None:
        assert is_unresolved_placeholder("   ") is True

    def test_unresolved_placeholder_reference(self) -> None:
        assert is_unresolved_placeholder("${WHATSAPP_PHONE_NUMBER_ID}") is True

    def test_real_value_is_resolved(self) -> None:
        assert is_unresolved_placeholder("real-token") is False


@pytest.mark.unit
class TestValidateAdapterConfig:
    def test_whatsapp_missing_both_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)
        monkeypatch.delenv("WHATSAPP_ACCESS_TOKEN", raising=False)
        cfg = SimpleNamespace(phone_number_id="${WHATSAPP_PHONE_NUMBER_ID}", access_token=None)
        assert validate_adapter_config("whatsapp", cfg) == ["phone_number_id", "access_token"]

    def test_whatsapp_satisfied_by_config_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)
        monkeypatch.delenv("WHATSAPP_ACCESS_TOKEN", raising=False)
        cfg = SimpleNamespace(phone_number_id="123", access_token="tok")
        assert validate_adapter_config("whatsapp", cfg) == []

    def test_whatsapp_satisfied_by_env_when_config_is_placeholder(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123")
        monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "tok")
        cfg = SimpleNamespace(phone_number_id="${WHATSAPP_PHONE_NUMBER_ID}", access_token="${WHATSAPP_ACCESS_TOKEN}")
        assert validate_adapter_config("whatsapp", cfg) == []

    def test_discord_token_from_config_or_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        assert validate_adapter_config("discord", SimpleNamespace(token=None)) == ["token"]
        assert validate_adapter_config("discord", SimpleNamespace(token="t")) == []
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "env-token")
        assert validate_adapter_config("discord", SimpleNamespace(token=None)) == []

    def test_telegram_token_is_env_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        assert validate_adapter_config("telegram", SimpleNamespace()) == ["bot token"]
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-token")
        assert validate_adapter_config("telegram", SimpleNamespace()) == []

    def test_unknown_adapter_has_no_requirements(self) -> None:
        assert validate_adapter_config("nonexistent", SimpleNamespace()) == []
