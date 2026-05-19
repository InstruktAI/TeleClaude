"""Characterization tests for teleclaude.context_selector."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import teleclaude.context_selector as context_selector
from teleclaude.constants import (
    DOMAIN_SCOPES,
    SNIPPET_STATUS_MIXED,
    SNIPPET_STATUS_TARGET,
    TAXONOMY_TYPES,
)


def _write_empty_global_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    global_docs = tmp_path / "global-home" / "docs"
    global_docs.mkdir(parents=True, exist_ok=True)
    (global_docs / "index.yaml").write_text(
        yaml.safe_dump({"project_root": str(global_docs.parent), "snippets": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_docs)
    return global_docs


def _patch_project_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        context_selector,
        "_load_manifest_by_name",
        lambda: {},  # pyright: ignore[reportUnknownLambdaType]
    )
    monkeypatch.setattr(
        context_selector,
        "get_project_slug",
        lambda _root: "alpha",  # pyright: ignore[reportUnknownLambdaType]
    )


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

    _patch_project_slug(monkeypatch)

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


def test_phase1_header_includes_dynamic_filter_enums() -> None:
    output = context_selector._build_phase1_output(
        [],
        [],
        areas=[],
        global_snippets_root=Path("/tmp/global-docs"),
        test_agent=None,
        test_mode=None,
        test_request=None,
        test_csv_path=None,
    )
    expected_areas = "|".join(TAXONOMY_TYPES)
    expected_domains = "|".join(DOMAIN_SCOPES)
    assert f"--areas <{expected_areas}>" in output
    assert f"--domains <{expected_domains}>" in output


def test_include_snippet_unauthed_sees_only_public(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "workspace" / "alpha"
    project_docs = project_root / "docs" / "project"
    project_docs.mkdir(parents=True)
    (project_docs / "index.yaml").write_text(
        yaml.safe_dump(
            {
                "project_root": str(project_root),
                "snippets": [
                    {
                        "id": "project/spec/internal-thing",
                        "description": "Internal project snippet",
                        "type": "spec",
                        "scope": "project",
                        "path": "docs/project/internal-thing.md",
                        "visibility": "internal",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    global_root = tmp_path / "global-home"
    global_docs = global_root / "docs"
    (global_docs / "general" / "policy").mkdir(parents=True)
    (global_docs / "software-development" / "policy").mkdir(parents=True)
    (global_docs / "index.yaml").write_text(
        yaml.safe_dump(
            {
                "project_root": str(global_root),
                "snippets": [
                    {
                        "id": "general/policy/public-thing",
                        "description": "Public global snippet",
                        "type": "policy",
                        "scope": "global",
                        "path": "docs/general/policy/public-thing.md",
                        "visibility": "public",
                    },
                    {
                        "id": "general/policy/internal-thing",
                        "description": "Internal global snippet",
                        "type": "policy",
                        "scope": "global",
                        "path": "docs/general/policy/internal-thing.md",
                        "visibility": "internal",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_docs)
    monkeypatch.setattr(
        context_selector,
        "_load_manifest_by_name",
        lambda: {},  # pyright: ignore[reportUnknownLambdaType]
    )
    monkeypatch.setattr(
        context_selector,
        "get_project_slug",
        lambda _: "alpha",  # pyright: ignore[reportUnknownLambdaType]
    )

    output = context_selector.build_context_output(
        areas=[],
        project_root=project_root,
        snippet_ids=None,
        effective_human_role=None,
    )

    assert "general/policy/public-thing" in output
    assert "general/policy/internal-thing" not in output
    assert "project/spec/internal-thing" not in output


def test_build_context_output_filters_phase1_by_target_slug(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context_selector._index_cache.clear()
    project_root = tmp_path / "workspace" / "alpha"
    project_docs = project_root / "docs" / "project"
    project_docs.mkdir(parents=True, exist_ok=True)
    (project_docs / "index.yaml").write_text(
        yaml.safe_dump(
            {
                "project_root": str(project_root),
                "snippets": [
                    {
                        "id": "project/spec/a",
                        "description": "A",
                        "type": "spec",
                        "scope": "project",
                        "path": "docs/project/a.md",
                        "status": SNIPPET_STATUS_TARGET,
                        "delivered_by": ["v2-knowledge"],
                    },
                    {
                        "id": "project/spec/b",
                        "description": "B",
                        "type": "spec",
                        "scope": "project",
                        "path": "docs/project/b.md",
                        "status": SNIPPET_STATUS_TARGET,
                        "delivered_by": ["v2-knowledge", "snippet-status-framework"],
                    },
                    {
                        "id": "project/spec/c",
                        "description": "C",
                        "type": "spec",
                        "scope": "project",
                        "path": "docs/project/c.md",
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    _write_empty_global_index(tmp_path, monkeypatch)
    _patch_project_slug(monkeypatch)

    output = context_selector.build_context_output(
        areas=[],
        project_root=project_root,
        effective_human_role="admin",
        target_slug="v2-knowledge",
    )

    assert "project/spec/a" in output
    assert "project/spec/b" in output
    assert "project/spec/c" not in output


def test_build_context_output_prefixes_non_actual_snippets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context_selector._index_cache.clear()
    project_root = tmp_path / "workspace" / "alpha"
    project_docs = project_root / "docs" / "project"
    project_docs.mkdir(parents=True, exist_ok=True)
    (project_docs / "index.yaml").write_text(
        yaml.safe_dump(
            {
                "project_root": str(project_root),
                "snippets": [
                    {
                        "id": "project/spec/actual",
                        "description": "Actual",
                        "type": "spec",
                        "scope": "project",
                        "path": "docs/project/actual.md",
                    },
                    {
                        "id": "project/spec/mixed",
                        "description": "Mixed",
                        "type": "spec",
                        "scope": "project",
                        "path": "docs/project/mixed.md",
                        "status": SNIPPET_STATUS_MIXED,
                        "delivered_by": ["work-b"],
                    },
                    {
                        "id": "project/spec/target",
                        "description": "Target",
                        "type": "spec",
                        "scope": "project",
                        "path": "docs/project/target.md",
                        "status": SNIPPET_STATUS_TARGET,
                        "delivered_by": ["s1", "s2", "s3", "s4", "s5"],
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    _write_empty_global_index(tmp_path, monkeypatch)
    _patch_project_slug(monkeypatch)

    output = context_selector.build_context_output(
        areas=[],
        project_root=project_root,
        effective_human_role="admin",
    )

    assert "project/spec/actual: Actual" in output
    assert "[mixed → work-b] project/spec/mixed: Mixed" in output
    assert "[target → s1, s2, s3 +2 more] project/spec/target: Target" in output
