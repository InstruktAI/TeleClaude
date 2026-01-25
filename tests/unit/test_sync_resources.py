"""Unit tests for sync_resources helpers."""

from pathlib import Path

import pytest

from scripts import sync_resources as bsi


@pytest.mark.unit
def test_write_index_yaml_skips_when_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """write_index_yaml should not rewrite index.yaml when content is unchanged."""
    docs_root = tmp_path / "docs"
    docs_root.mkdir(parents=True)

    snippet = docs_root / "example.md"
    snippet.write_text(
        "---\nid: example/snippet\ntype: reference\nscope: project\ndescription: Example snippet\n---\n\nBody\n",
        encoding="utf-8",
    )

    bsi.write_index_yaml(tmp_path, docs_root)

    called = False
    original_write_text = Path.write_text

    def _track_write(self: Path, *args: object, **kwargs: object) -> int:
        nonlocal called
        called = True
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _track_write)

    bsi.write_index_yaml(tmp_path, docs_root)

    assert called is False


@pytest.mark.unit
def test_agents_docs_index_uses_global_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """agents/docs index should point at ~/.teleclaude paths."""
    monkeypatch.setattr(bsi, "REPO_ROOT", tmp_path)
    agents_docs = tmp_path / "agents" / "docs"
    agents_docs.mkdir(parents=True)

    snippet = agents_docs / "example.md"
    snippet.write_text(
        "---\nid: example/snippet\ntype: reference\nscope: project\ndescription: Example snippet\n---\n\nBody\n",
        encoding="utf-8",
    )

    index_path = bsi.write_index_yaml(tmp_path, agents_docs)
    payload = index_path.read_text(encoding="utf-8")

    home = Path.home()
    assert f"project_root: {home / '.teleclaude'}" in payload
    assert f"snippets_root: {home / '.teleclaude' / 'docs'}" in payload
    assert "path: docs/" in payload


@pytest.mark.unit
def test_build_index_payload_uses_required_reads(tmp_path: Path) -> None:
    """build_index_payload should use Required reads section for requires."""
    docs_root = tmp_path / "docs"
    docs_root.mkdir(parents=True)

    base = docs_root / "base.md"
    base.write_text(
        "---\nid: example/base\ntype: policy\nscope: project\ndescription: Base\n---\n\n# Base\n\nBody\n",
        encoding="utf-8",
    )

    child = docs_root / "child.md"
    child.write_text(
        "---\nid: example/child\ntype: policy\nscope: project\ndescription: Child\n---\n\n"
        "# Child\n\n## Required reads\n- @example/base\n- @example/extra\n\nBody\n",
        encoding="utf-8",
    )

    payload = bsi.build_index_payload(tmp_path, docs_root)
    snippet_map = {entry["id"]: entry for entry in payload["snippets"]}
    assert snippet_map["example/child"]["requires"] == ["example/base", "example/extra"]
