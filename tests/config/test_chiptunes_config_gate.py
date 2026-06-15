from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML

import teleclaude.config as _tc_config_module
from teleclaude.config import reload_config, restart_required_sections

CHIPTUNES_SECTION = "chiptunes"


def _write_config(path: Path, *, chiptunes_enabled: bool | None = None) -> None:
    config: dict[str, object] = {  # guard: loose-dict - YAML fixture structure
        "computer": {
            "name": "TestMac",
            "role": "development",
            "timezone": "Europe/Amsterdam",
            "is_master": True,
        },
        "agents": {
            "default": "claude",
            "claude": {
                "system_prompt": "hello",
            },
        },
    }
    if chiptunes_enabled is not None:
        config["chiptunes"] = {"enabled": chiptunes_enabled}
    YAML().dump(config, path)


def test_chiptunes_gate_defaults_off_and_hot_reloads(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.yml"
    _write_config(config_path)
    monkeypatch.setattr(_tc_config_module, "_config_path", config_path)
    monkeypatch.setattr(_tc_config_module, "config_path", config_path)

    reload_config()

    assert _tc_config_module.config.chiptunes is not None
    assert _tc_config_module.config.chiptunes.enabled is False

    _write_config(config_path, chiptunes_enabled=True)
    changed = reload_config()

    assert changed == [CHIPTUNES_SECTION]
    assert restart_required_sections(changed) == []
    assert _tc_config_module.config.chiptunes.enabled is True
