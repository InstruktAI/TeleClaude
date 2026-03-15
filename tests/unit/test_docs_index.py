"""Characterization tests for teleclaude.docs_index."""

from __future__ import annotations

from pathlib import Path

import yaml

import teleclaude.docs_index as docs_index


def test_normalize_frontmatter_single_quotes_renders_scalar_values_as_strings() -> None:
    content = "---\ntitle: Hello\ncount: 3\nmissing:\n---\n# Body\n"

    normalized = docs_index._normalize_frontmatter_single_quotes(content)

    assert normalized == "---\ntitle: 'Hello'\ncount: '3'\nmissing: ''\n---\n# Body\n"


def test_normalize_titles_preserves_frontmatter_and_adds_type_suffix(tmp_path: Path) -> None:
    snippets_root = tmp_path / "docs" / "project"
    snippets_root.mkdir(parents=True)
    snippet_path = snippets_root / "access.md"
    snippet_path.write_text("---\ntype: policy\n---\n# Access Rules\nUse MFA.\n", encoding="utf-8")

    docs_index.normalize_titles(snippets_root)

    assert snippet_path.read_text(encoding="utf-8") == "---\ntype: 'policy'\n---\n# Access Rules — Policy\nUse MFA."


def test_remove_non_baseline_indexes_only_deletes_stale_non_third_party_indexes(tmp_path: Path) -> None:
    snippets_root = tmp_path / "docs" / "project"
    top_level = snippets_root / "index.md"
    baseline = snippets_root / "baseline" / "policy" / "index.md"
    third_party = snippets_root / "third-party" / "index.md"
    top_level.parent.mkdir(parents=True, exist_ok=True)
    baseline.parent.mkdir(parents=True, exist_ok=True)
    third_party.parent.mkdir(parents=True, exist_ok=True)
    top_level.write_text("top\n", encoding="utf-8")
    baseline.write_text("baseline\n", encoding="utf-8")
    third_party.write_text("third-party\n", encoding="utf-8")

    removed = docs_index.remove_non_baseline_indexes(snippets_root)

    assert removed == [str(top_level)]
    assert not top_level.exists()
    assert baseline.exists()
    assert third_party.exists()


def test_build_index_payload_for_global_root_includes_baseline_and_rewrites_paths(tmp_path: Path) -> None:
    project_root = tmp_path
    snippets_root = project_root / "docs" / "global"
    baseline_path = snippets_root / "baseline" / "policy" / "shared.md"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text("# Shared Policy\nBody.\n", encoding="utf-8")

    project_snippet = snippets_root / "spec" / "api.md"
    project_snippet.parent.mkdir(parents=True, exist_ok=True)
    project_snippet.write_text(
        (
            "---\n"
            "id: project/spec/api\n"
            "description: API surface\n"
            "type: spec\n"
            "scope: global\n"
            "visibility: public\n"
            "---\n"
            "# API\n"
            "Body.\n"
        ),
        encoding="utf-8",
    )

    payload = docs_index.build_index_payload(project_root, snippets_root)
    snippets = {entry["id"]: entry for entry in payload["snippets"]}

    assert payload["project_root"] == "~/.teleclaude"
    assert payload["snippets_root"] == "~/.teleclaude/docs"
    assert snippets["baseline/policy/shared"]["path"] == "docs/baseline/policy/shared.md"
    assert snippets["baseline/policy/shared"]["type"] == "policy"
    assert snippets["baseline/policy/shared"]["visibility"] == "internal"
    assert snippets["project/spec/api"]["path"] == "docs/spec/api.md"
    assert snippets["project/spec/api"]["visibility"] == "public"
    assert {entry["source_project"] for entry in payload["snippets"]} == {project_root.name}


def test_write_third_party_index_yaml_writes_entries_and_removes_empty_index(tmp_path: Path) -> None:
    third_party_root = tmp_path / "docs" / "third-party"
    doc_path = third_party_root / "react" / "hooks.md"
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text("# Hooks\nBody.\n", encoding="utf-8")

    index_path = docs_index.write_third_party_index_yaml(third_party_root, scope="project")
    payload = yaml.safe_load(index_path.read_text(encoding="utf-8"))

    expected_root = str(third_party_root)
    home = str(Path.home())
    if expected_root.startswith(home):
        expected_root = expected_root.replace(home, "~", 1)
    assert payload["snippets_root"] == expected_root
    assert payload["snippets"] == [
        {
            "id": "third-party/react/hooks",
            "description": "Hooks",
            "scope": "project",
            "path": "react/hooks.md",
        }
    ]

    doc_path.unlink()
    assert docs_index.write_third_party_index_yaml(third_party_root, scope="project") is None
    assert not index_path.exists()
