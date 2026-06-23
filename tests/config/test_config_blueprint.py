"""Functional bindings for the tier-driven public config sample generator.

Binds ``project/policy/config-public-surface``: the generated
``templates/config.yml`` is a consequence of the machine-config field tiers — it
carries the ``public``/``tui`` surface, omits ``internal`` fields, preserves the
curated comments and seed bodies, and remains seedable by the bootstrap.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from teleclaude.config import deep_merge
from teleclaude.config._blueprint import generate_sample_file
from teleclaude.config._bootstrap import resolve_runtime_config_path
from teleclaude.runtime.config import RuntimeConfig, get_runtime_config, set_runtime_config

pytestmark = [pytest.mark.functional]

# A curated sample: a comment, a public section (computer) with a seed body
# (trusted_dirs), plus an internal section (polling) that the tier map must drop.
_CURATED_SAMPLE = """\
# Curated header comment
computer:
  name: Mac # inline comment kept
  trusted_dirs:
    - name: Workspace
      path: /tmp/ws
polling:
  directory_check_interval: 5
"""

CHIPTUNES = "chiptunes"
COMPUTER = "computer"
POLLING = "polling"
WORKFLOW = "workflow"
RUNNER = "runner"
RUNNER_AUTOSTART = "autostart"
WORKSPACE_NAME = "Workspace"
COMPUTER_NAME = "Mac"


def _write_template(tmp_path: Path) -> Path:
    template = tmp_path / "config.yml"
    template.write_text(_CURATED_SAMPLE, encoding="utf-8")
    return template


def test_generated_sample_reflects_tiers_and_preserves_curated_content(tmp_path, snapshot):
    template = _write_template(tmp_path)

    assert generate_sample_file(template) is True

    text = template.read_text(encoding="utf-8")
    data = YAML().load(text)

    # Public/tui sections are present; an internal section (polling) is dropped.
    assert COMPUTER in data
    assert POLLING not in data
    # A public/tui field missing from the curated sample is added from the tiers.
    assert CHIPTUNES in data
    # Nested public leaves are reconciled, not just top-level sections: workflow.runner
    # is tier=public and must be surfaced even though the workflow section pre-exists.
    assert data[WORKFLOW][RUNNER] == RUNNER_AUTOSTART
    assert data["computer"]["trusted_dirs"][0]["name"] == WORKSPACE_NAME

    # Curated comments and the full generated body are pinned by snapshot (no
    # string-content assertions against the generated YAML text).
    assert text == snapshot


def test_generation_is_idempotent(tmp_path):
    template = _write_template(tmp_path)

    assert generate_sample_file(template) is True
    after_first = template.read_text(encoding="utf-8")

    # A second pass finds no drift and leaves the file byte-for-byte unchanged.
    assert generate_sample_file(template) is False
    assert template.read_text(encoding="utf-8") == after_first


def test_generated_sample_still_seeds_runtime_config(tmp_path):
    template = _write_template(tmp_path)
    generate_sample_file(template)

    old_rc = get_runtime_config()
    home = tmp_path / "home"
    home.mkdir()
    set_runtime_config(
        RuntimeConfig(
            home=home,
            config_path=None,
            env_path=old_rc.env_path,
            project_config_path=old_rc.project_config_path,
            tmpdir_base=old_rc.tmpdir_base,
        )
    )
    try:
        runtime_path = resolve_runtime_config_path(template, deep_merge)
        assert runtime_path.exists()
        seeded = YAML().load(runtime_path.read_text(encoding="utf-8"))
        assert seeded[COMPUTER]["name"] == COMPUTER_NAME
        assert POLLING not in seeded
    finally:
        set_runtime_config(old_rc)
