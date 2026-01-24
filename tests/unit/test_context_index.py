from __future__ import annotations

from pathlib import Path

from teleclaude.context_index import build_snippet_index


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_build_snippet_index_resolves_requires(tmp_path: Path) -> None:
    project_root = tmp_path
    snippets_root = project_root / "docs"

    base = "---\nid: domain/base\ndescription: Base snippet\n---\n# Base\n\nBase content\n"
    child = (
        "---\n"
        "id: domain/child\n"
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

    entries = build_snippet_index(project_root)
    ids = [entry.snippet_id for entry in entries]

    assert ids == ["domain/base", "domain/child"]
    child_entry = next(entry for entry in entries if entry.snippet_id == "domain/child")
    assert child_entry.requires == ["docs/domain/base.md"]
