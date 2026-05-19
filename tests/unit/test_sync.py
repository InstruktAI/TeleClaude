"""Characterization tests for teleclaude.sync."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from teleclaude import project_manifest, sync
from teleclaude.constants import RoadmapStatus
from teleclaude.docs_reconcile import SnippetStatusReconcileResult
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

        with patch("teleclaude.sync.Repo", return_value=mock_repo):
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

        with patch("teleclaude.sync.Repo", return_value=mock_repo):
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

    def test_format_finding_includes_all_extra_fields(self) -> None:
        formatted = sync._format_finding(
            {
                "code": "snippet_missing_frontmatter_field",
                "path": "docs/third-party/tool.md",
                "field": "id",
            }
        )

        assert formatted == "snippet_missing_frontmatter_field: docs/third-party/tool.md (field=id)"


class TestSyncValidation:
    def test_validate_only_fails_with_all_invalid_third_party_docs(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        docs_root = tmp_path / "docs" / "third-party"
        docs_root.mkdir(parents=True)
        (docs_root / "one.md").write_text("# One\n\n## Sources\n- https://example.com\n", encoding="utf-8")
        (docs_root / "two.md").write_text("# Two\n\n## Sources\n- https://example.com\n", encoding="utf-8")

        monkeypatch.setattr(sync, "_repair_broken_docs_links", lambda _: None)
        monkeypatch.setattr(sync, "validate_all_artifacts", lambda _: [])
        monkeypatch.setattr(sync, "validate_jobs_config", lambda _: [])

        assert sync.sync(tmp_path, validate_only=True) is False
        out = capsys.readouterr().out
        assert str(docs_root / "one.md") in out
        assert str(docs_root / "two.md") in out


class TestSyncBootstrapOrdering:
    def test_build_all_indexes_called_before_run_distribute(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Pins R2: build_all_indexes must precede _run_distribute in the sync pipeline."""
        call_order: list[str] = []

        monkeypatch.setattr(sync, "build_roadmap_status_map", lambda _project_root: {})
        monkeypatch.setattr(sync, "validate_all_snippets", lambda _project_root, **_kwargs: None)
        monkeypatch.setattr(sync, "reconcile_snippet_status", lambda _project_root, _roadmap_status_map: [])
        monkeypatch.setattr(sync, "validate_all_artifacts", lambda _: [])
        monkeypatch.setattr(sync, "validate_jobs_config", lambda _: [])
        monkeypatch.setattr(sync, "get_errors", lambda: [])
        monkeypatch.setattr(sync, "clear_errors", lambda: None)
        monkeypatch.setattr(sync, "_repair_broken_docs_links", lambda _: None)

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

    def test_full_sync_reconciles_between_validation_and_index(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        call_order: list[str] = []
        roadmap_status_map = {"work-a": RoadmapStatus.DELIVERED}

        monkeypatch.setattr(sync, "_repair_broken_docs_links", lambda _project_root: None)
        monkeypatch.setattr(sync, "clear_errors", lambda: None)
        monkeypatch.setattr(sync, "get_errors", lambda: [])
        monkeypatch.setattr(sync, "validate_all_artifacts", lambda _project_root: [])
        monkeypatch.setattr(sync, "validate_jobs_config", lambda _project_root: [])
        monkeypatch.setattr(sync, "build_roadmap_status_map", lambda _project_root: roadmap_status_map)

        def fake_validate_all_snippets(
            project_root: Path,
            *,
            roadmap_status_map: dict[str, str],
            enforce_delivered_drift: bool,
        ) -> None:
            assert project_root == tmp_path
            assert roadmap_status_map == {"work-a": RoadmapStatus.DELIVERED}
            call_order.append(f"validate:{enforce_delivered_drift}")

        def fake_reconcile(project_root: Path, passed_map: dict[str, str]) -> list[SnippetStatusReconcileResult]:
            assert project_root == tmp_path
            assert passed_map == roadmap_status_map
            call_order.append("reconcile")
            return []

        def fake_build_all_indexes(project_root: Path) -> list[Path]:
            assert project_root == tmp_path
            call_order.append("build_all_indexes")
            return []

        monkeypatch.setattr(sync, "validate_all_snippets", fake_validate_all_snippets)
        monkeypatch.setattr(sync, "reconcile_snippet_status", fake_reconcile)
        monkeypatch.setattr(sync, "build_all_indexes", fake_build_all_indexes)
        monkeypatch.setattr(
            sync,
            "_run_distribute",
            lambda _project_root, **_kwargs: call_order.append("_run_distribute"),
        )

        assert sync.sync(tmp_path) is True
        assert call_order == [
            "validate:False",
            "reconcile",
            "validate:True",
            "build_all_indexes",
            "_run_distribute",
        ]

    def test_validate_only_enforces_drift_and_skips_reconcile(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        call_order: list[str] = []
        roadmap_status_map = {"work-a": RoadmapStatus.DELIVERED}

        monkeypatch.setattr(sync, "_repair_broken_docs_links", lambda _project_root: None)
        monkeypatch.setattr(sync, "clear_errors", lambda: None)
        monkeypatch.setattr(sync, "get_errors", lambda: [])
        monkeypatch.setattr(sync, "validate_all_artifacts", lambda _project_root: [])
        monkeypatch.setattr(sync, "validate_jobs_config", lambda _project_root: [])
        monkeypatch.setattr(sync, "build_roadmap_status_map", lambda _project_root: roadmap_status_map)

        def fake_validate_all_snippets(
            project_root: Path,
            *,
            roadmap_status_map: dict[str, str],
            enforce_delivered_drift: bool,
        ) -> None:
            assert project_root == tmp_path
            assert roadmap_status_map == {"work-a": RoadmapStatus.DELIVERED}
            call_order.append(f"validate:{enforce_delivered_drift}")

        def fail_reconcile(
            _project_root: Path, _roadmap_status_map: dict[str, str]
        ) -> list[SnippetStatusReconcileResult]:
            raise AssertionError("validate-only must not reconcile snippets")

        monkeypatch.setattr(sync, "validate_all_snippets", fake_validate_all_snippets)
        monkeypatch.setattr(sync, "reconcile_snippet_status", fail_reconcile)

        assert sync.sync(tmp_path, validate_only=True) is True
        assert call_order == ["validate:True"]


class TestSyncDoesNotRegisterProject:
    """Post-migration: ``telec sync`` MUST NOT write to the project registry.

    Registration is now owned exclusively by ``telec init``. The registry
    module and its public symbols must not appear anywhere in ``sync``.
    """

    def test_sync_module_does_not_import_project_manifest(self) -> None:
        source = Path(sync.__file__).read_text(encoding="utf-8")
        assert "project_manifest" not in source
        assert "register_project" not in source
        assert "register_root" not in source

    def test_sync_pipeline_does_not_touch_manifest_file(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """The sync pipeline must never write to ``~/.teleclaude/projects.yaml``."""
        manifest_path = tmp_path / "state" / "projects.yaml"
        monkeypatch.setattr(project_manifest, "MANIFEST_PATH", manifest_path)

        monkeypatch.setattr(sync, "build_roadmap_status_map", lambda _project_root: {})
        monkeypatch.setattr(sync, "validate_all_snippets", lambda _project_root, **_kwargs: None)
        monkeypatch.setattr(sync, "reconcile_snippet_status", lambda _project_root, _roadmap_status_map: [])
        monkeypatch.setattr(sync, "validate_all_artifacts", lambda _: [])
        monkeypatch.setattr(sync, "validate_jobs_config", lambda _: [])
        monkeypatch.setattr(sync, "get_errors", lambda: [])
        monkeypatch.setattr(sync, "clear_errors", lambda: None)
        monkeypatch.setattr(sync, "_repair_broken_docs_links", lambda _: None)
        monkeypatch.setattr(sync, "build_all_indexes", lambda _: [])
        monkeypatch.setattr(sync, "_run_distribute", lambda _pr, **_kw: None)

        assert sync.sync(tmp_path / "project") is True
        assert not manifest_path.exists()
