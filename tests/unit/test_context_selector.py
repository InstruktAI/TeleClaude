"""Characterization tests for teleclaude.context_selector."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import teleclaude.context_selector as context_selector


def test_resolve_inline_refs_preserves_frontmatter_and_expands_relative_paths(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    snippet_path = project_root / "docs" / "project" / "guide.md"
    snippet_path.parent.mkdir(parents=True)
    content = "---\ntitle: Guide\n---\nSee @related.md and @docs/shared/reference.md.\n"

    resolved = context_selector._resolve_inline_refs(
        content,
        snippet_path=snippet_path,
        root_path=project_root,
    )

    assert resolved.startswith("---\ntitle: Guide\n---\n")
    assert f"@{(snippet_path.parent / 'related.md').resolve()}" in resolved
    assert f"@{(project_root / 'docs' / 'shared' / 'reference.md').resolve()}" in resolved


def test_load_index_rewrites_project_prefix_and_defaults_visibility(tmp_path: Path) -> None:
    docs_root = tmp_path / "docs"
    snippet_path = docs_root / "spec" / "overview.md"
    snippet_path.parent.mkdir(parents=True)
    snippet_path.write_text("# Overview\n", encoding="utf-8")
    index_path = tmp_path / "index.yaml"
    index_path.write_text(
        yaml.safe_dump(
            {
                "project_root": str(tmp_path),
                "snippets": [
                    {
                        "id": "project/spec/overview",
                        "description": "Overview",
                        "type": "spec",
                        "scope": "project",
                        "path": "docs/spec/overview.md",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    entries = context_selector._load_index(
        index_path,
        source_project="Alpha",
        rewrite_project_prefix=True,
        project_root=tmp_path,
    )

    assert len(entries) == 1
    assert entries[0].snippet_id == "alpha/spec/overview"
    assert entries[0].visibility == context_selector.SNIPPET_VISIBILITY_INTERNAL
    assert entries[0].project_root == tmp_path


def test_build_context_output_emits_requested_public_body_and_denied_private_snippet(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "workspace" / "alpha"
    project_docs = project_root / "docs" / "project"
    public_path = project_docs / "public.md"
    private_path = project_docs / "private.md"
    public_path.parent.mkdir(parents=True)
    public_path.write_text(
        (
            "---\n"
            "id: project/spec/public\n"
            "description: Public snippet\n"
            "type: spec\n"
            "scope: project\n"
            "visibility: public\n"
            "---\n"
            "# Public\n"
            "Visible body.\n"
        ),
        encoding="utf-8",
    )
    private_path.write_text(
        (
            "---\n"
            "id: project/spec/private\n"
            "description: Private snippet\n"
            "type: spec\n"
            "scope: project\n"
            "visibility: internal\n"
            "---\n"
            "# Private\n"
            "Hidden body.\n"
        ),
        encoding="utf-8",
    )
    (project_docs / "index.yaml").write_text(
        yaml.safe_dump(
            {
                "project_root": str(project_root),
                "snippets": [
                    {
                        "id": "project/spec/public",
                        "description": "Public snippet",
                        "type": "spec",
                        "scope": "project",
                        "path": "docs/project/public.md",
                        "visibility": "public",
                    },
                    {
                        "id": "project/spec/private",
                        "description": "Private snippet",
                        "type": "spec",
                        "scope": "project",
                        "path": "docs/project/private.md",
                        "visibility": "internal",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    global_docs = tmp_path / "global-home" / "docs"
    global_docs.mkdir(parents=True)
    (global_docs / "index.yaml").write_text(
        yaml.safe_dump({"project_root": str(global_docs.parent), "snippets": []}),
        encoding="utf-8",
    )

    monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_docs)
    monkeypatch.setattr(context_selector, "_load_manifest_by_name", lambda: {})
    monkeypatch.setattr(context_selector, "get_project_name", lambda _root: "Alpha")

    output = context_selector.build_context_output(
        areas=[],
        project_root=project_root,
        snippet_ids=["project/spec/public", "project/spec/private"],
        effective_human_role="customer",
    )

    assert "# Requested: project/spec/public, project/spec/private" in output
    assert "Visible body." in output
    assert "Hidden body." not in output
    assert "id: project/spec/private" in output
    assert "access: denied" in output
