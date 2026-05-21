"""Characterization tests for teleclaude.sync."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude import project_manifest, sync

pytestmark = pytest.mark.unit

_FORBIDDEN_SYNC_MANIFEST_SYMBOLS = frozenset({"project_manifest", "register_project", "register_root"})
_HEAD_SHA = "abc123"
_WORKFLOW_SNIPPET = "docs/project/spec/domain/workflow.md"
_DELIVERY_A = "delivery-a"
_DELIVERY_B = "delivery-b"
_DATABASE_URL = "postgres://postgres:postgres@localhost:5432/teleclaude"


class TestRunDistribute:
    def test_builds_deploy_command_with_warn_only_flag(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, snapshot: SnapshotAssertion
    ) -> None:
        script_path = tmp_path / "scripts" / "distribute.py"
        script_path.parent.mkdir(parents=True)
        script_path.write_text("print('ok')", encoding="utf-8")
        calls: list[tuple[list[str], Path, bool, dict[str, str]]] = []

        def fake_run(cmd: list[str], cwd: Path, check: bool, env: dict[str, str]) -> None:
            calls.append((cmd, cwd, check, env.copy()))

        monkeypatch.setattr(sync, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(sync.sys, "executable", "SYS_EXECUTABLE")
        monkeypatch.setattr(sync.subprocess, "run", fake_run)

        sync._run_distribute(tmp_path / "project", warn_only=True)

        assert [part.replace(str(tmp_path), "TMP") for part in calls[0][0]] == snapshot
        assert calls[0][1] == tmp_path / "project"
        assert calls[0][2] is False


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

    def test_format_finding_includes_all_extra_fields(self, snapshot: SnapshotAssertion) -> None:
        formatted = sync._format_finding(
            {
                "code": "snippet_missing_frontmatter_field",
                "path": "docs/third-party/tool.md",
                "field": "id",
            }
        )

        assert formatted == snapshot


class TestSyncValidation:
    def test_validate_only_fails_with_all_invalid_third_party_docs(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        snapshot: SnapshotAssertion,
    ) -> None:
        docs_root = tmp_path / "docs" / "third-party"
        docs_root.mkdir(parents=True)
        (docs_root / "one.md").write_text("# One\n\n## Sources\n- https://example.com\n", encoding="utf-8")
        (docs_root / "two.md").write_text("# Two\n\n## Sources\n- https://example.com\n", encoding="utf-8")

        monkeypatch.setattr(sync, "validate_all_artifacts", lambda _: [])
        monkeypatch.setattr(sync, "validate_jobs_config", lambda _: [])

        assert sync.sync(tmp_path, validate_only=True) is False
        out = capsys.readouterr().out
        assert out.replace(str(tmp_path), "TMP") == snapshot


class TestSyncBootstrapOrdering:
    def test_build_all_indexes_called_before_run_distribute(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, snapshot: SnapshotAssertion
    ) -> None:
        """Pins R2: build_all_indexes must precede _run_distribute in the sync pipeline."""
        call_order: list[str] = []

        monkeypatch.setattr(sync, "validate_all_snippets", lambda _project_root: None)
        monkeypatch.setattr(sync, "validate_all_artifacts", lambda _: [])
        monkeypatch.setattr(sync, "validate_jobs_config", lambda _: [])
        monkeypatch.setattr(sync, "get_errors", lambda: [])
        monkeypatch.setattr(sync, "clear_errors", lambda: None)

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
        assert call_order == snapshot

    def test_full_sync_validates_once_before_index_and_distribute(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, snapshot: SnapshotAssertion
    ) -> None:
        call_order: list[str] = []

        monkeypatch.setattr(sync, "clear_errors", lambda: None)
        monkeypatch.setattr(sync, "get_errors", lambda: [])
        monkeypatch.setattr(sync, "validate_all_artifacts", lambda _project_root: [])
        monkeypatch.setattr(sync, "validate_jobs_config", lambda _project_root: [])

        def fake_validate_all_snippets(project_root: Path) -> None:
            assert project_root == tmp_path
            call_order.append("validate")

        def fake_build_all_indexes(project_root: Path) -> list[Path]:
            assert project_root == tmp_path
            call_order.append("build_all_indexes")
            return []

        monkeypatch.setattr(sync, "validate_all_snippets", fake_validate_all_snippets)
        monkeypatch.setattr(sync, "build_all_indexes", fake_build_all_indexes)
        monkeypatch.setattr(
            sync,
            "_run_distribute",
            lambda _project_root, **_kwargs: call_order.append("_run_distribute"),
        )

        assert sync.sync(tmp_path) is True
        assert call_order == snapshot

    def test_validate_only_calls_validate_once_and_skips_indexes(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, snapshot: SnapshotAssertion
    ) -> None:
        call_order: list[str] = []

        monkeypatch.setattr(sync, "clear_errors", lambda: None)
        monkeypatch.setattr(sync, "get_errors", lambda: [])
        monkeypatch.setattr(sync, "validate_all_artifacts", lambda _project_root: [])
        monkeypatch.setattr(sync, "validate_jobs_config", lambda _project_root: [])

        def fake_validate_all_snippets(project_root: Path) -> None:
            assert project_root == tmp_path
            call_order.append("validate")

        monkeypatch.setattr(sync, "validate_all_snippets", fake_validate_all_snippets)

        assert sync.sync(tmp_path, validate_only=True) is True
        assert call_order == snapshot

    def test_full_sync_does_not_run_source_markdown_repair(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(sync, "clear_errors", lambda: None)
        monkeypatch.setattr(sync, "get_errors", lambda: [])
        monkeypatch.setattr(sync, "validate_all_snippets", lambda _project_root: None)
        monkeypatch.setattr(sync, "validate_all_artifacts", lambda _project_root: [])
        monkeypatch.setattr(sync, "validate_jobs_config", lambda _project_root: [])
        monkeypatch.setattr(sync, "build_all_indexes", lambda _project_root: [])
        monkeypatch.setattr(sync, "_run_distribute", lambda _project_root, **_kwargs: None)

        assert sync.sync(tmp_path) is True

    def test_full_sync_leaves_broken_baseline_symlink_unchanged(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        baseline_path = tmp_path / "docs" / "global" / "baseline.md"
        baseline_path.parent.mkdir(parents=True)
        os.symlink("baseline.md", baseline_path)
        before_target = os.readlink(baseline_path)

        monkeypatch.setattr(sync, "clear_errors", lambda: None)
        monkeypatch.setattr(sync, "get_errors", lambda: [])
        monkeypatch.setattr(sync, "validate_all_snippets", lambda _project_root: None)
        monkeypatch.setattr(sync, "validate_all_artifacts", lambda _project_root: [])
        monkeypatch.setattr(sync, "validate_jobs_config", lambda _project_root: [])
        monkeypatch.setattr(sync, "build_all_indexes", lambda _project_root: [])
        monkeypatch.setattr(sync, "_run_distribute", lambda _project_root, **_kwargs: None)

        assert sync.sync(tmp_path) is True
        assert baseline_path.is_symlink()
        assert os.readlink(baseline_path) == before_target


class TestSnippetProvenance:
    def test_collects_one_record_per_delivered_by_slug(self, tmp_path: Path) -> None:
        snippet_path = tmp_path / _WORKFLOW_SNIPPET
        snippet_path.parent.mkdir(parents=True)
        snippet_path.write_text(
            f"""---
