"""Characterization tests for teleclaude.project_setup.domain_seeds."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import teleclaude.project_setup.domain_seeds as domain_seeds
from teleclaude.events.domain_seeds import DEFAULT_EVENT_DOMAINS


def test_seed_event_domains_populates_empty_domains_and_preserves_existing_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "teleclaude.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "profile": "local",
                "event_domains": {
                    "enabled": False,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(domain_seeds, "_GLOBAL_CONFIG_PATH", config_path)

    domain_seeds.seed_event_domains(tmp_path)

    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert payload["profile"] == "local"
    assert payload["event_domains"]["enabled"] is False
    for key, value in DEFAULT_EVENT_DOMAINS.items():
        assert payload["event_domains"][key] == value


def test_seed_event_domains_skips_when_domains_are_already_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "teleclaude.yml"
    original = yaml.safe_dump(
        {
            "event_domains": {
                "domains": {
                    "custom": {
                        "description": "keep me",
                    }
                }
            }
        },
        sort_keys=False,
    )
    config_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(domain_seeds, "_GLOBAL_CONFIG_PATH", config_path)

    domain_seeds.seed_event_domains(tmp_path)

    assert config_path.read_text(encoding="utf-8") == original
