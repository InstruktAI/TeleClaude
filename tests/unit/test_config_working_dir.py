"""Config working directory fallback tests."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


def _load_config_module(config_py: Path) -> object:
    module_name = "teleclaude_config_test_working_dir"
    if module_name in sys.modules:
        del sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, config_py)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_working_dir_fallback_used_for_database_path(monkeypatch, tmp_path):
    """Test that config fallbacks set WORKING_DIR for database path expansion."""
    repo_root = Path(__file__).resolve().parents[2]
    config_py = repo_root / "teleclaude" / "config.py"

    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")

    config_file = tmp_path / "config.yml"
    config_file.write_text("database:\n  path: ${WORKING_DIR}/teleclaude.db\n", encoding="utf-8")

    monkeypatch.setenv("TELECLAUDE_CONFIG_PATH", str(config_file))
    monkeypatch.setenv("TELECLAUDE_ENV_PATH", str(env_path))
    monkeypatch.delenv("WORKING_DIR", raising=False)
    monkeypatch.delenv("TELECLAUDE_DB_PATH", raising=False)

    module = _load_config_module(config_py)

    assert os.environ["WORKING_DIR"] == str(repo_root)
    assert module.config.database.path == str(repo_root / "teleclaude.db")
