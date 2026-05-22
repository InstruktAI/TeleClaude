"""Characterization tests for teleclaude.resource_validation._snippet."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude import paths as tc_paths
from teleclaude.constants import (
    SNIPPET_STATUS_ACTUAL,
    SNIPPET_STATUS_MIXED,
    SNIPPET_STATUS_TARGET,
    RoadmapStatus,
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


# guard: loose-dict-func - validation error payloads carry a variable per-code field set
def _normalize_error_paths(errors: list[dict[str, object]], root: Path) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for error in errors:
        normalized.append(
            {key: value.replace(str(root), "TMP") if isinstance(value, str) else value for key, value in error.items()}
        )
    return normalized


class TestIterInlineRefs:
    def test_skips_code_fence_contents(self, snapshot: SnapshotAssertion) -> None:
        refs = _snippet.iter_inline_refs(
            [
                "@docs/project/policy/one.md",
                "```md",
                "@docs/project/policy/two.md",
                "```",
                "- @docs/project/policy/three.md",
            ]
        )

        assert refs == snapshot


class TestCollectInlineRefErrors:
    def test_reports_missing_and_non_file_targets(self, tmp_path: Path, snapshot: SnapshotAssertion) -> None:
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

        assert sorted(error["code"] for error in errors) == snapshot


class TestSeeAlsoValidation:
    def test_global_docs_require_global_prefix(self, tmp_path: Path, snapshot: SnapshotAssertion) -> None:
        resource_models.clear_errors()
        path = tmp_path / "docs" / "global" / "general" / "policy" / "doc.md"
        path.parent.mkdir(parents=True)
        path.write_text("body", encoding="utf-8")

        _snippet._validate_see_also_ref("docs/project/policy/other.md", path, tmp_path)

        assert _normalize_error_paths(resource_models.get_errors(), tmp_path) == snapshot

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
    def test_target_status_without_delivered_by_is_rejected(self, tmp_path: Path, snapshot: SnapshotAssertion) -> None:
        resource_models.clear_errors()
        snippet_path = tmp_path / "docs" / "project" / "spec" / "snippet.md"

        _snippet._validate_status_and_delivered_by(
            snippet_path,
            {"status": SNIPPET_STATUS_TARGET},
        )

        assert _normalize_error_paths(resource_models.get_errors(), tmp_path) == snapshot

    def test_mixed_status_without_delivered_by_is_rejected(self, tmp_path: Path, snapshot: SnapshotAssertion) -> None:
        resource_models.clear_errors()
        snippet_path = tmp_path / "docs" / "project" / "spec" / "snippet.md"

        _snippet._validate_status_and_delivered_by(
            snippet_path,
            {"status": SNIPPET_STATUS_MIXED},
        )

        assert _normalize_error_paths(resource_models.get_errors(), tmp_path) == snapshot

    def test_actual_status_with_delivered_by_is_rejected(self, tmp_path: Path, snapshot: SnapshotAssertion) -> None:
        resource_models.clear_errors()
        snippet_path = tmp_path / "docs" / "project" / "spec" / "snippet.md"

        _snippet._validate_status_and_delivered_by(
            snippet_path,
            {"status": SNIPPET_STATUS_ACTUAL, "delivered_by": ["some-slug"]},
        )

        assert _normalize_error_paths(resource_models.get_errors(), tmp_path) == snapshot

    def test_omitted_status_is_treated_as_actual(self, tmp_path: Path) -> None:
        resource_models.clear_errors()
        snippet_path = tmp_path / "docs" / "project" / "spec" / "snippet.md"

        _snippet._validate_status_and_delivered_by(
            snippet_path,
            {},
        )

        assert resource_models.get_errors() == []

    def test_invalid_status_value_is_rejected(self, tmp_path: Path, snapshot: SnapshotAssertion) -> None:
        resource_models.clear_errors()
        snippet_path = tmp_path / "docs" / "project" / "spec" / "snippet.md"

        _snippet._validate_status_and_delivered_by(
            snippet_path,
            {"status": "pending"},
        )

        assert _normalize_error_paths(resource_models.get_errors(), tmp_path) == snapshot

    def test_unknown_delivered_by_slug_is_accepted(self, tmp_path: Path) -> None:
        resource_models.clear_errors()
        snippet_path = tmp_path / "docs" / "project" / "spec" / "snippet.md"

        _snippet._validate_status_and_delivered_by(
            snippet_path,
            {"status": SNIPPET_STATUS_TARGET, "delivered_by": ["gamma"]},
        )

        assert resource_models.get_errors() == []

    def test_all_delivered_target_snippet_is_accepted(self, tmp_path: Path) -> None:
        resource_models.clear_errors()
        snippet_path = tmp_path / "docs" / "project" / "spec" / "snippet.md"

        _snippet._validate_status_and_delivered_by(
            snippet_path,
            {"status": SNIPPET_STATUS_TARGET, "delivered_by": ["work-a", "work-b"]},
        )

        assert resource_models.get_errors() == []

    def test_all_delivered_mixed_snippet_is_accepted(self, tmp_path: Path) -> None:
        resource_models.clear_errors()
        snippet_path = tmp_path / "docs" / "project" / "spec" / "snippet.md"

        _snippet._validate_status_and_delivered_by(
            snippet_path,
            {"status": SNIPPET_STATUS_MIXED, "delivered_by": ["work-a"]},
        )

        assert resource_models.get_errors() == []


class TestRoadmapStatusMap:
    def test_missing_todos_db_returns_empty_status_map(self, tmp_path: Path) -> None:
        assert _snippet.build_roadmap_status_map(tmp_path) == {}

    def test_reads_active_icebox_and_delivered_statuses(self, tmp_path: Path, snapshot: SnapshotAssertion) -> None:
        _write_roadmap_db(
            tmp_path,
            [
                ("alpha", RoadmapStatus.ACTIVE),
                ("beta", RoadmapStatus.ICEBOX),
                ("gamma", RoadmapStatus.DELIVERED),
                ("delta", RoadmapStatus.REMOVED),
            ],
        )

        assert _snippet.build_roadmap_status_map(tmp_path) == snapshot

    def test_current_roadmap_entry_wins_over_historical_delivery(self, tmp_path: Path) -> None:
        _write_roadmap_db(
            tmp_path,
            [
                ("reused-slug", RoadmapStatus.DELIVERED),
                ("reused-slug", RoadmapStatus.ACTIVE),
            ],
        )

        assert _snippet.build_roadmap_status_map(tmp_path)["reused-slug"] == RoadmapStatus.ACTIVE

    def test_live_status_wins_over_historical_removed_entry(self, tmp_path: Path) -> None:
        _write_roadmap_db(
            tmp_path,
            [
                ("reused-slug", RoadmapStatus.REMOVED),
                ("reused-slug", RoadmapStatus.ICEBOX),
            ],
        )

        assert _snippet.build_roadmap_status_map(tmp_path)["reused-slug"] == RoadmapStatus.ICEBOX

    def test_delivered_status_wins_over_historical_removed_entry(self, tmp_path: Path) -> None:
        _write_roadmap_db(
            tmp_path,
            [
                ("reused-slug", RoadmapStatus.REMOVED),
                ("reused-slug", RoadmapStatus.DELIVERED),
            ],
        )

        assert _snippet.build_roadmap_status_map(tmp_path)["reused-slug"] == RoadmapStatus.DELIVERED


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

    def test_reports_all_missing_third_party_frontmatter_fields(
        self, tmp_path: Path, snapshot: SnapshotAssertion
    ) -> None:
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

        assert _normalize_error_paths(resource_models.get_errors(), tmp_path) == snapshot

    def test_reports_non_url_source_entries_as_errors(self, tmp_path: Path, snapshot: SnapshotAssertion) -> None:
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

        assert _normalize_error_paths(resource_models.get_errors(), tmp_path) == snapshot


# ---------------------------------------------------------------------------
# _validate_baseline_dedup — injecting procedures must not re-include baseline
# ---------------------------------------------------------------------------

_DEDUP_VIOLATION = "baseline_dedup_violation"


def _dedup_snippet(path: Path, snippet_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nid: {snippet_id}\ntype: policy\ndomain: sd\nscope: domain\n"
        f"description: x\nvisibility: public\n---\n# {snippet_id}\n",
        encoding="utf-8",
    )


def _dedup_injecting_procedure(root: Path, *, required_read: str) -> None:
    path = root / "docs/global/sd/procedure/build.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\nid: sd/procedure/build\ntype: procedure\ndomain: sd\nscope: domain\n"
        "description: x\nvisibility: public\nneeds_domain_baseline: true\n---\n"
        f"# Build\n\n## Required reads\n\n- @{required_read}\n",
        encoding="utf-8",
    )


def _dedup_baseline(root: Path, *refs: str) -> None:
    path = root / "docs/global/sd/baseline.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"@{ref}\n" for ref in refs), encoding="utf-8")


def _dedup_violations() -> int:
    return sum(1 for e in resource_models.get_errors() if e.get("code") == _DEDUP_VIOLATION)


def test_baseline_dedup_flags_required_read_already_in_baseline(tmp_path: Path) -> None:
    """An injecting procedure that re-reads a baseline snippet is a violation."""
    _dedup_snippet(tmp_path / "docs/global/sd/policy/commits.md", "sd/policy/commits")
    _dedup_baseline(tmp_path, "docs/global/sd/policy/commits.md")
    _dedup_injecting_procedure(tmp_path, required_read="docs/global/sd/policy/commits.md")

    resource_models.clear_errors()
    _snippet._validate_baseline_dedup(tmp_path)

    assert _dedup_violations() == 1


def test_baseline_dedup_flags_transitively_through_nested_procedure(tmp_path: Path) -> None:
    """A baseline snippet reached through a chained procedure is still flagged."""
    _dedup_snippet(tmp_path / "docs/global/sd/policy/commits.md", "sd/policy/commits")
    nested = tmp_path / "docs/global/sd/procedure/review.md"
    nested.parent.mkdir(parents=True, exist_ok=True)
    nested.write_text(
        "---\nid: sd/procedure/review\ntype: procedure\ndomain: sd\nscope: domain\n"
        "description: x\nvisibility: public\n---\n# Review\n\n## Required reads\n\n"
        "- @docs/global/sd/policy/commits.md\n",
        encoding="utf-8",
    )
    _dedup_baseline(tmp_path, "docs/global/sd/policy/commits.md")
    _dedup_injecting_procedure(tmp_path, required_read="docs/global/sd/procedure/review.md")

    resource_models.clear_errors()
    _snippet._validate_baseline_dedup(tmp_path)

    assert _dedup_violations() == 1


def test_baseline_dedup_passes_when_required_read_not_in_baseline(tmp_path: Path) -> None:
    """Referencing a non-baseline snippet is allowed."""
    _dedup_snippet(tmp_path / "docs/global/sd/policy/commits.md", "sd/policy/commits")
    _dedup_snippet(tmp_path / "docs/global/sd/concept/role.md", "sd/concept/role")
    _dedup_baseline(tmp_path, "docs/global/sd/policy/commits.md")
    _dedup_injecting_procedure(tmp_path, required_read="docs/global/sd/concept/role.md")

    resource_models.clear_errors()
    _snippet._validate_baseline_dedup(tmp_path)

    assert _dedup_violations() == 0


def test_baseline_dedup_ignores_non_injecting_procedures(tmp_path: Path) -> None:
    """A procedure without needs_domain_baseline may reference baseline snippets freely."""
    _dedup_snippet(tmp_path / "docs/global/sd/policy/commits.md", "sd/policy/commits")
    _dedup_baseline(tmp_path, "docs/global/sd/policy/commits.md")
    path = tmp_path / "docs/global/sd/procedure/plain.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\nid: sd/procedure/plain\ntype: procedure\ndomain: sd\nscope: domain\n"
        "description: x\nvisibility: public\n---\n# Plain\n\n## Required reads\n\n"
        "- @docs/global/sd/policy/commits.md\n",
        encoding="utf-8",
    )

    resource_models.clear_errors()
    _snippet._validate_baseline_dedup(tmp_path)

    assert _dedup_violations() == 0
