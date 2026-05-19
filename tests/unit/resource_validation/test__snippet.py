"""Characterization tests for teleclaude.resource_validation._snippet."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from teleclaude import paths as tc_paths
from teleclaude.constants import (
    SNIPPET_STATUS_ACTUAL,
    SNIPPET_STATUS_MIXED,
    SNIPPET_STATUS_TARGET,
)
from teleclaude.resource_validation import _models as resource_models
from teleclaude.resource_validation import _snippet

pytestmark = pytest.mark.unit


def _write_roadmap_db(project_root: Path, rows: list[tuple[str, str]]) -> None:
    db_path = project_root / ".teleclaude" / "todos.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE roadmap (slug TEXT NOT NULL, status TEXT NOT NULL)")  # guard: raw-sql
        conn.executemany("INSERT INTO roadmap (slug, status) VALUES (?, ?)", rows)  # guard: raw-sql
        conn.commit()
    finally:
        conn.close()


def _write_policy_snippet(snippets_root: Path, name: str, delivered_by: list[str]) -> None:
    slug = Path(name).with_suffix("").as_posix()
    snippet_path = snippets_root / name
    snippet_path.parent.mkdir(parents=True, exist_ok=True)
    snippet_path.write_text(
        (
            "---\n"
            f"id: project/policy/{slug}\n"
            "type: policy\n"
            "scope: project\n"
            "description: Policy snippet\n"
            f"status: {SNIPPET_STATUS_TARGET}\n"
            f"delivered_by: {delivered_by}\n"
            "---\n"
            "# Policy Snippet\n\n"
            "## Rules\nBody.\n\n"
            "## Rationale\nBody.\n\n"
            "## Scope\nBody.\n\n"
            "## Enforcement\nBody.\n\n"
            "## Exceptions\nBody.\n"
        ),
        encoding="utf-8",
    )


class TestResolveRefPath:
    def test_falls_back_to_project_docs_when_plain_docs_target_is_missing(self, tmp_path: Path) -> None:
        project_root = tmp_path
        current_path = project_root / "docs" / "project" / "policy" / "current.md"
        current_path.parent.mkdir(parents=True)
        current_path.write_text("current", encoding="utf-8")
        target = project_root / "docs" / "project" / "policy" / "target.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("target", encoding="utf-8")

        resolved = _snippet.resolve_ref_path("docs/policy/target.md", root_path=project_root, current_path=current_path)

        assert resolved == target.resolve()


class TestIterInlineRefs:
    def test_skips_code_fence_contents(self) -> None:
        refs = _snippet.iter_inline_refs(
            [
                "@docs/project/policy/one.md",
                "```md",
                "@docs/project/policy/two.md",
                "```",
                "- @docs/project/policy/three.md",
            ]
        )

        assert refs == ["@docs/project/policy/one.md", "@docs/project/policy/three.md"]


class TestCollectInlineRefErrors:
    def test_reports_missing_and_non_file_targets(self, tmp_path: Path) -> None:
        project_root = tmp_path
        snippet_path = project_root / "docs" / "project" / "policy" / "snippet.md"
        snippet_path.parent.mkdir(parents=True)
        snippet_path.write_text("body", encoding="utf-8")
        existing_dir = project_root / "docs" / "project" / "policy" / "folder.md"
        existing_dir.mkdir()

        errors = _snippet.collect_inline_ref_errors(
            project_root,
            snippet_path,
            [
                "@docs/project/policy/missing.md",
                "@docs/project/policy/folder.md",
            ],
            domains={"software-development"},
        )

        assert {error["code"] for error in errors} == {
            "snippet_inline_ref_missing",
            "snippet_inline_ref_not_file",
        }


class TestSeeAlsoValidation:
    def test_global_docs_require_global_prefix(self, tmp_path: Path) -> None:
        resource_models.clear_errors()
        path = tmp_path / "docs" / "global" / "general" / "policy" / "doc.md"
        path.parent.mkdir(parents=True)
        path.write_text("body", encoding="utf-8")

        _snippet._validate_see_also_ref("docs/project/policy/other.md", path, tmp_path)

        assert resource_models.get_errors()[0]["code"] == "snippet_see_also_bad_prefix"

    def test_global_docs_accept_smudged_home_prefix(self, tmp_path: Path) -> None:
        resource_models.clear_errors()
        path = tmp_path / "docs" / "global" / "general" / "policy" / "doc.md"
        path.parent.mkdir(parents=True)
        path.write_text("body", encoding="utf-8")
        target = tmp_path / "docs" / "global" / "general" / "concept" / "other.md"
        target.parent.mkdir(parents=True)
        target.write_text("body", encoding="utf-8")

        smudged_ref = str(tc_paths.GLOBAL_SNIPPETS_DIR / "general" / "concept" / "other.md")

        _snippet._validate_see_also_ref(smudged_ref, path, tmp_path)

        assert not resource_models.get_errors()


class TestStatusAndDeliveredByValidation:
    def test_target_status_without_delivered_by_is_rejected(self, tmp_path: Path) -> None:
        resource_models.clear_errors()
        snippet_path = tmp_path / "docs" / "project" / "spec" / "snippet.md"

        _snippet._validate_status_and_delivered_by(
            snippet_path,
            {"status": SNIPPET_STATUS_TARGET},
            roadmap_status_map={},
            enforce_delivered_drift=True,
        )

        assert resource_models.get_errors() == [
            {
                "code": _snippet.SNIPPET_STATUS_TARGET_MISSING_DELIVERED_BY,
                "path": str(snippet_path),
            }
        ]

    def test_mixed_status_without_delivered_by_is_rejected(self, tmp_path: Path) -> None:
        resource_models.clear_errors()
        snippet_path = tmp_path / "docs" / "project" / "spec" / "snippet.md"

        _snippet._validate_status_and_delivered_by(
            snippet_path,
            {"status": SNIPPET_STATUS_MIXED},
            roadmap_status_map={},
            enforce_delivered_drift=True,
        )

        assert resource_models.get_errors()[0]["code"] == _snippet.SNIPPET_STATUS_TARGET_MISSING_DELIVERED_BY
        assert resource_models.get_errors()[0]["path"] == str(snippet_path)

    def test_actual_status_with_delivered_by_is_rejected(self, tmp_path: Path) -> None:
        resource_models.clear_errors()
        snippet_path = tmp_path / "docs" / "project" / "spec" / "snippet.md"

        _snippet._validate_status_and_delivered_by(
            snippet_path,
            {"status": SNIPPET_STATUS_ACTUAL, "delivered_by": ["some-slug"]},
            roadmap_status_map={"some-slug": _snippet.ROADMAP_STATUS_ACTIVE},
            enforce_delivered_drift=True,
        )

        assert resource_models.get_errors()[0]["code"] == _snippet.SNIPPET_STATUS_ACTUAL_FORBIDS_DELIVERED_BY
        assert resource_models.get_errors()[0]["path"] == str(snippet_path)

    def test_omitted_status_is_treated_as_actual(self, tmp_path: Path) -> None:
        resource_models.clear_errors()
        snippet_path = tmp_path / "docs" / "project" / "spec" / "snippet.md"

        _snippet._validate_status_and_delivered_by(
            snippet_path,
            {},
            roadmap_status_map={},
            enforce_delivered_drift=True,
        )

        assert resource_models.get_errors() == []

    def test_invalid_status_value_is_rejected(self, tmp_path: Path) -> None:
        resource_models.clear_errors()
        snippet_path = tmp_path / "docs" / "project" / "spec" / "snippet.md"

        _snippet._validate_status_and_delivered_by(
            snippet_path,
            {"status": "pending"},
            roadmap_status_map={},
            enforce_delivered_drift=True,
        )

        assert resource_models.get_errors() == [
            {
                "code": _snippet.SNIPPET_STATUS_INVALID_VALUE,
                "path": str(snippet_path),
                "value": "pending",
            }
        ]

    def test_delivered_by_reference_missing_from_roadmap_is_rejected(self, tmp_path: Path) -> None:
        resource_models.clear_errors()
        snippet_path = tmp_path / "docs" / "project" / "spec" / "snippet.md"

        _snippet._validate_status_and_delivered_by(
            snippet_path,
            {"status": SNIPPET_STATUS_TARGET, "delivered_by": ["gamma"]},
            roadmap_status_map={"alpha": _snippet.ROADMAP_STATUS_ACTIVE, "beta": _snippet.ROADMAP_STATUS_ACTIVE},
            enforce_delivered_drift=True,
        )

        assert resource_models.get_errors() == [
            {
                "code": _snippet.SNIPPET_DELIVERED_BY_UNKNOWN_SLUG,
                "path": str(snippet_path),
                "slug": "gamma",
            }
        ]

    def test_delivered_by_reports_only_unknown_slugs(self, tmp_path: Path) -> None:
        resource_models.clear_errors()
        snippet_path = tmp_path / "docs" / "project" / "spec" / "snippet.md"

        _snippet._validate_status_and_delivered_by(
            snippet_path,
            {"status": SNIPPET_STATUS_TARGET, "delivered_by": ["alpha", "ghost"]},
            roadmap_status_map={"alpha": _snippet.ROADMAP_STATUS_ACTIVE},
            enforce_delivered_drift=True,
        )

        assert resource_models.get_errors() == [
            {
                "code": _snippet.SNIPPET_DELIVERED_BY_UNKNOWN_SLUG,
                "path": str(snippet_path),
                "slug": "ghost",
            }
        ]

    def test_icebox_slugs_are_valid_delivered_by_references(self, tmp_path: Path) -> None:
        resource_models.clear_errors()
        snippet_path = tmp_path / "docs" / "project" / "spec" / "snippet.md"

        _snippet._validate_status_and_delivered_by(
            snippet_path,
            {"status": SNIPPET_STATUS_TARGET, "delivered_by": ["frozen-work"]},
            roadmap_status_map={"frozen-work": _snippet.ROADMAP_STATUS_ICEBOX},
            enforce_delivered_drift=True,
        )

        assert resource_models.get_errors() == []

    def test_target_whose_delivered_by_slugs_all_delivered_fails_drift_rule(self, tmp_path: Path) -> None:
        resource_models.clear_errors()
        snippet_path = tmp_path / "docs" / "project" / "spec" / "snippet.md"

        _snippet._validate_status_and_delivered_by(
            snippet_path,
            {"status": SNIPPET_STATUS_TARGET, "delivered_by": ["work-a", "work-b"]},
            roadmap_status_map={
                "work-a": _snippet.ROADMAP_STATUS_DELIVERED,
                "work-b": _snippet.ROADMAP_STATUS_DELIVERED,
            },
            enforce_delivered_drift=True,
        )

        assert resource_models.get_errors() == [
            {
                "code": _snippet.SNIPPET_STATUS_UNFLIPPED_DRIFT,
                "path": str(snippet_path),
                "delivered_slugs": "work-a,work-b",
            }
        ]

    def test_mixed_whose_delivered_by_slugs_all_delivered_fails_drift_rule(self, tmp_path: Path) -> None:
        resource_models.clear_errors()
        snippet_path = tmp_path / "docs" / "project" / "spec" / "snippet.md"

        _snippet._validate_status_and_delivered_by(
            snippet_path,
            {"status": SNIPPET_STATUS_MIXED, "delivered_by": ["work-a"]},
            roadmap_status_map={"work-a": _snippet.ROADMAP_STATUS_DELIVERED},
            enforce_delivered_drift=True,
        )

        assert resource_models.get_errors()[0]["code"] == _snippet.SNIPPET_STATUS_UNFLIPPED_DRIFT
        assert resource_models.get_errors()[0]["path"] == str(snippet_path)

    def test_target_with_in_flight_slug_passes_drift_rule(self, tmp_path: Path) -> None:
        resource_models.clear_errors()
        snippet_path = tmp_path / "docs" / "project" / "spec" / "snippet.md"

        _snippet._validate_status_and_delivered_by(
            snippet_path,
            {"status": SNIPPET_STATUS_TARGET, "delivered_by": ["work-a", "work-b"]},
            roadmap_status_map={
                "work-a": _snippet.ROADMAP_STATUS_DELIVERED,
                "work-b": _snippet.ROADMAP_STATUS_ACTIVE,
            },
            enforce_delivered_drift=True,
        )

        assert resource_models.get_errors() == []

    def test_drift_rule_can_be_disabled_for_pre_reconcile_validation(self, tmp_path: Path) -> None:
        resource_models.clear_errors()
        snippet_path = tmp_path / "docs" / "project" / "spec" / "snippet.md"

        _snippet._validate_status_and_delivered_by(
            snippet_path,
            {"status": SNIPPET_STATUS_TARGET, "delivered_by": ["work-a"]},
            roadmap_status_map={"work-a": _snippet.ROADMAP_STATUS_DELIVERED},
            enforce_delivered_drift=False,
        )

        assert resource_models.get_errors() == []


class TestRoadmapStatusMap:
    def test_missing_todos_db_returns_empty_status_map(self, tmp_path: Path) -> None:
        assert _snippet.build_roadmap_status_map(tmp_path) == {}

    def test_reads_active_icebox_and_delivered_statuses(self, tmp_path: Path) -> None:
        _write_roadmap_db(
            tmp_path,
            [
                ("alpha", _snippet.ROADMAP_STATUS_ACTIVE),
                ("beta", _snippet.ROADMAP_STATUS_ICEBOX),
                ("gamma", _snippet.ROADMAP_STATUS_DELIVERED),
            ],
        )

        assert _snippet.build_roadmap_status_map(tmp_path) == {
            "alpha": _snippet.ROADMAP_STATUS_ACTIVE,
            "beta": _snippet.ROADMAP_STATUS_ICEBOX,
            "gamma": _snippet.ROADMAP_STATUS_DELIVERED,
        }

    def test_current_roadmap_entry_wins_over_historical_delivery(self, tmp_path: Path) -> None:
        _write_roadmap_db(
            tmp_path,
            [
                ("reused-slug", _snippet.ROADMAP_STATUS_DELIVERED),
                ("reused-slug", _snippet.ROADMAP_STATUS_ACTIVE),
            ],
        )

        assert _snippet.build_roadmap_status_map(tmp_path)["reused-slug"] == _snippet.ROADMAP_STATUS_ACTIVE

    def test_validate_all_snippets_builds_roadmap_status_map_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        resource_models.clear_errors()
        snippets_root = tmp_path / "docs" / "project"
        _write_policy_snippet(snippets_root / "policy", "alpha.md", ["alpha"])
        _write_policy_snippet(snippets_root / "policy", "beta.md", ["beta"])
        calls = 0

        def fake_build_roadmap_status_map(project_root: Path) -> dict[str, str]:
            nonlocal calls
            calls += 1
            assert project_root == tmp_path
            return {
                "alpha": _snippet.ROADMAP_STATUS_ACTIVE,
                "beta": _snippet.ROADMAP_STATUS_ACTIVE,
            }

        monkeypatch.setattr(_snippet, "build_roadmap_status_map", fake_build_roadmap_status_map)

        _snippet.validate_all_snippets(tmp_path)

        assert calls == 1
        assert resource_models.get_errors() == []


class TestThirdPartyValidation:
    def test_accepts_valid_third_party_frontmatter(self, tmp_path: Path) -> None:
        resource_models.clear_errors()
        doc_path = tmp_path / "docs" / "third-party" / "library" / "guide.md"
        doc_path.parent.mkdir(parents=True)
        doc_path.write_text(
            (
                "---\n"
                "id: third-party/library/guide\n"
                "type: third-party\n"
                "scope: project\n"
                "description: Library guide\n"
                "---\n"
                "# Library Guide\n\n"
                "## Sources\n"
                "- https://example.com\n"
            ),
            encoding="utf-8",
        )

        _snippet.validate_snippet(
            doc_path,
            doc_path.read_text(encoding="utf-8"),
            tmp_path,
            domains={"software-development"},
        )

        assert resource_models.get_errors() == []

    def test_reports_all_missing_third_party_frontmatter_fields(self, tmp_path: Path) -> None:
        resource_models.clear_errors()
        doc_path = tmp_path / "docs" / "third-party" / "guide.md"
        doc_path.parent.mkdir(parents=True)
        doc_path.write_text("# Guide\n\n## Sources\n- https://example.com\n", encoding="utf-8")

        _snippet.validate_snippet(
            doc_path,
            doc_path.read_text(encoding="utf-8"),
            tmp_path,
            domains={"software-development"},
        )

        assert [
            (error["code"], error.get("field"))
            for error in resource_models.get_errors()
            if error["code"] == "snippet_missing_frontmatter_field"
        ] == [
            ("snippet_missing_frontmatter_field", "id"),
            ("snippet_missing_frontmatter_field", "type"),
            ("snippet_missing_frontmatter_field", "scope"),
            ("snippet_missing_frontmatter_field", "description"),
        ]

    def test_reports_non_url_source_entries_as_errors(self, tmp_path: Path) -> None:
        resource_models.clear_errors()
        doc_path = tmp_path / "docs" / "third-party" / "guide.md"
        doc_path.parent.mkdir(parents=True)
        doc_path.write_text(
            (
                "---\n"
                "id: third-party/guide\n"
                "type: third-party\n"
                "scope: project\n"
                "description: Guide\n"
                "---\n"
                "# Guide\n\n"
                "## Sources\n"
                "- not-a-url\n"
                "- /context7/library\n"
                "- https://example.com\n"
            ),
            encoding="utf-8",
        )

        _snippet.validate_third_party_docs(tmp_path)

        assert resource_models.get_errors() == [
            {"code": "third_party_source_invalid", "path": str(doc_path), "source": "not-a-url"}
        ]
