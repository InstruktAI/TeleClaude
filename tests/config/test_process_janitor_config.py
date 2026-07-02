from __future__ import annotations

from pathlib import Path

import pytest
from ruamel.yaml import YAML

import teleclaude.config as _tc_config_module
from teleclaude.config import reload_config

pytestmark = pytest.mark.functional


def _write_config(path: Path, *, reap_revalidation_seconds: int | None = None) -> None:
    process_janitor: dict[str, object] = {}  # guard: loose-dict - YAML fixture structure
    if reap_revalidation_seconds is not None:
        process_janitor["reap_revalidation_seconds"] = reap_revalidation_seconds
    config: dict[str, object] = {  # guard: loose-dict - YAML fixture structure
        "computer": {
            "name": "TestMac",
            "role": "development",
            "timezone": "Europe/Amsterdam",
            "is_master": False,
        },
        "agents": {
            "default": "claude",
            "claude": {
                "system_prompt": "hello",
            },
        },
    }
    if process_janitor:
        config["process_janitor"] = process_janitor
    YAML().dump(config, path)


def test_reap_revalidation_seconds_defaults_when_unset(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yml"
    _write_config(config_path)
    monkeypatch.setattr(_tc_config_module, "_config_path", config_path)
    monkeypatch.setattr(_tc_config_module, "config_path", config_path)

    reload_config()

    assert _tc_config_module.config.process_janitor.reap_revalidation_seconds == 3600


def test_reap_revalidation_seconds_loads_explicit_value(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yml"
    _write_config(config_path, reap_revalidation_seconds=120)
    monkeypatch.setattr(_tc_config_module, "_config_path", config_path)
    monkeypatch.setattr(_tc_config_module, "config_path", config_path)

    reload_config()

    assert _tc_config_module.config.process_janitor.reap_revalidation_seconds == 120


def test_reap_revalidation_seconds_below_floor_raises(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yml"
    _write_config(config_path, reap_revalidation_seconds=59)
    monkeypatch.setattr(_tc_config_module, "_config_path", config_path)
    monkeypatch.setattr(_tc_config_module, "config_path", config_path)

    with pytest.raises(ValueError):
        reload_config()
