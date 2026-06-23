"""Functional bindings for the legacy release-channel migration.

The release channel moved from per-project ``teleclaude.yml`` to the machine
``config.yml``. A ``deployment:`` block in an existing project file is folded into
the machine config on the daemon load path and reaches the runtime reader
(``config.deployment``); the source key is stripped so it cannot shadow the
machine surface. A corrupt machine config is never clobbered.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from ruamel.yaml import YAML

import teleclaude.config as _tc_config_module
from teleclaude.config import reload_config
from teleclaude.project_setup.init_flow import migrate_legacy_deployment_channel
from teleclaude.runtime.config import RuntimeConfig, get_runtime_config, set_runtime_config

pytestmark = [pytest.mark.functional]

BETA = "beta"
ALPHA = "alpha"
DEPLOYMENT = "deployment"
CHANNEL = "channel"
PINNED_MINOR = "pinned_minor"
PROJECT_SLUG = "demo"


def _write(path: Path, data: object) -> None:
    YAML().dump(data, path)


def test_legacy_deployment_migrates_and_reaches_runtime_reader(tmp_path, monkeypatch):
    """Load-path coverage: a legacy project deployment block reaches config.deployment."""
    source = tmp_path / "teleclaude.yml"
    machine = tmp_path / "config.yml"
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")
    _write(source, {"project_slug": PROJECT_SLUG, DEPLOYMENT: {CHANNEL: BETA, PINNED_MINOR: ""}})
    _write(
        machine,
        {
            "computer": {"name": "PC", "role": "development", "timezone": "Europe/Amsterdam", "is_master": True},
            "agents": {"default": "claude", "claude": {"system_prompt": "hi"}},
            DEPLOYMENT: {CHANNEL: ALPHA, PINNED_MINOR: ""},
        },
    )

    old_rc = get_runtime_config()
    monkeypatch.setattr(_tc_config_module, "_config_path", machine)
    monkeypatch.setattr(_tc_config_module, "config_path", machine)
    set_runtime_config(
        RuntimeConfig(
            home=old_rc.home,
            config_path=machine,
            env_path=env_path,
            project_config_path=old_rc.project_config_path,
            tmpdir_base=old_rc.tmpdir_base,
        )
    )
    try:
        assert migrate_legacy_deployment_channel(source, machine) is True
        reload_config()
        # The runtime reader sees the migrated channel, not the seeded default.
        assert _tc_config_module.config.deployment.channel == BETA
        # The atomic source-strip rewrite removes the legacy key while preserving the
        # surrounding round-trip YAML tree.
        source_doc = YAML().load(source.read_text(encoding="utf-8"))
        assert DEPLOYMENT not in source_doc
        assert source_doc["project_slug"] == PROJECT_SLUG
    finally:
        set_runtime_config(old_rc)
        reload_config()


def test_file_without_deployment_is_untouched(tmp_path):
    source = tmp_path / "teleclaude.yml"
    machine = tmp_path / "config.yml"
    _write(source, {"project_slug": PROJECT_SLUG})
    before = source.read_text(encoding="utf-8")

    assert migrate_legacy_deployment_channel(source, machine) is False
    assert source.read_text(encoding="utf-8") == before
    assert not machine.exists()


def test_corrupt_machine_config_is_not_clobbered(tmp_path):
    """A read/parse failure on the machine config fails loudly and leaves it untouched."""
    source = tmp_path / "teleclaude.yml"
    machine = tmp_path / "config.yml"
    _write(source, {DEPLOYMENT: {CHANNEL: BETA, PINNED_MINOR: ""}})
    # A non-mapping machine config: writing a deployment-only document would destroy it.
    machine.write_text("- not\n- a\n- mapping\n", encoding="utf-8")
    before = machine.read_text(encoding="utf-8")

    with pytest.raises(ValueError):
        migrate_legacy_deployment_channel(source, machine)

    # The corrupt machine config is left exactly as it was — never overwritten.
    assert machine.read_text(encoding="utf-8") == before
    # The source still carries its block (migration aborted before stripping it).
    source_doc = YAML().load(source.read_text(encoding="utf-8"))
    assert DEPLOYMENT in source_doc
