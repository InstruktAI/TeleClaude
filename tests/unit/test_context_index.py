from __future__ import annotations

from pathlib import Path

from teleclaude.docs_index import DEFAULT_ROLE, build_index_payload


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
    assert "requires" not in child_entry


# ---------------------------------------------------------------------------
# Role derivation tests
# ---------------------------------------------------------------------------


def test_role_public_stored_in_index(tmp_path: Path) -> None:
    """Snippet with role: public stores that role in the index entry."""
    project_root = tmp_path
    snippets_root = project_root / "docs"

    _write(
        snippets_root / "domain" / "faq.md",
        "---\nid: domain/faq\ntype: spec\nscope: project\n"
        "description: Public FAQ\nrole: public\n---\n# FAQ\n\nFAQ content\n",
    )
    _write(snippets_root / "baseline" / "identity.md", "# Baseline\n")

    payload = build_index_payload(project_root, snippets_root)
    entry = next(e for e in payload["snippets"] if e["id"] == "domain/faq")
    assert entry.get("role") == "public"


def test_role_admin_stored_in_index(tmp_path: Path) -> None:
    """Snippet with role: admin stores that role in the index entry."""
    project_root = tmp_path
    snippets_root = project_root / "docs"

    _write(
        snippets_root / "domain" / "secrets.md",
        "---\nid: domain/secrets\ntype: spec\nscope: project\n"
        "description: Admin secrets\nrole: admin\n---\n# Secrets\n\nSecret content\n",
    )
    _write(snippets_root / "baseline" / "identity.md", "# Baseline\n")

    payload = build_index_payload(project_root, snippets_root)
    entry = next(e for e in payload["snippets"] if e["id"] == "domain/secrets")
    assert entry.get("role") == "admin"


def test_no_role_defaults_to_member(tmp_path: Path) -> None:
    """Snippet without role defaults to member."""
    project_root = tmp_path
    snippets_root = project_root / "docs"

    _write(
        snippets_root / "domain" / "guide.md",
        "---\nid: domain/guide\ntype: spec\nscope: project\ndescription: Member guide\n---\n# Guide\n\nGuide content\n",
    )
    _write(snippets_root / "baseline" / "identity.md", "# Baseline\n")

    payload = build_index_payload(project_root, snippets_root)
    entry = next(e for e in payload["snippets"] if e["id"] == "domain/guide")
    assert entry.get("role") == DEFAULT_ROLE
