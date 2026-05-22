"""Characterization tests for teleclaude.project_setup.enrichment."""

from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest

import teleclaude.project_setup.enrichment as enrichment

FLAT_SNIPPET_ID = "project/design/overview"
DOMAIN_SPEC_SNIPPET_ID = "project/spec/domain/workflow"
FEATURE_SPEC_SNIPPET_ID = "project/spec/feature/workflow/todo-management"
UNSAFE_DOMAIN_SPEC_SNIPPET_ID = "project/spec/domain/../workflow"
UNKNOWN_NESTED_SPEC_SNIPPET_ID = "project/spec/unknown/workflow"


def test_write_snippet_writes_frontmatter_defaults(tmp_path: Path) -> None:
    snippet_path = enrichment.write_snippet(
        tmp_path,
        FLAT_SNIPPET_ID,
        "Generated body",
        {},
    )

    post = frontmatter.load(snippet_path)
    assert snippet_path == tmp_path / "docs" / "project" / "design" / "overview.md"
    assert post.metadata["id"] == FLAT_SNIPPET_ID
    assert post.metadata["type"] == "design"
    assert post.metadata["scope"] == "project"
    assert post.metadata["status"] == "actual"
    assert post.metadata["visibility"] == "internal"
    assert post.metadata["generated_by"] == "telec-init"
    assert post.metadata["generated_at"] != ""
    assert post.content.strip() == "Generated body"


def test_write_snippet_honors_explicit_public_visibility(tmp_path: Path) -> None:
    snippet_path = enrichment.write_snippet(
        tmp_path,
        FLAT_SNIPPET_ID,
        "Generated body",
        {"visibility": "public"},
    )

    post = frontmatter.load(snippet_path)
    assert post.metadata["visibility"] == "public"


def test_merge_snippet_preserves_human_section_after_marker() -> None:
    merged = enrichment.merge_snippet(
        "old generated\n\n<!-- human -->\nKeep this\n",
        "new generated\n",
    )

    assert merged == "new generated\n\n<!-- human -->\nKeep this\n"


def test_refresh_snippet_returns_unchanged_when_generated_and_human_content_match(tmp_path: Path) -> None:
    snippet_path = enrichment.write_snippet(
        tmp_path,
        FLAT_SNIPPET_ID,
        "Stable body",
        {"generated_at": "2024-01-01T00:00:00+00:00"},
    )
    existing = snippet_path.read_text(encoding="utf-8") + f"\n{enrichment.HUMAN_MARKER}\nKeep this\n"
    snippet_path.write_text(existing, encoding="utf-8")

    result = enrichment.refresh_snippet(tmp_path, FLAT_SNIPPET_ID, "Stable body", {})

    assert result == "unchanged"
    assert snippet_path.read_text(encoding="utf-8") == existing


def test_refresh_snippet_updates_generated_portion_but_keeps_human_content(tmp_path: Path) -> None:
    snippet_path = enrichment.write_snippet(
        tmp_path,
        FLAT_SNIPPET_ID,
        "Old body",
        {"generated_at": "2024-01-01T00:00:00+00:00"},
    )
    snippet_path.write_text(
        snippet_path.read_text(encoding="utf-8") + f"\n{enrichment.HUMAN_MARKER}\nKeep this\n",
        encoding="utf-8",
    )

    result = enrichment.refresh_snippet(
        tmp_path,
        FLAT_SNIPPET_ID,
        "New body",
        {"description": "Updated description"},
    )

    post = frontmatter.loads(snippet_path.read_text(encoding="utf-8"))
    assert result == "updated"
    assert post.metadata["description"] == "Updated description"
    assert "New body" in post.content
    assert "Keep this" in post.content


def test_read_existing_snippets_and_metadata_round_trip(tmp_path: Path) -> None:
    generated_path = enrichment.write_snippet(
        tmp_path,
        FLAT_SNIPPET_ID,
        "Body",
        {},
    )
    manual_path = tmp_path / "docs" / "project" / "design" / "manual.md"
    manual_path.parent.mkdir(parents=True, exist_ok=True)
    manual_path.write_text("# Manual\n", encoding="utf-8")

    snippets = enrichment.read_existing_snippets(tmp_path)
    enrichment.write_metadata(
        tmp_path,
        files_analyzed=3,
        snippets_generated=["project/design/beta", "project/design/alpha"],
        snippets_preserved=["project/design/manual"],
    )
    metadata = enrichment.read_metadata(tmp_path)

    assert snippets == {FLAT_SNIPPET_ID: generated_path}
    assert metadata is not None
    assert metadata["files_analyzed"] == 3
    assert metadata["snippets_generated"] == ["project/design/alpha", "project/design/beta"]
    assert metadata["snippets_preserved"] == ["project/design/manual"]


def test_nested_domain_spec_id_maps_to_project_spec_domain_path(tmp_path: Path) -> None:
    snippet_path = enrichment.write_snippet(
        tmp_path,
        DOMAIN_SPEC_SNIPPET_ID,
        "Generated body",
        {},
    )

    post = frontmatter.load(snippet_path)
    assert snippet_path == tmp_path / "docs" / "project" / "spec" / "domain" / "workflow.md"
    assert post.metadata["id"] == DOMAIN_SPEC_SNIPPET_ID
    assert post.metadata["type"] == "spec"
    assert post.metadata["status"] == "actual"


def test_nested_feature_spec_id_maps_to_project_spec_feature_path(tmp_path: Path) -> None:
    snippet_path = enrichment.write_snippet(
        tmp_path,
        FEATURE_SPEC_SNIPPET_ID,
        "Generated body",
        {},
    )

    post = frontmatter.load(snippet_path)
    assert snippet_path == tmp_path / "docs" / "project" / "spec" / "feature" / "workflow" / "todo-management.md"
    assert post.metadata["id"] == FEATURE_SPEC_SNIPPET_ID
    assert post.metadata["type"] == "spec"
    assert post.metadata["status"] == "actual"


def test_nested_snippet_id_rejects_path_traversal() -> None:
    assert enrichment.validate_snippet_id(UNSAFE_DOMAIN_SPEC_SNIPPET_ID) is False

    with pytest.raises(ValueError):
        enrichment.snippet_id_to_path(Path.cwd(), UNSAFE_DOMAIN_SPEC_SNIPPET_ID)


def test_nested_snippet_id_rejects_unknown_spec_family() -> None:
    assert enrichment.validate_snippet_id(UNKNOWN_NESTED_SPEC_SNIPPET_ID) is False

    with pytest.raises(ValueError):
        enrichment.snippet_id_to_path(Path.cwd(), UNKNOWN_NESTED_SPEC_SNIPPET_ID)


def test_refresh_nested_snippet_keeps_human_content(tmp_path: Path) -> None:
    snippet_path = enrichment.write_snippet(
        tmp_path,
        DOMAIN_SPEC_SNIPPET_ID,
        "Old body",
        {"generated_at": "2024-01-01T00:00:00+00:00"},
    )
    existing = snippet_path.read_text(encoding="utf-8") + f"\n{enrichment.HUMAN_MARKER}\nKeep this\n"
    snippet_path.write_text(existing, encoding="utf-8")

    result = enrichment.refresh_snippet(tmp_path, DOMAIN_SPEC_SNIPPET_ID, "New body", {})

    post = frontmatter.loads(snippet_path.read_text(encoding="utf-8"))
    assert result == "updated"
    assert "New body" in post.content
    assert "Keep this" in post.content
