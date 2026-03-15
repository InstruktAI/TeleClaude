"""Characterization tests for teleclaude.sync."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from teleclaude import sync

pytestmark = pytest.mark.unit


class TestRunDistribute:
    def test_builds_deploy_command_with_warn_only_flag(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        script_path = tmp_path / "scripts" / "distribute.py"
        script_path.parent.mkdir(parents=True)
        script_path.write_text("print('ok')", encoding="utf-8")
        calls: list[tuple[list[str], Path, bool, dict[str, str]]] = []
        monkeypatch.setattr(sync, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(
            sync.subprocess,
            "run",
            lambda cmd, cwd, check, env: calls.append((cmd, cwd, check, env.copy())),
        )

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
    def test_restores_self_referential_symlink_from_git_blob(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        project_root = tmp_path
        docs_dir = project_root / "docs" / "global"
        docs_dir.mkdir(parents=True)
        baseline_path = docs_dir / "baseline.md"
        os.symlink("baseline.md", baseline_path)
        responses = {
            "HEAD:docs/global/baseline.md": subprocess.CompletedProcess([], 0, stdout="restored baseline\n"),
            "HEAD:docs/global/index.yaml": subprocess.CompletedProcess([], 1, stdout=""),
        }

        def fake_run(
            cmd: list[str], cwd: Path, capture_output: bool, text: bool, check: bool
        ) -> subprocess.CompletedProcess:
            return responses[cmd[2]]

        monkeypatch.setattr(sync.subprocess, "run", fake_run)

        sync._repair_broken_docs_links(project_root)

        assert baseline_path.is_symlink() is False
        assert baseline_path.read_text(encoding="utf-8") == "restored baseline\n"


class TestPrintWarnings:
    def test_groups_warnings_by_code_and_reason(self, capsys: pytest.CaptureFixture[str]) -> None:
        sync._print_warnings(
            [
                {"code": "missing", "path": "docs/a.md"},
                {"code": "missing", "path": "docs/b.md", "reason": "bad_ref"},
            ],
            quiet=False,
        )

        output = capsys.readouterr().out
        assert "Validation warnings: 2" in output
        assert "missing:" in output
        assert "missing/bad_ref:" in output


class TestRegisterProjectManifest:
    def test_uses_trimmed_project_name_and_description(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        config_path = tmp_path / "teleclaude.yml"
        config_path.write_text("project: demo", encoding="utf-8")
        calls: list[tuple[Path, Path, str, str, Path]] = []
        monkeypatch.setattr(
            sync,
            "load_project_config",
            lambda path: SimpleNamespace(project_name=" Demo ", description=" Example "),
        )
        monkeypatch.setattr(
            sync,
            "register_project",
            lambda path, project_root, project_name, description, index_path: calls.append(
                (path, project_root, project_name, description, index_path)
            ),
        )

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
