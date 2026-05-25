"""Tests for restore-remote-computers config surfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, cast
from unittest.mock import patch

import pytest

import teleclaude.config as config_module
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


def _remote_computers_from_config(built_config: object) -> list[_RemoteComputerLike]:
    return cast(list[_RemoteComputerLike], object.__getattribute__(built_config, "remote_computers"))


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
        assert remote_computers[1].host == "relay.local"

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


class TestEventReliabilityConfig:
    def test_default_config_does_not_expose_event_reliability_controls(self) -> None:
        assert "event_reliability" not in config_module.DEFAULT_CONFIG

    def test_build_config_ignores_event_reliability_overrides(self) -> None:
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

        assert built.event_reliability.idle_threshold_ms == 30_000
        assert built.event_reliability.max_attempts == 3
        assert built.event_reliability.sweep_interval_ms == 5_000
        assert built.event_reliability.dlq_destination == "teleclaude:events:dlq"
