from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML

import teleclaude.config as _tc_config_module
from teleclaude.config import reload_config


def _write_config(path: Path, *, is_ingress_node: bool | None = None) -> None:
    computer: dict[str, object] = {  # guard: loose-dict - YAML fixture structure
        "name": "TestMac",
        "role": "development",
        "timezone": "Europe/Amsterdam",
        "is_master": False,
    }
    if is_ingress_node is not None:
        computer["is_ingress_node"] = is_ingress_node
    config: dict[str, object] = {  # guard: loose-dict - YAML fixture structure
        "computer": computer,
        "agents": {
            "default": "claude",
            "claude": {
                "system_prompt": "hello",
            },
        },
    }
    YAML().dump(config, path)


def test_ingress_node_flag_loads_explicit_true_and_defaults_false(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yml"
    _write_config(config_path, is_ingress_node=True)
    monkeypatch.setattr(_tc_config_module, "_config_path", config_path)
    monkeypatch.setattr(_tc_config_module, "config_path", config_path)

    reload_config()

    assert _tc_config_module.config.computer.is_ingress_node is True

    _write_config(config_path)
    reload_config()

    assert _tc_config_module.config.computer.is_ingress_node is False