id: project/spec/domain/workflow
type: spec
scope: project
status: target
delivered_by:
- {_DELIVERY_A}
- {_DELIVERY_B}
---
# Workflow
""",
            encoding="utf-8",
        )

        records = sync._collect_snippet_provenance_records(tmp_path, _HEAD_SHA)

        assert records == [
            sync.SnippetProvenanceRecord(_WORKFLOW_SNIPPET, _DELIVERY_A, _HEAD_SHA),
            sync.SnippetProvenanceRecord(_WORKFLOW_SNIPPET, _DELIVERY_B, _HEAD_SHA),
        ]

    def test_records_snippet_provenance_before_building_indexes(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        call_order: list[str] = []

        monkeypatch.setattr(sync, "clear_errors", lambda: None)
        monkeypatch.setattr(sync, "get_errors", lambda: [])
        monkeypatch.setattr(sync, "validate_all_artifacts", lambda _project_root: [])
        monkeypatch.setattr(sync, "validate_jobs_config", lambda _project_root: [])
        monkeypatch.setattr(sync, "validate_all_snippets", lambda _project_root, **_kwargs: None)

        def fake_record(project_root: Path) -> int:
            assert project_root == tmp_path
            call_order.append("record_snippet_provenance")
            return 1

        def fake_build(project_root: Path) -> list[Path]:
            assert project_root == tmp_path
            call_order.append("build_all_indexes")
            return []

        monkeypatch.setattr(sync, "_record_snippet_provenance_from_environment", fake_record)
        monkeypatch.setattr(sync, "build_all_indexes", fake_build)
        monkeypatch.setattr(sync, "_run_distribute", lambda _project_root, **_kwargs: None)

        assert sync.sync(tmp_path) is True
        assert call_order == ["record_snippet_provenance", "build_all_indexes"]

    def test_record_imports_current_head_for_each_membership(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        snippet_path = tmp_path / _WORKFLOW_SNIPPET
        snippet_path.parent.mkdir(parents=True)
        snippet_path.write_text(
            f"""---
