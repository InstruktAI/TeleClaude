"""Unit tests for context_selector.build_context_output."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
import yaml
from typing_extensions import TypedDict

from teleclaude import context_selector
from teleclaude.project_manifest import ProjectManifestEntry


class SnippetPayload(TypedDict, total=False):
    id: str
    description: str
    type: str
    scope: str
    path: str
    visibility: str
    source_project: str


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_index(index_path: Path, project_root: Path, snippets: list[SnippetPayload]) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "project_root": str(project_root),
        "snippets": snippets,
    }
    index_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_phase2_returns_snippet_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """build_context_output with snippet_ids returns snippet content."""
    project_root = tmp_path / "project"
    global_root = tmp_path / "global"
    global_snippets_root = global_root / "agents" / "docs"

    base_path = project_root / "docs" / "software-development" / "standards" / "base.md"
    child_path = project_root / "docs" / "software-development" / "concepts" / "role.md"

    _write(
        base_path,
        "---\nid: software-development/standards/base\ntype: policy\n"
        "scope: project\ndescription: Base standard\nvisibility: public\n---\n\nBase content.\n",
    )
    _write(
        child_path,
        "---\nid: software-development/concepts/role\ntype: concept\n"
        "scope: project\ndescription: Role description\nvisibility: public\n---\n\n"
        f"## Required reads\n\n- @{base_path}\n\n## Overview\n\nRole content.\n",
    )

    _write_index(
        project_root / "docs" / "project" / "index.yaml",
        project_root,
        [
            {
                "id": "software-development/standards/base",
                "description": "Base standard",
                "type": "policy",
                "scope": "project",
                "path": "docs/software-development/standards/base.md",
                "visibility": "public",
            },
            {
                "id": "software-development/concepts/role",
                "description": "Role description",
                "type": "concept",
                "scope": "project",
                "path": "docs/software-development/concepts/role.md",
                "visibility": "public",
            },
        ],
    )
    _write_index(global_snippets_root / "index.yaml", global_root, [])

    monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_snippets_root)

    output = context_selector.build_context_output(
        snippet_ids=["software-development/concepts/role"],
        areas=["concept"],
        project_root=project_root,
        caller_role="admin",
    )

    assert "software-development/concepts/role" in output
    assert "Role content." in output
    assert "domain: software-development" in output
    assert "software-development/standards/base" in output
    assert "Base content." in output


def test_phase2_invalid_ids_returns_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_root = tmp_path / "project"
    global_root = tmp_path / "global"
    global_snippets_root = global_root / "agents" / "docs"

    _write_index(project_root / "docs" / "project" / "index.yaml", project_root, [])
    _write_index(global_snippets_root / "index.yaml", global_root, [])

    monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_snippets_root)

    output = context_selector.build_context_output(
        snippet_ids=["nonexistent/snippet"],
        areas=[],
        project_root=project_root,
    )

    assert output.startswith("ERROR:")
    assert "nonexistent/snippet" in output


def test_phase1_returns_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_root = tmp_path / "project"
    global_root = tmp_path / "global"
    global_snippets_root = global_root / "agents" / "docs"

    _write(
        project_root / "docs" / "test" / "base.md",
        "---\nid: test/base\ntype: policy\nscope: project\ndescription: A base snippet\nvisibility: public\n---\n\nContent.\n",
    )

    _write_index(
        project_root / "docs" / "project" / "index.yaml",
        project_root,
        [
            {
                "id": "test/base",
                "description": "A base snippet",
                "type": "policy",
                "scope": "project",
                "path": "docs/test/base.md",
                "visibility": "public",
            }
        ],
    )
    _write_index(global_snippets_root / "index.yaml", global_root, [])

    monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_snippets_root)

    output = context_selector.build_context_output(
        snippet_ids=None,
        areas=["policy"],
        project_root=project_root,
        caller_role="admin",
    )

    assert "PHASE 1" in output
    assert "test/base" in output
    assert "A base snippet" in output


def test_list_projects_returns_manifest_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ = tmp_path
    monkeypatch.setattr(
        context_selector,
        "load_manifest",
        lambda: [
            ProjectManifestEntry(
                name="TeleClaude",
                description="Core docs",
                index_path="/tmp/teleclaude/index.yaml",
                project_root="/tmp/teleclaude",
            ),
            ProjectManifestEntry(
                name="Itsup",
                description="Support docs",
                index_path="/tmp/itsup/index.yaml",
                project_root="/tmp/itsup",
            ),
        ],
    )

    output = context_selector.build_context_output(
        areas=[],
        project_root=Path("/tmp/project"),
        list_projects=True,
    )

    assert "PHASE 0" in output
    assert "teleclaude: Core docs" in output
    assert "itsup: Support docs" in output


def test_projects_filter_loads_selected_project_and_rewrites_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current_root = tmp_path / "current"
    current_root.mkdir(parents=True, exist_ok=True)

    global_root = tmp_path / "global"
    global_snippets_root = global_root / "agents" / "docs"
    _write_index(global_snippets_root / "index.yaml", global_root, [])
    monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_snippets_root)

    teleclaude_root = tmp_path / "teleclaude"
    teleclaude_doc = teleclaude_root / "docs" / "project" / "design" / "architecture.md"
    _write(
        teleclaude_doc,
        "---\nid: project/design/architecture\ntype: design\nscope: project\n"
        "description: Architecture\nvisibility: public\n---\n\nArchitecture details.\n",
    )
    _write_index(
        teleclaude_root / "docs" / "project" / "index.yaml",
        teleclaude_root,
        [
            {
                "id": "project/design/architecture",
                "description": "Architecture",
                "type": "design",
                "scope": "project",
                "path": "docs/project/design/architecture.md",
                "visibility": "public",
            }
        ],
    )

    monkeypatch.setattr(
        context_selector,
        "load_manifest",
        lambda: [
            ProjectManifestEntry(
                name="teleclaude",
                description="Core",
                index_path=str(teleclaude_root / "docs" / "project" / "index.yaml"),
                project_root=str(teleclaude_root),
            )
        ],
    )

    output = context_selector.build_context_output(
        areas=["design"],
        project_root=current_root,
        projects=["teleclaude"],
        caller_role="admin",
    )

    assert "teleclaude/design/architecture" in output
    assert "project/design/architecture" not in output


def test_projects_filter_merges_multiple_projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    current_root = tmp_path / "current"
    current_root.mkdir(parents=True, exist_ok=True)
    global_root = tmp_path / "global"
    global_snippets_root = global_root / "agents" / "docs"
    _write_index(global_snippets_root / "index.yaml", global_root, [])
    monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_snippets_root)

    teleclaude_root = tmp_path / "teleclaude"
    itsup_root = tmp_path / "itsup"

    _write(
        teleclaude_root / "docs" / "project" / "policy" / "one.md",
        "---\nid: project/policy/one\ntype: policy\nscope: project\ndescription: One\nvisibility: public\n---\n\nOne\n",
    )
    _write(
        itsup_root / "docs" / "project" / "policy" / "two.md",
        "---\nid: project/policy/two\ntype: policy\nscope: project\ndescription: Two\nvisibility: public\n---\n\nTwo\n",
    )
    _write_index(
        teleclaude_root / "docs" / "project" / "index.yaml",
        teleclaude_root,
        [
            {
                "id": "project/policy/one",
                "description": "One",
                "type": "policy",
                "scope": "project",
                "path": "docs/project/policy/one.md",
                "visibility": "public",
            }
        ],
    )
    _write_index(
        itsup_root / "docs" / "project" / "index.yaml",
        itsup_root,
        [
            {
                "id": "project/policy/two",
                "description": "Two",
                "type": "policy",
                "scope": "project",
                "path": "docs/project/policy/two.md",
                "visibility": "public",
            }
        ],
    )

    monkeypatch.setattr(
        context_selector,
        "load_manifest",
        lambda: [
            ProjectManifestEntry(
                "teleclaude", "", str(teleclaude_root / "docs" / "project" / "index.yaml"), str(teleclaude_root)
            ),
            ProjectManifestEntry("itsup", "", str(itsup_root / "docs" / "project" / "index.yaml"), str(itsup_root)),
        ],
    )

    output = context_selector.build_context_output(
        areas=["policy"],
        project_root=current_root,
        projects=["teleclaude", "itsup"],
        caller_role="admin",
    )

    assert "teleclaude/policy/one" in output
    assert "itsup/policy/two" in output


def test_phase2_cross_project_request_without_projects_returns_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current_root = tmp_path / "current"
    current_root.mkdir(parents=True, exist_ok=True)
    global_root = tmp_path / "global"
    global_snippets_root = global_root / "agents" / "docs"
    _write_index(global_snippets_root / "index.yaml", global_root, [])
    monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_snippets_root)

    teleclaude_root = tmp_path / "teleclaude"
    teleclaude_doc = teleclaude_root / "docs" / "project" / "design" / "architecture.md"
    _write(
        teleclaude_doc,
        "---\nid: project/design/architecture\ntype: design\nscope: project\n"
        "description: Architecture\nvisibility: public\n---\n\nArchitecture details.\n",
    )
    _write_index(
        teleclaude_root / "docs" / "project" / "index.yaml",
        teleclaude_root,
        [
            {
                "id": "project/design/architecture",
                "description": "Architecture",
                "type": "design",
                "scope": "project",
                "path": "docs/project/design/architecture.md",
                "visibility": "public",
            }
        ],
    )
    monkeypatch.setattr(
        context_selector,
        "load_manifest",
        lambda: [
            ProjectManifestEntry(
                "teleclaude", "", str(teleclaude_root / "docs" / "project" / "index.yaml"), str(teleclaude_root)
            ),
        ],
    )

    output = context_selector.build_context_output(
        areas=[],
        project_root=current_root,
        snippet_ids=["teleclaude/design/architecture"],
        caller_role="admin",
    )

    assert "teleclaude/design/architecture" in output
    assert "Architecture details." in output
    assert "access: denied" not in output


def test_single_project_mode_keeps_project_prefix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_root = tmp_path / "project"
    global_root = tmp_path / "global"
    global_snippets_root = global_root / "agents" / "docs"
    _write_index(global_snippets_root / "index.yaml", global_root, [])
    _write(
        project_root / "docs" / "project" / "policy" / "one.md",
        "---\nid: project/policy/one\ntype: policy\nscope: project\ndescription: One\nvisibility: public\n---\n\nOne\n",
    )
    _write_index(
        project_root / "docs" / "project" / "index.yaml",
        project_root,
        [
            {
                "id": "project/policy/one",
                "description": "One",
                "type": "policy",
                "scope": "project",
                "path": "docs/project/policy/one.md",
                "visibility": "public",
            }
        ],
    )

    monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_snippets_root)

    output = context_selector.build_context_output(
        areas=["policy"],
        project_root=project_root,
        caller_role="admin",
    )

    assert "project/policy/one" in output
    assert "/policy/one" in output


def test_stale_manifest_entry_is_skipped_gracefully(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_root = tmp_path / "project"
    global_root = tmp_path / "global"
    global_snippets_root = global_root / "agents" / "docs"
    _write_index(global_snippets_root / "index.yaml", global_root, [])
    monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_snippets_root)

    missing_index = tmp_path / "missing" / "index.yaml"
    monkeypatch.setattr(
        context_selector,
        "load_manifest",
        lambda: [ProjectManifestEntry("stale", "", str(missing_index), str(tmp_path / "missing"))],
    )

    output = context_selector.build_context_output(
        areas=["policy"],
        project_root=project_root,
        projects=["stale"],
        caller_role="admin",
    )

    assert "PHASE 1" in output


def test_index_cache_hit_and_miss(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    index_path = project_root / "docs" / "project" / "index.yaml"

    _write(
        project_root / "docs" / "project" / "policy" / "one.md",
        "---\nid: project/policy/one\ntype: policy\nscope: project\ndescription: One\nvisibility: public\n---\n\nOne\n",
    )
    _write_index(
        index_path,
        project_root,
        [
            {
                "id": "project/policy/one",
                "description": "One",
                "type": "policy",
                "scope": "project",
                "path": "docs/project/policy/one.md",
                "visibility": "public",
            }
        ],
    )

    context_selector._index_cache.clear()
    first = context_selector._load_index(index_path, source_project="project")
    second = context_selector._load_index(index_path, source_project="project")

    assert first[0].snippet_id == "project/policy/one"
    assert second[0].snippet_id == "project/policy/one"
    assert str(index_path.resolve()) in context_selector._index_cache

    _write(
        project_root / "docs" / "project" / "policy" / "two.md",
        "---\nid: project/policy/two\ntype: policy\nscope: project\ndescription: Two\nvisibility: public\n---\n\nTwo\n",
    )
    _write_index(
        index_path,
        project_root,
        [
            {
                "id": "project/policy/two",
                "description": "Two",
                "type": "policy",
                "scope": "project",
                "path": "docs/project/policy/two.md",
                "visibility": "public",
            }
        ],
    )
    time.sleep(0.01)
    index_path.touch()

    third = context_selector._load_index(index_path, source_project="project")
    assert third[0].snippet_id == "project/policy/two"


def test_non_admin_sees_only_public_visibility(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_root = tmp_path / "project"
    global_root = tmp_path / "global"
    global_snippets_root = global_root / "agents" / "docs"
    _write_index(global_snippets_root / "index.yaml", global_root, [])
    monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_snippets_root)

    _write(
        project_root / "docs" / "project" / "policy" / "public.md",
        "---\nid: project/policy/public\ntype: policy\nscope: project\ndescription: Public\nvisibility: public\n---\n\nPublic\n",
    )
    _write(
        project_root / "docs" / "project" / "policy" / "internal.md",
        "---\nid: project/policy/internal\ntype: policy\nscope: project\ndescription: Internal\nvisibility: internal\n---\n\nInternal\n",
    )
    _write(
        project_root / "docs" / "project" / "policy" / "default.md",
        "---\nid: project/policy/default\ntype: policy\nscope: project\ndescription: Default\n---\n\nDefault\n",
    )
    _write_index(
        project_root / "docs" / "project" / "index.yaml",
        project_root,
        [
            {
                "id": "project/policy/public",
                "description": "Public",
                "type": "policy",
                "scope": "project",
                "path": "docs/project/policy/public.md",
                "visibility": "public",
            },
            {
                "id": "project/policy/internal",
                "description": "Internal",
                "type": "policy",
                "scope": "project",
                "path": "docs/project/policy/internal.md",
                "visibility": "internal",
            },
            {
                "id": "project/policy/default",
                "description": "Default",
                "type": "policy",
                "scope": "project",
                "path": "docs/project/policy/default.md",
            },
        ],
    )

    output = context_selector.build_context_output(
        areas=["policy"],
        project_root=project_root,
        caller_role="member",
    )

    assert "project/policy/public" in output
    assert "project/policy/internal" not in output
    assert "project/policy/default" not in output


def test_admin_sees_all_visibility_levels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_root = tmp_path / "project"
    global_root = tmp_path / "global"
    global_snippets_root = global_root / "agents" / "docs"
    _write_index(global_snippets_root / "index.yaml", global_root, [])
    monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_snippets_root)

    _write(
        project_root / "docs" / "project" / "policy" / "public.md",
        "---\nid: project/policy/public\ntype: policy\nscope: project\ndescription: Public\nvisibility: public\n---\n\nPublic\n",
    )
    _write(
        project_root / "docs" / "project" / "policy" / "internal.md",
        "---\nid: project/policy/internal\ntype: policy\nscope: project\ndescription: Internal\nvisibility: internal\n---\n\nInternal\n",
    )
    _write_index(
        project_root / "docs" / "project" / "index.yaml",
        project_root,
        [
            {
                "id": "project/policy/public",
                "description": "Public",
                "type": "policy",
                "scope": "project",
                "path": "docs/project/policy/public.md",
                "visibility": "public",
            },
            {
                "id": "project/policy/internal",
                "description": "Internal",
                "type": "policy",
                "scope": "project",
                "path": "docs/project/policy/internal.md",
                "visibility": "internal",
            },
        ],
    )

    output = context_selector.build_context_output(
        areas=["policy"],
        project_root=project_root,
        caller_role="admin",
    )

    assert "project/policy/public" in output
    assert "project/policy/internal" in output


def test_caller_role_admin_is_authoritative_over_human_role(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_root = tmp_path / "project"
    global_root = tmp_path / "global"
    global_snippets_root = global_root / "agents" / "docs"
    _write_index(global_snippets_root / "index.yaml", global_root, [])
    monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_snippets_root)

    _write(
        project_root / "docs" / "project" / "policy" / "internal.md",
        "---\nid: project/policy/internal\ntype: policy\nscope: project\ndescription: Internal\nvisibility: internal\n---\n\nInternal\n",
    )
    _write_index(
        project_root / "docs" / "project" / "index.yaml",
        project_root,
        [
            {
                "id": "project/policy/internal",
                "description": "Internal",
                "type": "policy",
                "scope": "project",
                "path": "docs/project/policy/internal.md",
                "visibility": "internal",
            }
        ],
    )

    output = context_selector.build_context_output(
        areas=["policy"],
        project_root=project_root,
        caller_role="admin",
        human_role="member",
    )

    assert "project/policy/internal" in output


def test_phase2_denies_default_internal_for_non_admin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_root = tmp_path / "project"
    global_root = tmp_path / "global"
    global_snippets_root = global_root / "agents" / "docs"
    _write_index(global_snippets_root / "index.yaml", global_root, [])
    monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_snippets_root)

    _write(
        project_root / "docs" / "project" / "policy" / "default.md",
        "---\nid: project/policy/default\ntype: policy\nscope: project\ndescription: Default\n---\n\nDefault\n",
    )
    _write_index(
        project_root / "docs" / "project" / "index.yaml",
        project_root,
        [
            {
                "id": "project/policy/default",
                "description": "Default",
                "type": "policy",
                "scope": "project",
                "path": "docs/project/policy/default.md",
            }
        ],
    )

    output = context_selector.build_context_output(
        areas=[],
        project_root=project_root,
        snippet_ids=["project/policy/default"],
        caller_role="member",
    )

    assert "access: denied" in output
    assert "project/policy/default" in output
    assert "Default" not in output
