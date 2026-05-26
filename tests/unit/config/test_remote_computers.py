"""Tests for restore-remote-computers config surfaces."""

from __future__ import annotations

from typing import Protocol, cast

import pytest

import teleclaude.config as config_module
from tests.unit.config.conftest import BuildConfig

pytestmark = [
    pytest.mark.unit,
]


class _RemoteComputerLike(Protocol):
    name: str
    user: str | None
    host: str | None


def _remote_computers_from_config(built_config: object) -> list[_RemoteComputerLike]:
    return cast(list[_RemoteComputerLike], object.__getattribute__(built_config, "remote_computers"))


class TestRemoteComputerParsing:
    def test_build_config_parses_remote_computers_into_structured_entries(self, build_config: BuildConfig) -> None:
        built = build_config(
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

    def test_build_config_defaults_remote_computers_to_empty_list_when_section_missing(
        self, build_config: BuildConfig
    ) -> None:
        built = build_config({})
        assert _remote_computers_from_config(built) == []

    def test_build_config_defaults_remote_computers_to_empty_list_when_section_empty(
        self, build_config: BuildConfig
    ) -> None:
        built = build_config({"remote_computers": {}})
        assert _remote_computers_from_config(built) == []

    def test_build_config_rejects_non_mapping_remote_entries_with_descriptive_error(
        self, build_config: BuildConfig
    ) -> None:
        with pytest.raises(ValueError) as exc_info:
            build_config({"remote_computers": {"builder-box": "alice@builder.local"}})

        message = str(exc_info.value)
        assert "remote_computers" in message
        assert "builder-box" in message


class TestEventReliabilityConfig:
    def test_default_config_does_not_expose_event_reliability_controls(self) -> None:
        assert "event_reliability" not in config_module.DEFAULT_CONFIG

    def test_build_config_ignores_event_reliability_overrides(self, build_config: BuildConfig) -> None:
        built = build_config(
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
