"""Tests for snippet status reconciliation."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import frontmatter

from teleclaude import docs_reconcile
from teleclaude.constants import SNIPPET_STATUS_MIXED, SNIPPET_STATUS_TARGET, RoadmapStatus
from teleclaude.resource_validation import _models, _snippet


def _write_snippet(
    project_root: Path,
    relative_path: str,
    *,
    status: str = SNIPPET_STATUS_TARGET,
    delivered_by: list[str],
    body: str = "# Snippet\n\nBody.\n",
) -> Path:
    path = project_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "---\n"
            "id: project/spec/snippet\n"
            "type: spec\n"
            "scope: project\n"
            "description: Snippet\n"
            f"status: {status}\n"
            f"delivered_by: {delivered_by}\n"
            "---\n"
            f"{body}"
        ),
        encoding="utf-8",
    )
    return path


def _metadata(path: Path) -> docs_reconcile.SnippetFrontmatter:
    return cast(docs_reconcile.SnippetFrontmatter, frontmatter.load(path).metadata)


def _frontmatter_line(path: Path, key: str) -> bytes:
    frontmatter_bytes = path.read_bytes().split(b"---\n", 2)[1]
    key_bytes = key.encode()
    for line in frontmatter_bytes.splitlines(keepends=True):
        if line.split(b":", 1)[0] == key_bytes:
            return line
    raise AssertionError(key)


def test_reconcile_flips_fully_delivered_target_to_implicit_actual(tmp_path: Path) -> None:
    snippet_path = _write_snippet(
        tmp_path,
        "docs/project/spec/snippet.md",
        delivered_by=["work-a", "work-b"],
    )

    results = docs_reconcile.reconcile_snippet_status(
        tmp_path,
        {
            "work-a": RoadmapStatus.DELIVERED,
            "work-b": RoadmapStatus.DELIVERED,
        },
    )

    assert results == [
        docs_reconcile.SnippetStatusReconcileResult(
            path=snippet_path,
            removed_slugs=("work-a", "work-b"),
        )
    ]
    assert "status" not in _metadata(snippet_path)
    assert "delivered_by" not in _metadata(snippet_path)


def test_reconcile_flips_fully_delivered_mixed_to_implicit_actual(tmp_path: Path) -> None:
    snippet_path = _write_snippet(
        tmp_path,
        "docs/project/spec/snippet.md",
        status=SNIPPET_STATUS_MIXED,
        delivered_by=["work-a"],
    )

    docs_reconcile.reconcile_snippet_status(
        tmp_path,
        {"work-a": RoadmapStatus.DELIVERED},
    )

    assert "status" not in _metadata(snippet_path)
    assert "delivered_by" not in _metadata(snippet_path)


def test_reconcile_removes_only_delivered_slug_from_partial_snippet(tmp_path: Path) -> None:
    snippet_path = _write_snippet(
        tmp_path,
        "docs/project/spec/snippet.md",
        delivered_by=["work-a", "work-b"],
    )

    docs_reconcile.reconcile_snippet_status(
        tmp_path,
        {
            "work-a": RoadmapStatus.DELIVERED,
            "work-b": RoadmapStatus.ACTIVE,
        },
    )

    metadata = _metadata(snippet_path)
    assert metadata["status"] == SNIPPET_STATUS_TARGET
    assert metadata["delivered_by"] == ["work-b"]


def test_reconcile_preserves_unicode_description_bytes_during_partial_flip(tmp_path: Path) -> None:
    snippet_path = tmp_path / "docs" / "project" / "spec" / "snippet.md"
    snippet_path.parent.mkdir(parents=True, exist_ok=True)
    snippet_path.write_text(
        (
            "---\n"
            "id: project/spec/snippet\n"
            "type: spec\n"
            "scope: project\n"
            "description: v1→v2 migration\n"
            "status: target\n"
            "delivered_by: [work-a, work-b]\n"
            "---\n"
            "# Snippet\n"
        ),
        encoding="utf-8",
    )
    description_before = _frontmatter_line(snippet_path, "description")

    docs_reconcile.reconcile_snippet_status(
        tmp_path,
        {
            "work-a": RoadmapStatus.DELIVERED,
            "work-b": RoadmapStatus.ACTIVE,
        },
    )

    assert _frontmatter_line(snippet_path, "description") == description_before


def test_reconcile_preserves_non_lifecycle_frontmatter_values_during_partial_flip(tmp_path: Path) -> None:
    snippet_path = tmp_path / "docs" / "project" / "spec" / "snippet.md"
    snippet_path.parent.mkdir(parents=True, exist_ok=True)
    snippet_path.write_text(
        (
            "---\n"
            "id: project/spec/snippet\n"
            "type: spec\n"
            "scope: project\n"
            "description: v1→v2 migration\n"
            "applies_to: v2\n"
            "visibility: public\n"
            "activation_trigger: when updating snippet lifecycle metadata\n"
            "status: target\n"
            "delivered_by: [work-a, work-b]\n"
            "---\n"
            "# Snippet\n"
        ),
        encoding="utf-8",
    )
    metadata_before = _metadata(snippet_path)

    docs_reconcile.reconcile_snippet_status(
        tmp_path,
        {
            "work-a": RoadmapStatus.DELIVERED,
            "work-b": RoadmapStatus.ACTIVE,
        },
    )

    metadata_after = _metadata(snippet_path)
    assert metadata_after["description"] == metadata_before["description"]
    assert metadata_after["applies_to"] == metadata_before["applies_to"]
    assert metadata_after["visibility"] == metadata_before["visibility"]
    assert metadata_after["activation_trigger"] == metadata_before["activation_trigger"]


def test_reconcile_preserves_body_bytes_when_flipping_frontmatter(tmp_path: Path) -> None:
    snippet_path = _write_snippet(
        tmp_path,
        "docs/project/spec/snippet.md",
        delivered_by=["work-a"],
        body="# Snippet\n\nBody with trailing newline.\n",
    )
    body_before = snippet_path.read_text(encoding="utf-8").split("---\n", 2)[2]

    docs_reconcile.reconcile_snippet_status(
        tmp_path,
        {"work-a": RoadmapStatus.DELIVERED},
    )

    body_after = snippet_path.read_text(encoding="utf-8").split("---\n", 2)[2]
    assert body_after == body_before


def test_reconcile_is_noop_when_no_slugs_are_delivered(tmp_path: Path) -> None:
    snippet_path = _write_snippet(
        tmp_path,
        "docs/project/spec/snippet.md",
        delivered_by=["work-a", "work-b"],
    )
    before = snippet_path.read_bytes()

    results = docs_reconcile.reconcile_snippet_status(
        tmp_path,
        {
            "work-a": RoadmapStatus.ACTIVE,
            "work-b": RoadmapStatus.ICEBOX,
        },
    )

    assert results == []
    assert snippet_path.read_bytes() == before


def test_reconcile_leaves_snippets_without_delivered_by_unchanged(tmp_path: Path) -> None:
    snippet_path = tmp_path / "docs" / "project" / "spec" / "actual.md"
    snippet_path.parent.mkdir(parents=True, exist_ok=True)
    snippet_path.write_text(
        "---\nid: project/spec/actual\ntype: spec\nscope: project\ndescription: Actual\n---\n# Actual\n",
        encoding="utf-8",
    )
    before = snippet_path.read_bytes()

    results = docs_reconcile.reconcile_snippet_status(
        tmp_path,
        {"work-a": RoadmapStatus.DELIVERED},
    )

    assert results == []
    assert snippet_path.read_bytes() == before


def test_reconcile_is_idempotent_across_runs(tmp_path: Path) -> None:
    _write_snippet(
        tmp_path,
        "docs/project/spec/snippet.md",
        delivered_by=["work-a"],
    )
    roadmap_status_map = {"work-a": RoadmapStatus.DELIVERED}

    first_results = docs_reconcile.reconcile_snippet_status(tmp_path, roadmap_status_map)
    second_results = docs_reconcile.reconcile_snippet_status(tmp_path, roadmap_status_map)

    assert len(first_results) == 1
    assert second_results == []


def test_rewrite_delivered_by_slug_updates_only_lifecycle_frontmatter_refs(tmp_path: Path) -> None:
    snippet_path = tmp_path / "docs" / "project" / "spec" / "snippet.md"
    snippet_path.parent.mkdir(parents=True, exist_ok=True)
    snippet_path.write_text(
        (
            "---\n"
            "id: project/spec/snippet\n"
            "type: spec\n"
            "scope: project\n"
            "description: old-slug is prose here\n"
            "status: target\n"
            "delivered_by: [old-slug, sibling]\n"
            "---\n"
            "# Snippet\n"
            "## What it is\n"
            "Body keeps old-slug as prose.\n"
            "## Canonical fields\n"
            "Fields stay stable.\n"
        ),
        encoding="utf-8",
    )
    description_before = _frontmatter_line(snippet_path, "description")
    body_before = snippet_path.read_bytes().split(b"---\n", 2)[2]

    docs_reconcile.rewrite_delivered_by_slug(tmp_path, "old-slug", "new-slug")

    metadata = _metadata(snippet_path)
    assert metadata["delivered_by"] == ["new-slug", "sibling"]
    assert _frontmatter_line(snippet_path, "description") == description_before
    assert snippet_path.read_bytes().split(b"---\n", 2)[2] == body_before


def test_rewrite_delivered_by_slug_leaves_snippets_valid_for_new_roadmap_slug(tmp_path: Path) -> None:
    _write_snippet(
        tmp_path,
        "docs/project/spec/snippet.md",
        delivered_by=["old-slug"],
        body=(
            "# Snippet\n"
            "## What it is\n"
            "Rename contract.\n"
            "## Canonical fields\n"
            "Delivery slug references are lifecycle metadata.\n"
        ),
    )

    docs_reconcile.rewrite_delivered_by_slug(tmp_path, "old-slug", "new-slug")
    _models.clear_errors()

    _snippet.validate_all_snippets(
        tmp_path,
        roadmap_status_map={"new-slug": _snippet.ROADMAP_STATUS_ACTIVE},
    )

    findings = _models.get_errors()
    assert _snippet.SNIPPET_DELIVERED_BY_UNKNOWN_SLUG not in {finding["code"] for finding in findings}