id: project/spec/domain/workflow
type: spec
scope: project
status: target
delivered_by:
- {_DELIVERY_A}
---
# Workflow
""",
            encoding="utf-8",
        )
        imports: list[tuple[str, str]] = []

        def fake_import(database_url: str, script: str) -> None:
            imports.append((database_url, script))

        monkeypatch.setattr(sync, "_run_psql_snippet_provenance_import", fake_import)

        count = sync._record_snippet_provenance(tmp_path, _HEAD_SHA, _DATABASE_URL)

        assert count == 1
        assert imports == [
            (
                _DATABASE_URL,
                sync._render_snippet_provenance_import_script(
                    [sync.SnippetProvenanceRecord(_WORKFLOW_SNIPPET, _DELIVERY_A, _HEAD_SHA)]
                ),
            )
        ]


class TestSyncDoesNotRegisterProject:
    """Post-migration: ``telec sync`` MUST NOT write to the project registry.

    Registration is now owned exclusively by ``telec init``. The registry
    module and its public symbols must not appear anywhere in ``sync``.
    """

    def test_sync_module_does_not_import_project_manifest(self) -> None:
        source = Path(sync.__file__).read_text(encoding="utf-8")
        imported_or_referenced = {symbol for symbol in _FORBIDDEN_SYNC_MANIFEST_SYMBOLS if symbol in source}
        assert imported_or_referenced == set()

    def test_sync_pipeline_does_not_touch_manifest_file(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """The sync pipeline must never write to ``~/.teleclaude/projects.yaml``."""
        manifest_path = tmp_path / "state" / "projects.yaml"
        monkeypatch.setattr(project_manifest, "MANIFEST_PATH", manifest_path)

        monkeypatch.setattr(sync, "validate_all_snippets", lambda _project_root: None)
        monkeypatch.setattr(sync, "validate_all_artifacts", lambda _: [])
        monkeypatch.setattr(sync, "validate_jobs_config", lambda _: [])
        monkeypatch.setattr(sync, "get_errors", lambda: [])
        monkeypatch.setattr(sync, "clear_errors", lambda: None)
        monkeypatch.setattr(sync, "build_all_indexes", lambda _: [])
        monkeypatch.setattr(sync, "_run_distribute", lambda _pr, **_kw: None)

        assert sync.sync(tmp_path / "project") is True
        assert not manifest_path.exists()
