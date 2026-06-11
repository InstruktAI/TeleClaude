from __future__ import annotations

import pytest
from ruamel.yaml import YAML

from teleclaude.cli.config_handlers import save_machine_config
from teleclaude.config import config

COMPUTER_KEY = "computer"


@pytest.mark.spec("project/spec/feature/config/machine-config-write", "UC-MCW-1")
def test_save_machine_config_success(tmp_path):
    target_path = tmp_path / "config.yml"

    # Save the config
    save_machine_config(config, path=target_path)

    # Verify file exists and has correct contents
    assert target_path.exists()
    yaml = YAML()
    with open(target_path, encoding="utf-8") as f:
        data = yaml.load(f)
    assert isinstance(data, dict)
    assert COMPUTER_KEY in data
    assert data[COMPUTER_KEY]["name"] == config.computer.name


@pytest.mark.spec("project/spec/feature/config/machine-config-write", "UC-MCW-2")
def test_save_machine_config_failure(tmp_path):
    # Setup: make a file at the parent path so mkdir fails
    parent_file = tmp_path / "parent_file"
    parent_file.write_text("not a directory", encoding="utf-8")
    target_path = parent_file / "config.yml"

    with pytest.raises(OSError):
        save_machine_config(config, path=target_path)

    # Verify no temp file or lock file is leaked
    assert not target_path.exists()
    assert not target_path.with_suffix(".tmp").exists()
    assert not target_path.with_suffix(".lock").exists()
