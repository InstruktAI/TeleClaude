"""Characterization tests for teleclaude.sync."""

# pylint: disable=protected-access
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from teleclaude import sync
from teleclaude.git import GitCommandError

pytestmark = pytest.mark.unit


class TestRunDistribute:
    def test_builds_deploy_command_with_warn_only_flag(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        script_path = tmp_path / "scripts" / "distribute.py"
        script_path.parent.mkdir(parents=True)
        script_path.write_text("print('ok')", encoding="utf-8")
        calls: list[tuple[list[str], Path, bool, dict[str, str]]] = []

        def fake_run(cmd: list[str], cwd: Path, check: bool, env: dict[str, str]) -> None:
            calls.append((cmd, cwd, check, env.copy()))

        monkeypatch.setattr(sync, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(sync.subprocess, "run", fake_run)

        sync._run_distribute(tmp_path / "project", warn_only=True)

        assert calls[0][0] == [
            sync.sys.executable,
            str(script_path),
            "--project-root",
            str(tmp_path / "project"),
            "--deploy",
            "--warn-only",
        ]
        assert calls[0][1] == tmp_path / "project"
        assert calls[0][2] is False


class TestRepairBrokenDocsLinks:
    def test_restores_self_referential_symlink_from_git_blob(self, tmp_path: Path) -> None:
        project_root = tmp_path
        docs_dir = project_root / "docs" / "global"
        docs_dir.mkdir(parents=True)
        baseline_path = docs_dir / "baseline.md"
        os.symlink("baseline.md", baseline_path)

        mock_repo = MagicMock()

        def fake_show(ref: str) -> str:
            if ref == "HEAD:docs/global/baseline.md":
                return "restored baseline\n"
            raise GitCommandError("git show", 1)

        mock_repo.git.show = fake_show

        with patch("teleclaude.git.Repo", return_value=mock_repo):
            sync._repair_broken_docs_links(project_root)

        assert baseline_path.is_symlink() is False
        assert baseline_path.read_text(encoding="utf-8") == "restored baseline\n"

    def test_repair_broken_docs_links_excludes_index_yaml_from_git_recovery(self, tmp_path: Path) -> None:
        project_root = tmp_path
        (project_root / "docs" / "global").mkdir(parents=True)
        # index.yaml absent — simulates missing-file scenario that would trigger repair

        mock_repo = MagicMock()
        git_calls: list[str] = []
        mock_repo.git.show = lambda ref: git_calls.append(ref) or ""

        with patch("teleclaude.git.Repo", return_value=mock_repo):
            sync._repair_broken_docs_links(project_root)

        # After Task 2.1, index.yaml must not be in tracked_docs_files.
        # Git show must never be called for index.yaml.
        assert not any("index.yaml" in call for call in git_calls)


class TestGroupFindings:
    def test_groups_findings_by_code_and_reason(self) -> None:
        grouped = sync._group_findings(
            [
                {"code": "missing", "path": "docs/a.md"},
                {"code": "missing", "path": "docs/b.md", "reason": "bad_ref"},
            ]
        )

        assert grouped == {
            "missing": {
                "": ["docs/a.md"],
                "bad_ref": ["docs/b.md"],
            }
        }


class TestSyncBootstrapOrdering:
    def test_build_all_indexes_called_before_run_distribute(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Pins R2: build_all_indexes must precede _run_distribute in the sync pipeline."""
        call_order: list[str] = []

        monkeypatch.setattr(sync, "validate_all_snippets", lambda _: None)
        monkeypatch.setattr(sync, "validate_third_party_docs", lambda _: None)
        monkeypatch.setattr(sync, "validate_all_artifacts", lambda _: [])
        monkeypatch.setattr(sync, "validate_jobs_config", lambda _: [])
        monkeypatch.setattr(sync, "get_errors", lambda: [])
        monkeypatch.setattr(sync, "clear_errors", lambda: None)
        monkeypatch.setattr(sync, "_repair_broken_docs_links", lambda _: None)
        monkeypatch.setattr(sync, "_register_project_manifest", lambda _: None)

        def fake_build_all_indexes(_: Path) -> list[Path]:
            call_order.append("build_all_indexes")
            return []

        def fake_run_distribute(project_root: Path, *, warn_only: bool = False) -> None:
            del project_root, warn_only
            call_order.append("_run_distribute")

        monkeypatch.setattr(sync, "build_all_indexes", fake_build_all_indexes)
        monkeypatch.setattr(sync, "_run_distribute", fake_run_distribute)

        result = sync.sync(tmp_path)

        assert result is True
        assert call_order.index("build_all_indexes") < call_order.index("_run_distribute")


class TestRegisterProjectManifest:
    def test_uses_trimmed_project_name_and_description(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        config_path = tmp_path / "teleclaude.yml"
        config_path.write_text("project: demo", encoding="utf-8")
        calls: list[tuple[Path, Path, str, str, Path]] = []

        def fake_load_project_config(path: Path) -> SimpleNamespace:
            assert path == config_path
            return SimpleNamespace(project_name=" Demo ", description=" Example ")

        def fake_register_project(
            path: Path,
            project_root: Path,
            project_name: str,
            description: str,
            index_path: Path,
        ) -> None:
            calls.append((path, project_root, project_name, description, index_path))

        monkeypatch.setattr(sync, "load_project_config", fake_load_project_config)
        monkeypatch.setattr(sync, "register_project", fake_register_project)

        sync._register_project_manifest(tmp_path)

        assert calls == [
            (
                sync.MANIFEST_PATH,
                tmp_path,
                "Demo",
                "Example",
                tmp_path / "docs" / "project" / "index.yaml",
            )
        ]
