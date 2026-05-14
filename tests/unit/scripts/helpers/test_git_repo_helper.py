"""Regression tests for scripts/helpers/git_repo_helper.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Protocol, cast
from unittest.mock import patch

import pytest
import yaml

_SCRIPT_GIT_REPO_HELPER_PATH = Path(__file__).resolve().parents[4] / "scripts" / "helpers" / "git_repo_helper.py"


class _ScriptGitRepoHelper(Protocol):
    GLOBAL_CONFIG_PATH: Path

    def _load_checkout_root(self) -> Path: ...


def _load_script_git_repo_helper() -> _ScriptGitRepoHelper:
    spec = importlib.util.spec_from_file_location("scripts_git_repo_helper_under_test", _SCRIPT_GIT_REPO_HELPER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(_ScriptGitRepoHelper, module)


class TestScriptGitRepoHelper:
    def test_invalid_global_config_fails_visibly(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        helper = _load_script_git_repo_helper()
        config_path = tmp_path / "teleclaude.yml"
        config_path.write_text("git: [\n", encoding="utf-8")
        monkeypatch.setattr(helper, "GLOBAL_CONFIG_PATH", config_path)

        with pytest.raises(SystemExit) as exc_info:
            helper._load_checkout_root()

        assert isinstance(exc_info.value.__cause__, yaml.YAMLError)

    def test_unreadable_global_config_fails_visibly(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        helper = _load_script_git_repo_helper()
        config_path = tmp_path / "teleclaude.yml"
        config_path.write_text("git: {}\n", encoding="utf-8")
        monkeypatch.setattr(helper, "GLOBAL_CONFIG_PATH", config_path)

        with patch.object(Path, "read_text", side_effect=OSError), pytest.raises(SystemExit) as exc_info:
            helper._load_checkout_root()

        assert isinstance(exc_info.value.__cause__, OSError)
