"""Tests for restore-remote-computers config surfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, cast
from unittest.mock import patch

import pytest

import teleclaude.config as config_module
from teleclaude.cli.config_handlers import _ADAPTER_ENV_VARS
from teleclaude.cli.tui.config_components.guidance import GuidanceRegistry
from teleclaude.config import Config

pytestmark = [
    pytest.mark.unit,
]

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SAMPLE_CONFIG = _REPO_ROOT / "config.sample.yml"
_CONFIG_SPEC = _REPO_ROOT / "docs" / "project" / "spec" / "teleclaude-config.md"


class _RemoteComputerLike(Protocol):
    name: str
    user: str | None
    host: str | None
    bot_username: str | None


def _remote_computers_from_config(built_config: object) -> list[_RemoteComputerLike]:
    return cast(list[_RemoteComputerLike], object.__getattribute__(built_config, "remote_computers"))


def _bot_username_from_computer(computer_config: object) -> str | None:
    return cast(str | None, object.__getattribute__(computer_config, "bot_username"))


def _build_test_config(overrides: dict[str, object]) -> Config:  # guard: loose-dict - YAML-style test input
    raw = config_module._deep_merge(
        config_module.DEFAULT_CONFIG,
        {
            "computer": {
                "name": "local-box",
                "user": "dev",
                "role": "builder",
                "host": "localhost",
                "default_working_dir": "/workspace/teleclaude",
            },
            "agents": {
                "default": "claude",
                "claude": {"enabled": True},
                "gemini": {"enabled": False},
                "codex": {"enabled": False},
            },
        },
    )
    raw = config_module._deep_merge(raw, overrides)

    with (
        patch.object(config_module, "resolve_tmux_binary", return_value="tmux"),
        patch.object(config_module, "resolve_agent_binary", side_effect=lambda name: f"/usr/bin/{name}"),
    ):
        return config_module._build_config(raw)


class TestRemoteComputerParsing:
    def test_build_config_parses_remote_computers_into_structured_entries(self) -> None:
        built = _build_test_config(
            {
                "remote_computers": {
                    "builder-box": {
                        "user": "alice",
                        "host": "builder.local",
                        "ip": "10.0.0.8",
                        "teleclaude_path": "/srv/teleclaude",
                        "bot_username": "builder_box_bot",
                    },
                    "relay-box": {
                        "host": "relay.local",
                    },
                }
            }
        )

        remote_computers = _remote_computers_from_config(built)
        assert [remote.name for remote in remote_computers] == ["builder-box", "relay-box"]
        assert remote_computers[0].user == "alice"
        assert remote_computers[0].bot_username == "builder_box_bot"
        assert remote_computers[1].host == "relay.local"
        assert remote_computers[1].bot_username is None

    def test_build_config_defaults_remote_computers_to_empty_list_when_section_missing(self) -> None:
        built = _build_test_config({})
        assert _remote_computers_from_config(built) == []

    def test_build_config_defaults_remote_computers_to_empty_list_when_section_empty(self) -> None:
        built = _build_test_config({"remote_computers": {}})
        assert _remote_computers_from_config(built) == []

    def test_build_config_rejects_non_mapping_remote_entries_with_descriptive_error(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            _build_test_config({"remote_computers": {"builder-box": "alice@builder.local"}})

        message = str(exc_info.value)
        assert "remote_computers" in message
        assert "builder-box" in message


class TestLocalBotUsername:
    def test_build_config_preserves_local_computer_bot_username(self) -> None:
        built = _build_test_config({"computer": {"bot_username": "local_box_bot"}})
        assert _bot_username_from_computer(built.computer) == "local_box_bot"

    def test_build_config_defaults_local_computer_bot_username_to_none(self) -> None:
        built = _build_test_config({})
        assert _bot_username_from_computer(built.computer) is None


class TestTrustedBotDerivation:
    def test_build_config_derives_trusted_bots_from_local_and_remote_fleet_bot_usernames(self) -> None:
        built = _build_test_config(
            {
                "computer": {"bot_username": "local_box_bot"},
                "remote_computers": {
                    "builder-box": {"bot_username": "builder_box_bot"},
                },
            }
        )

        assert set(built.telegram.trusted_bots) == {"local_box_bot", "builder_box_bot"}

    def test_build_config_derives_trusted_bots_from_explicit_telegram_entries_when_no_fleet_bots(self) -> None:
        built = _build_test_config(
            {
                "telegram": {"trusted_bots": ["manual_bot", "relay_bot"]},
            }
        )

        assert set(built.telegram.trusted_bots) == {"manual_bot", "relay_bot"}

    def test_build_config_deduplicates_fleet_and_explicit_trusted_bots(self) -> None:
        built = _build_test_config(
            {
                "computer": {"bot_username": "local_box_bot"},
                "remote_computers": {
                    "builder-box": {"bot_username": "builder_box_bot"},
                    "relay-box": {"bot_username": "builder_box_bot"},
                    "silent-box": {"bot_username": ""},
                },
                "telegram": {"trusted_bots": ["manual_bot", "builder_box_bot"]},
            }
        )

        expected = {"local_box_bot", "builder_box_bot", "manual_bot"}
        assert set(built.telegram.trusted_bots) == expected
        assert len(built.telegram.trusted_bots) == len(expected)

    def test_build_config_produces_empty_trusted_bots_when_all_bot_usernames_are_none(self) -> None:
        built = _build_test_config(
            {
                "computer": {"bot_username": None},
                "remote_computers": {
                    "builder-box": {"bot_username": None},
                },
                "telegram": {"trusted_bots": []},
            }
        )

        assert built.telegram.trusted_bots == []


class TestConfigSurfaceDocumentation:
    def test_sample_config_documents_remote_computers_and_trusted_bot_merge(self) -> None:
        content = _SAMPLE_CONFIG.read_text(encoding="utf-8")
        telegram_section = content.split("telegram:", maxsplit=1)[1]

        assert "remote_computers:" in content
        assert "bot_username:" in content
        assert "trusted_bots:" in telegram_section

    def test_teleclaude_config_spec_documents_remote_computers_and_bot_username(self) -> None:
        content = _CONFIG_SPEC.read_text(encoding="utf-8")

        assert "remote_computers" in content
        assert "bot_username" in content
        assert "trusted_bots" in content

    def test_config_surface_sync_confirms_no_new_env_or_guidance_entries_are_required(self) -> None:
        env_names = {info.name for env_vars in _ADAPTER_ENV_VARS.values() for info in env_vars}
        guidance = GuidanceRegistry()

        assert "BOT_USERNAME" not in " ".join(sorted(env_names))
        assert "REMOTE_COMPUTERS" not in " ".join(sorted(env_names))
        assert guidance.get("computer.bot_username") is None
        assert guidance.get("remote_computers") is None


class TestEventReliabilityConfig:
    def test_default_config_exposes_event_reliability_controls(self) -> None:
        raw = config_module.DEFAULT_CONFIG["event_reliability"]

        assert isinstance(raw, dict)
        assert raw["idle_threshold_ms"] == 30_000
        assert raw["max_attempts"] == 3
        assert raw["sweep_interval_ms"] == 5_000
        assert raw["dlq_destination"] == "teleclaude:events:dlq"

    def test_build_config_parses_event_reliability_overrides(self) -> None:
        built = _build_test_config(
            {
                "event_reliability": {
                    "idle_threshold_ms": 12_000,
                    "max_attempts": 7,
                    "sweep_interval_ms": 900,
                    "dlq_destination": "custom:dlq",
                }
            }
        )

        assert built.event_reliability.idle_threshold_ms == 12_000
        assert built.event_reliability.max_attempts == 7
        assert built.event_reliability.sweep_interval_ms == 900
        assert built.event_reliability.dlq_destination == "custom:dlq"

    def test_teleclaude_config_spec_documents_event_reliability_keys(self) -> None:
        content = _CONFIG_SPEC.read_text(encoding="utf-8")

        assert "event_reliability:" in content
        assert "idle_threshold_ms:" in content
        assert "max_attempts:" in content
        assert "sweep_interval_ms:" in content
        assert "dlq_destination:" in content
