from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude import context_selector


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _snippet(snippet_id: str, snippet_type: str, scope: str, description: str, body: str, requires: list[str] | None = None) -> str:
    requires = requires or []
    requires_block = "\n".join(f"  - {req}" for req in requires)
    return (
        "---\n"
        f"id: {snippet_id}\n"
        f"type: {snippet_type}\n"
        f"scope: {scope}\n"
        f"description: {description}\n"
        + ("requires:\n" + requires_block + "\n" if requires else "")
        + "---\n"
        f"{body}\n"
    )


def test_context_selector_state_and_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_root = tmp_path / "project"
    global_root = tmp_path / "global"

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
        "Role content.",
        ["../standards/base.md"],
    )

    _write(project_root / "docs" / "snippets" / "software-development" / "standards" / "base.md", base)
    _write(project_root / "docs" / "snippets" / "software-development" / "roles" / "role.md", child)

    monkeypatch.setattr(context_selector, "GLOBAL_SNIPPETS_DIR", global_root)
    monkeypatch.setattr(context_selector, "CONTEXT_STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(context_selector, "_select_ids", lambda corpus, metadata: ["software-development/roles/role"])

    output = context_selector.build_context_output(
        corpus="Need role guidance",
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
    assert "scope: project" in output

    second = context_selector.build_context_output(
        corpus="Need role guidance",
        areas=["role"],
        project_root=project_root,
        session_id="session-1",
    )

    assert "ALREADY_PROVIDED_IDS:" in second
    assert "software-development/roles/role" in second
    assert "software-development/standards/base" in second
    assert "NEW_SNIPPETS:\n(none)" in second
