"""Tests for teleclaude.config.validation."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from teleclaude.config.validation import (
    is_section_available,
    is_unresolved_placeholder,
    missing_required_fields,
)


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
        assert missing_required_fields("whatsapp", cfg) == ["phone_number_id", "access_token"]

    def test_whatsapp_satisfied_by_config_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)
        monkeypatch.delenv("WHATSAPP_ACCESS_TOKEN", raising=False)
        cfg = SimpleNamespace(phone_number_id="123", access_token="tok")
        assert missing_required_fields("whatsapp", cfg) == []

    def test_whatsapp_satisfied_by_env_when_config_is_placeholder(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123")
        monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "tok")
        cfg = SimpleNamespace(phone_number_id="${WHATSAPP_PHONE_NUMBER_ID}", access_token="${WHATSAPP_ACCESS_TOKEN}")
        assert missing_required_fields("whatsapp", cfg) == []

    def test_discord_token_from_config_or_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        assert missing_required_fields("discord", SimpleNamespace(token=None)) == ["token"]
        assert missing_required_fields("discord", SimpleNamespace(token="t")) == []
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "env-token")
        assert missing_required_fields("discord", SimpleNamespace(token=None)) == []

    def test_telegram_token_is_env_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        assert missing_required_fields("telegram", SimpleNamespace()) == ["bot token"]
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-token")
        assert missing_required_fields("telegram", SimpleNamespace()) == []

    def test_unknown_adapter_has_no_requirements(self) -> None:
        assert missing_required_fields("nonexistent", SimpleNamespace()) == []


@pytest.mark.unit
class TestIsSectionAvailable:
    def test_available_when_enabled_and_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SMTP_USERNAME", "u")
        monkeypatch.setenv("SMTP_KEY", "k")
        monkeypatch.setenv("EMAIL_FROM", "a@b.c")
        assert is_section_available("email", SimpleNamespace(enabled=True)) is True

    def test_unavailable_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SMTP_USERNAME", "u")
        monkeypatch.setenv("SMTP_KEY", "k")
        monkeypatch.setenv("EMAIL_FROM", "a@b.c")
        assert is_section_available("email", SimpleNamespace(enabled=False)) is False

    def test_unavailable_when_enabled_but_unconfigured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SMTP_USERNAME", raising=False)
        monkeypatch.delenv("SMTP_KEY", raising=False)
        monkeypatch.delenv("EMAIL_FROM", raising=False)
        assert is_section_available("email", SimpleNamespace(enabled=True)) is False

    def test_unavailable_when_cfg_is_none(self) -> None:
        assert is_section_available("email", None) is False
