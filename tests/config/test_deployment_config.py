"""Functional bindings for the machine-config release channel (deployment).

The release channel is a machine-wide concern: it lives on ``TeleclaudeConfig``
(``config.deployment``), is parsed from ``config.yml:deployment`` at load, and
rejects a ``stable`` channel that omits ``pinned_minor``.
"""

from __future__ import annotations

import pytest
from ruamel.yaml import YAML

import teleclaude.config as _tc_config_module
from teleclaude.config import _parse_deployment_config, reload_config
from teleclaude.runtime.config import RuntimeConfig, get_runtime_config, set_runtime_config

pytestmark = [pytest.mark.functional]

BETA = "beta"
STABLE = "stable"
PINNED_MINOR = "1.2"


def _write_machine_config(path, deployment: dict) -> None:
    YAML().dump(
        {
            "computer": {"name": "PC", "role": "development", "timezone": "Europe/Amsterdam", "is_master": True},
            "agents": {"default": "claude", "claude": {"system_prompt": "hi"}},
            "deployment": deployment,
        },
        path,
    )


def test_deployment_channel_loads_from_machine_config(tmp_path, monkeypatch):
    machine_config_path = tmp_path / "config.yml"
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")
    _write_machine_config(machine_config_path, {"channel": BETA})

    old_rc = get_runtime_config()
    monkeypatch.setattr(_tc_config_module, "_config_path", machine_config_path)
    monkeypatch.setattr(_tc_config_module, "config_path", machine_config_path)
    set_runtime_config(
        RuntimeConfig(
            home=old_rc.home,
            config_path=machine_config_path,
            env_path=env_path,
            project_config_path=old_rc.project_config_path,
            tmpdir_base=old_rc.tmpdir_base,
        )
    )
    try:
        reload_config()
        assert _tc_config_module.config.deployment.channel == BETA
    finally:
        set_runtime_config(old_rc)
        reload_config()


def test_stable_channel_requires_pinned_minor():
    with pytest.raises(ValueError):
        _parse_deployment_config({"channel": STABLE})

    parsed = _parse_deployment_config({"channel": STABLE, "pinned_minor": PINNED_MINOR})
    assert parsed.channel == STABLE
    assert parsed.pinned_minor == PINNED_MINOR
