from __future__ import annotations

from pathlib import Path

from scripts.sync_resources import build_index_payload


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_sync_resources_resolves_requires(tmp_path: Path) -> None:
    project_root = tmp_path
    snippets_root = project_root / "docs"

    base = "---\nid: domain/base\ntype: reference\nscope: project\ndescription: Base snippet\n---\n# Base\n\nBase content\n"
    child = (
        "---\n"
        "id: domain/child\n"
        "type: reference\n"
        "scope: project\n"
        "description: Child snippet\n"
        "---\n"
        "# Child\n\n"
        "## Required reads\n"
        "- @./base.md\n\n"
        "Child content\n"
    )

    _write(snippets_root / "domain" / "base.md", base)
    _write(snippets_root / "domain" / "child.md", child)
    _write(snippets_root / "baseline" / "identity.md", "# Baseline\n")

    payload = build_index_payload(project_root, snippets_root)
    entries = payload["snippets"]
    ids = [entry["id"] for entry in entries]

    assert ids == ["domain/base", "domain/child"]
    child_entry = next(entry for entry in entries if entry["id"] == "domain/child")
    assert child_entry["requires"] == ["domain/base"]
