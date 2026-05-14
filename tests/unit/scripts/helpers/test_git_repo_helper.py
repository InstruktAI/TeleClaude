"""Regression tests for scripts/helpers/git_repo_helper.py."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from scripts.helpers import git_repo_helper


class TestScriptGitRepoHelper:
    def _block_repo_side_effects(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def unexpected_ensure_repo(_repo_url: str, _repo_path: Path) -> tuple[list[str], list[str]]:
            pytest.fail("config error tests must not reach git clone/update")

        monkeypatch.setattr(git_repo_helper, "_ensure_repo", unexpected_ensure_repo)

    def test_invalid_global_config_fails_visibly(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = tmp_path / "teleclaude.yml"
        config_path.write_text("git: [\n", encoding="utf-8")
        monkeypatch.setattr(git_repo_helper, "GLOBAL_CONFIG_PATH", config_path)
        monkeypatch.setattr(sys, "argv", ["git_repo_helper.py", "--url", "https://github.com/org/repo.git"])
        self._block_repo_side_effects(monkeypatch)

        with pytest.raises(SystemExit) as exc_info:
            git_repo_helper.main()

        assert isinstance(exc_info.value.__cause__, yaml.YAMLError)

    def test_unreadable_global_config_fails_visibly(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = tmp_path / "teleclaude.yml"
        config_path.write_text("git: {}\n", encoding="utf-8")
        monkeypatch.setattr(git_repo_helper, "GLOBAL_CONFIG_PATH", config_path)
        monkeypatch.setattr(sys, "argv", ["git_repo_helper.py", "--url", "https://github.com/org/repo.git"])
        self._block_repo_side_effects(monkeypatch)

        with patch.object(Path, "read_text", side_effect=OSError), pytest.raises(SystemExit) as exc_info:
            git_repo_helper.main()

        assert isinstance(exc_info.value.__cause__, OSError)
