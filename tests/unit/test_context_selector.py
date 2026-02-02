"""Unit tests for context_selector.build_context_output."""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

import pytest
import yaml

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
    child_path = project_root / "docs" / "software-development" / "roles" / "role.md"

    _write(
        base_path,
        "---\nid: software-development/standards/base\ntype: policy\n"
        "scope: project\ndescription: Base standard\n---\n\nBase content.\n",
    )
    _write(
        child_path,
        "---\nid: software-development/roles/role\ntype: role\n"
        "scope: project\ndescription: Role description\n---\n\n"
        f"## Required reads\n\n- @{base_path}\n\nRole content.\n",
    )

    _write_index(
        project_root / "docs" / "index.yaml",
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
                "id": "software-development/roles/role",
                "description": "Role description",
                "type": "role",
                "scope": "project",
                "path": "docs/software-development/roles/role.md",
            },
        ],
    )
    _write_index(global_snippets_root / "index.yaml", global_root, [])

    monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_snippets_root)

    output = context_selector.build_context_output(
        snippet_ids=["software-development/roles/role"],
        areas=["role"],
        project_root=project_root,
    )

    assert "software-development/roles/role" in output
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

    _write_index(project_root / "docs" / "index.yaml", project_root, [])
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
        project_root / "docs" / "index.yaml",
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
    )

    assert "PHASE 1" in output
    assert "test/base" in output
    assert "A base snippet" in output
