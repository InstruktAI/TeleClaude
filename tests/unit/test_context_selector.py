"""Unit tests for context_selector.build_context_output."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typing_extensions import TypedDict

from teleclaude import context_selector


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class SnippetPayload(TypedDict):
    id: str
    description: str
    type: str
    scope: str
    path: str


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
        "scope: project\ndescription: Base standard\n---\n\nBase content.\n",
    )
    _write(
        child_path,
        "---\nid: software-development/concepts/role\ntype: concept\n"
        "scope: project\ndescription: Role description\n---\n\n"
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
            },
            {
                "id": "software-development/concepts/role",
                "description": "Role description",
                "type": "concept",
                "scope": "project",
                "path": "docs/software-development/concepts/role.md",
            },
        ],
    )
    _write_index(global_snippets_root / "index.yaml", global_root, [])

    monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_snippets_root)

    output = context_selector.build_context_output(
        snippet_ids=["software-development/concepts/role"],
        areas=["concept"],
        project_root=project_root,
        human_role="admin",
    )

    assert "software-development/concepts/role" in output
    assert "Role content." in output
    assert "domain: software-development" in output
    # Dependency resolved from file @ ref
    assert "software-development/standards/base" in output
    assert "Base content." in output
    assert "Auto-included" in output


def test_phase2_invalid_ids_returns_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """build_context_output with invalid snippet_ids returns an error."""
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
    """build_context_output without snippet_ids returns snippet index."""
    project_root = tmp_path / "project"
    global_root = tmp_path / "global"
    global_snippets_root = global_root / "agents" / "docs"

    _write(
        project_root / "docs" / "test" / "base.md",
        "---\nid: test/base\ntype: policy\nscope: project\ndescription: A base snippet\n---\n\nContent.\n",
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
            }
        ],
    )
    _write_index(global_snippets_root / "index.yaml", global_root, [])

    monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_snippets_root)

    output = context_selector.build_context_output(
        snippet_ids=None,
        areas=["policy"],
        project_root=project_root,
        human_role="admin",
    )

    assert "PHASE 1" in output
    assert "test/base" in output
    assert "A base snippet" in output


# ---------------------------------------------------------------------------
# Role-based filtering tests
# ---------------------------------------------------------------------------


def _setup_multi_role(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Create a fixture with admin, member, and public role snippets."""
    project_root = tmp_path / "project"
    global_root = tmp_path / "global"
    global_snippets_root = global_root / "agents" / "docs"

    _write(
        project_root / "docs" / "test" / "admin-only.md",
        "---\nid: test/admin-only\ntype: policy\nscope: project\ndescription: Admin secret\n---\n\nAdmin content.\n",
    )
    _write(
        project_root / "docs" / "test" / "member-doc.md",
        "---\nid: test/member-doc\ntype: policy\nscope: project\ndescription: Member doc\n---\n\nMember content.\n",
    )
    _write(
        project_root / "docs" / "test" / "public.md",
        "---\nid: test/public\ntype: policy\nscope: project\ndescription: Public doc\n---\n\nPublic content.\n",
    )

    _write_index(
        project_root / "docs" / "project" / "index.yaml",
        project_root,
        [
            {
                "id": "test/admin-only",
                "description": "Admin secret",
                "type": "policy",
                "scope": "project",
                "path": "docs/test/admin-only.md",
                "role": "admin",
            },
            {
                "id": "test/member-doc",
                "description": "Member doc",
                "type": "policy",
                "scope": "project",
                "path": "docs/test/member-doc.md",
                "role": "member",
            },
            {
                "id": "test/public",
                "description": "Public doc",
                "type": "policy",
                "scope": "project",
                "path": "docs/test/public.md",
                "role": "public",
            },
        ],
    )
    _write_index(global_snippets_root / "index.yaml", global_root, [])
    monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_snippets_root)
    return project_root, global_snippets_root


def test_admin_sees_all_snippets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Admin role sees all snippets in Phase 1 index."""
    project_root, _ = _setup_multi_role(tmp_path, monkeypatch)
    output = context_selector.build_context_output(
        snippet_ids=None, areas=[], project_root=project_root, human_role="admin"
    )
    assert "test/admin-only" in output
    assert "test/member-doc" in output
    assert "test/public" in output


def test_member_sees_member_and_public(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Member role sees member and public, but not admin-only."""
    project_root, _ = _setup_multi_role(tmp_path, monkeypatch)
    output = context_selector.build_context_output(
        snippet_ids=None, areas=[], project_root=project_root, human_role="member"
    )
    assert "test/admin-only" not in output
    assert "test/member-doc" in output
    assert "test/public" in output


def test_customer_sees_only_public(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Customer/public role only sees public snippets."""
    project_root, _ = _setup_multi_role(tmp_path, monkeypatch)
    output = context_selector.build_context_output(
        snippet_ids=None, areas=[], project_root=project_root, human_role="customer"
    )
    assert "test/admin-only" not in output
    assert "test/member-doc" not in output
    assert "test/public" in output


def test_no_role_sees_only_public(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No role (None) defaults to public — least privilege."""
    project_root, _ = _setup_multi_role(tmp_path, monkeypatch)
    output = context_selector.build_context_output(
        snippet_ids=None, areas=[], project_root=project_root, human_role=None
    )
    assert "test/admin-only" not in output
    assert "test/member-doc" not in output
    assert "test/public" in output


def test_phase2_access_denied_for_forbidden_snippet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase 2 request for a snippet above caller's role returns access-denied."""
    project_root, _ = _setup_multi_role(tmp_path, monkeypatch)
    output = context_selector.build_context_output(
        snippet_ids=["test/admin-only"],
        areas=[],
        project_root=project_root,
        human_role="customer",
    )
    assert "access: denied" in output
    assert "test/admin-only" in output
    assert "Admin content." not in output


def test_phase2_access_denied_does_not_block_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase 2 with a mix of allowed and denied snippets returns content for allowed."""
    project_root, _ = _setup_multi_role(tmp_path, monkeypatch)
    output = context_selector.build_context_output(
        snippet_ids=["test/public", "test/admin-only"],
        areas=[],
        project_root=project_root,
        human_role="customer",
    )
    assert "Public content." in output
    assert "access: denied" in output
    assert "Admin content." not in output
