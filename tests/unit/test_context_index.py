from __future__ import annotations

from pathlib import Path

from teleclaude.docs_index import CLEARANCE_TO_AUDIENCE, DEFAULT_CLEARANCE, build_index_payload


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
# Clearance-to-audience derivation tests
# ---------------------------------------------------------------------------


def test_clearance_public_derives_full_audience(tmp_path: Path) -> None:
    """Snippet with clearance: public gets audience visible to all roles."""
    project_root = tmp_path
    snippets_root = project_root / "docs"

    _write(
        snippets_root / "domain" / "faq.md",
        "---\nid: domain/faq\ntype: spec\nscope: project\n"
        "description: Public FAQ\nclearance: public\n---\n# FAQ\n\nFAQ content\n",
    )
    _write(snippets_root / "baseline" / "identity.md", "# Baseline\n")

    payload = build_index_payload(project_root, snippets_root)
    entry = next(e for e in payload["snippets"] if e["id"] == "domain/faq")
    assert entry["audience"] == CLEARANCE_TO_AUDIENCE["public"]
    assert entry.get("clearance") == "public"


def test_clearance_admin_derives_admin_only_audience(tmp_path: Path) -> None:
    """Snippet with clearance: admin only visible to admin."""
    project_root = tmp_path
    snippets_root = project_root / "docs"

    _write(
        snippets_root / "domain" / "secrets.md",
        "---\nid: domain/secrets\ntype: spec\nscope: project\n"
        "description: Admin secrets\nclearance: admin\n---\n# Secrets\n\nSecret content\n",
    )
    _write(snippets_root / "baseline" / "identity.md", "# Baseline\n")

    payload = build_index_payload(project_root, snippets_root)
    entry = next(e for e in payload["snippets"] if e["id"] == "domain/secrets")
    assert entry["audience"] == ["admin"]
    assert entry.get("clearance") == "admin"


def test_no_clearance_defaults_to_member(tmp_path: Path) -> None:
    """Snippet without clearance or audience defaults to member clearance."""
    project_root = tmp_path
    snippets_root = project_root / "docs"

    _write(
        snippets_root / "domain" / "guide.md",
        "---\nid: domain/guide\ntype: spec\nscope: project\ndescription: Member guide\n---\n# Guide\n\nGuide content\n",
    )
    _write(snippets_root / "baseline" / "identity.md", "# Baseline\n")

    payload = build_index_payload(project_root, snippets_root)
    entry = next(e for e in payload["snippets"] if e["id"] == "domain/guide")
    assert entry["audience"] == CLEARANCE_TO_AUDIENCE[DEFAULT_CLEARANCE]
    assert entry.get("clearance") == DEFAULT_CLEARANCE


def test_explicit_audience_overrides_clearance(tmp_path: Path) -> None:
    """Explicit audience array takes precedence over clearance derivation."""
    project_root = tmp_path
    snippets_root = project_root / "docs"

    _write(
        snippets_root / "domain" / "custom.md",
        "---\nid: domain/custom\ntype: spec\nscope: project\n"
        "description: Custom audience\naudience:\n  - public\n  - member\n"
        "clearance: admin\n---\n# Custom\n\nCustom content\n",
    )
    _write(snippets_root / "baseline" / "identity.md", "# Baseline\n")

    payload = build_index_payload(project_root, snippets_root)
    entry = next(e for e in payload["snippets"] if e["id"] == "domain/custom")
    # Explicit audience wins over clearance
    assert entry["audience"] == ["public", "member"]
    assert "clearance" not in entry
