"""Behavioral tests for daemon `_build_config` parsing and in-place config reload."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

import teleclaude.config as config_module
from tests.unit.config.conftest import BuildConfig

pytestmark = [pytest.mark.unit]

GEMINI_AGENT_KEY = "gemini"

_SUMMARIZER_SECTION = "summarizer"
_ENV_REF_VAR = "TELECLAUDE_RELOAD_TEST_BASE_URL"
_ENV_REF_FIRST = "http://first:1234/v1"
_ENV_REF_SECOND = "http://second:1234/v1"
_RELOAD_ENV_CONFIG = (
    "computer:\n"
    "  name: local-box\n"
    "  user: dev\n"
    "  role: builder\n"
    "  host: localhost\n"
    "  default_working_dir: /workspace/teleclaude\n"
    "agents:\n"
    "  default: claude\n"
    "  claude:\n"
    "    enabled: true\n"
    "  gemini:\n"
    "    enabled: false\n"
    "  codex:\n"
    "    enabled: false\n"
    "summarizer:\n"
    "  provider_priority: [openai]\n"
    "  local:\n"
    "    enabled: true\n"
    "    base_url: ${" + _ENV_REF_VAR + "}\n"
)
_RELOAD_BASE_CONFIG = (
    "computer:\n"
    "  name: local-box\n"
    "  user: dev\n"
    "  role: builder\n"
    "  host: localhost\n"
    "  default_working_dir: /workspace/teleclaude\n"
    "agents:\n"
    "  default: claude\n"
    "  claude:\n"
    "    enabled: true\n"
    "  gemini:\n"
    "    enabled: false\n"
    "  codex:\n"
    "    enabled: false\n"
    "summarizer:\n"
    "  provider_priority: [openai]\n"
)


class TestEmailEnablement:
    def test_defaults_to_disabled(self, build_config: BuildConfig) -> None:
        assert build_config({}).email.enabled is False

    def test_enabled_flag_flows_into_config(self, build_config: BuildConfig) -> None:
        assert build_config({"email": {"enabled": True}}).email.enabled is True


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


class TestReloadConfig:
    def test_restart_required_sections_are_connection_bound(self) -> None:
        assert config_module.RESTART_REQUIRED_SECTIONS == frozenset({"redis", "telegram", "discord", "whatsapp"})

    def _seed_singleton(self, cfg: Path) -> None:
        config_module.config.__dict__.update(config_module._load_config_from_disk(cfg).__dict__)

    def test_reload_applies_hot_change_in_place(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = tmp_path / "config.yml"
        cfg.write_text(_RELOAD_BASE_CONFIG, encoding="utf-8")
        monkeypatch.setattr(config_module, "_config_path", cfg)
        saved = dict(config_module.config.__dict__)
        try:
            with (
                patch.object(config_module, "resolve_tmux_binary", return_value="tmux"),
                patch.object(config_module, "resolve_agent_binary", side_effect=lambda name: f"/usr/bin/{name}"),
            ):
                self._seed_singleton(cfg)
                singleton_id = id(config_module.config)
                cfg.write_text(_RELOAD_BASE_CONFIG.replace("[openai]", "[openai, google]"), encoding="utf-8")
                changed = config_module.reload_config()
            assert _SUMMARIZER_SECTION in changed
            # Identity preserved so existing importers see the update.
            assert id(config_module.config) == singleton_id
            assert config_module.config.summarizer is not None
            assert config_module.config.summarizer.provider_priority == ["openai", "google"]
        finally:
            config_module.config.__dict__.clear()
            config_module.config.__dict__.update(saved)

    def test_reload_with_no_change_reports_nothing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = tmp_path / "config.yml"
        cfg.write_text(_RELOAD_BASE_CONFIG, encoding="utf-8")
        monkeypatch.setattr(config_module, "_config_path", cfg)
        saved = dict(config_module.config.__dict__)
        try:
            with (
                patch.object(config_module, "resolve_tmux_binary", return_value="tmux"),
                patch.object(config_module, "resolve_agent_binary", side_effect=lambda name: f"/usr/bin/{name}"),
            ):
                self._seed_singleton(cfg)
                changed = config_module.reload_config()
            assert changed == []
        finally:
            config_module.config.__dict__.clear()
            config_module.config.__dict__.update(saved)

    def test_reload_reflects_dotenv_edit_in_place(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        env_file = tmp_path / ".env"
        cfg = tmp_path / "config.yml"
        env_file.write_text(f"{_ENV_REF_VAR}={_ENV_REF_FIRST}\n", encoding="utf-8")
        cfg.write_text(_RELOAD_ENV_CONFIG, encoding="utf-8")
        monkeypatch.setattr(config_module, "_dotenv_path", env_file)
        monkeypatch.setattr(config_module, "_config_path", cfg)
        # Isolate the dotenv-managed-key tracker so the temp .env does not evict real keys.
        monkeypatch.setattr(config_module, "_dotenv_managed_keys", set())
        monkeypatch.delenv(_ENV_REF_VAR, raising=False)
        saved = dict(config_module.config.__dict__)
        try:
            with (
                patch.object(config_module, "resolve_tmux_binary", return_value="tmux"),
                patch.object(config_module, "resolve_agent_binary", side_effect=lambda name: f"/usr/bin/{name}"),
            ):
                self._seed_singleton(cfg)
                assert config_module.config.summarizer is not None
                assert config_module.config.summarizer.local.base_url == _ENV_REF_FIRST
                # An out-of-process .env edit (as the TUI does) must be reflected by reload.
                env_file.write_text(f"{_ENV_REF_VAR}={_ENV_REF_SECOND}\n", encoding="utf-8")
                config_module.reload_config()
            assert config_module.config.summarizer is not None
            assert config_module.config.summarizer.local.base_url == _ENV_REF_SECOND
        finally:
            config_module.config.__dict__.clear()
            config_module.config.__dict__.update(saved)
            os.environ.pop(_ENV_REF_VAR, None)

    def test_reload_drops_dotenv_key_removed_from_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        env_file = tmp_path / ".env"
        cfg = tmp_path / "config.yml"
        env_file.write_text(f"{_ENV_REF_VAR}={_ENV_REF_FIRST}\n", encoding="utf-8")
        cfg.write_text(_RELOAD_ENV_CONFIG, encoding="utf-8")
        monkeypatch.setattr(config_module, "_dotenv_path", env_file)
        monkeypatch.setattr(config_module, "_config_path", cfg)
        monkeypatch.setattr(config_module, "_dotenv_managed_keys", set())
        monkeypatch.delenv(_ENV_REF_VAR, raising=False)
        saved = dict(config_module.config.__dict__)
        try:
            with (
                patch.object(config_module, "resolve_tmux_binary", return_value="tmux"),
                patch.object(config_module, "resolve_agent_binary", side_effect=lambda name: f"/usr/bin/{name}"),
            ):
                self._seed_singleton(cfg)
                assert _ENV_REF_VAR in os.environ
                # Removing the key from .env must drop it from os.environ on reload.
                env_file.write_text("", encoding="utf-8")
                config_module.reload_config()
            assert _ENV_REF_VAR not in os.environ
        finally:
            config_module.config.__dict__.clear()
            config_module.config.__dict__.update(saved)
            os.environ.pop(_ENV_REF_VAR, None)
