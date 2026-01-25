from __future__ import annotations

from pathlib import Path
from typing import TypedDict

import pytest
import yaml

from teleclaude import context_selector


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _snippet(
    snippet_id: str, snippet_type: str, scope: str, description: str, body: str, requires: list[str] | None = None
) -> str:
    requires = requires or []
    requires_block = "\n".join(f"  - {req}" for req in requires)
    return (
        "---\n"
        f"id: {snippet_id}\n"
        f"type: {snippet_type}\n"
        f"scope: {scope}\n"
        f"description: {description}\n" + ("requires:\n" + requires_block + "\n" if requires else "") + "---\n"
        f"{body}\n"
    )


class SnippetPayload(TypedDict):
    id: str
    description: str
    type: str
    scope: str
    path: str
    requires: list[str]


def _write_index(index_path: Path, project_root: Path, snippets: list[SnippetPayload]) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "project_root": str(project_root),
        "snippets": snippets,
    }
    index_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_context_selector_state_and_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_root = tmp_path / "project"
    global_root = tmp_path / "global"
    global_snippets_root = global_root / "agents" / "docs"

    base = _snippet(
        "software-development/standards/base",
        "policy",
        "project",
        "Base standard",
        "Base content.",
    )
    child = _snippet(
        "software-development/roles/role",
        "role",
        "project",
        "Role description",
        "Role content. @docs/software-development/standards/base.md",
        ["software-development/standards/base"],
    )

    _write(project_root / "docs" / "software-development" / "standards" / "base.md", base)
    _write(project_root / "docs" / "software-development" / "roles" / "role.md", child)

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
                "requires": [],
            },
            {
                "id": "software-development/roles/role",
                "description": "Role description",
                "type": "role",
                "scope": "project",
                "path": "docs/software-development/roles/role.md",
                "requires": ["software-development/standards/base"],
            },
        ],
    )
    _write_index(global_snippets_root / "index.yaml", global_root, [])

    monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_snippets_root)
    monkeypatch.setattr(context_selector, "CONTEXT_STATE_PATH", tmp_path / "state.json")

    output = context_selector.build_context_output(
        snippet_ids=["software-development/roles/role"],
        areas=["role"],
        project_root=project_root,
        session_id="session-1",
    )

    assert "ALREADY_PROVIDED_IDS:" in output
    assert "NEW_SNIPPETS:" in output
    assert "software-development/roles/role" in output
    assert "software-development/standards/base" in output
    assert "Role content." in output
    assert "Base content." in output
    assert "domain: software-development" in output
    expected_inline = project_root / "docs" / "software-development" / "standards" / "base.md"
    assert f"@{expected_inline}" in output

    second = context_selector.build_context_output(
        snippet_ids=["software-development/roles/role"],
        areas=["role"],
        project_root=project_root,
        session_id="session-1",
    )

    assert "ALREADY_PROVIDED_IDS:" in second
    assert "software-development/roles/role" in second
    assert "software-development/standards/base" in second
    assert "NEW_SNIPPETS:\n(none)" in second
