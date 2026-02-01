"""Tests for docs_index — the index.yaml building module."""

from pathlib import Path

import pytest
import yaml

from teleclaude.docs_index import (
    build_all_indexes,
    build_index_payload,
    extract_required_reads,
    normalize_titles,
    strip_baseline_frontmatter,
    write_baseline_index,
    write_index_yaml,
    write_third_party_index,
)


def _write_snippet(path: Path, *, id: str, type: str = "reference", scope: str = "project", desc: str = "Test") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nid: {id}\ntype: {type}\nscope: {scope}\ndescription: {desc}\n---\n\n# Title\n\n## Body\n\nContent.\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Index building
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWriteIndexYaml:
    def test_creates_index(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs" / "project"
        _write_snippet(docs / "test.md", id="test/snippet")
        index = write_index_yaml(tmp_path, docs)
        assert index.exists()
        data = yaml.safe_load(index.read_text())
        assert len(data["snippets"]) == 1
        assert data["snippets"][0]["id"] == "test/snippet"

    def test_skips_when_unchanged(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        docs = tmp_path / "docs" / "project"
        _write_snippet(docs / "test.md", id="test/snippet")
        write_index_yaml(tmp_path, docs)

        called = False
        original_write_text = Path.write_text

        def _track_write(self: Path, *args: object, **kwargs: object) -> int:
            nonlocal called
            called = True
            return original_write_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", _track_write)
        write_index_yaml(tmp_path, docs)
        assert called is False

    def test_removes_empty_index(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs" / "project"
        docs.mkdir(parents=True)
        index = docs / "index.yaml"
        index.write_text("old content")
        write_index_yaml(tmp_path, docs)
        assert not index.exists()

    def test_third_party_deletes_index(self, tmp_path: Path) -> None:
        tp = tmp_path / "docs" / "third-party"
        tp.mkdir(parents=True)
        index = tp / "index.yaml"
        index.write_text("stale")
        write_index_yaml(tmp_path, tp)
        assert not index.exists()


@pytest.mark.unit
class TestBuildIndexPayload:
    def test_resolves_requires(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs" / "project"
        _write_snippet(docs / "base.md", id="test/base", type="policy")
        child = docs / "child.md"
        child.parent.mkdir(parents=True, exist_ok=True)
        child.write_text(
            "---\nid: test/child\ntype: policy\nscope: project\ndescription: Child\n---\n\n"
            "# Child\n\n## Required reads\n- @test/base\n\n## Body\n\nContent.\n",
        )
        payload = build_index_payload(tmp_path, docs)
        by_id = {s["id"]: s for s in payload["snippets"]}
        assert "requires" in by_id["test/child"]
        assert "test/base" in by_id["test/child"]["requires"]

    def test_global_docs_use_tilde_paths(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs" / "global"
        _write_snippet(docs / "policy" / "test.md", id="sd/policy/test", type="policy", scope="global")
        payload = build_index_payload(tmp_path, docs)
        assert payload["project_root"] == "~/.teleclaude"
        assert payload["snippets_root"] == "~/.teleclaude/docs"

    def test_baseline_snippets_included(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs" / "global"
        baseline = docs / "baseline" / "principle"
        baseline.mkdir(parents=True)
        (baseline / "test.md").write_text("# Test — Principle\n\nContent.\n")
        payload = build_index_payload(tmp_path, docs)
        ids = [s["id"] for s in payload["snippets"]]
        assert "baseline/principle/test" in ids


# ---------------------------------------------------------------------------
# Title normalization
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNormalizeTitles:
    def test_adds_type_suffix(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs" / "global" / "baseline" / "policy"
        docs.mkdir(parents=True)
        f = docs / "test.md"
        f.write_text("# Test\n\nContent.\n")
        normalize_titles(tmp_path / "docs" / "global")
        assert "# Test — Policy" in f.read_text()

    def test_preserves_correct_suffix(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs" / "global" / "baseline" / "policy"
        docs.mkdir(parents=True)
        f = docs / "test.md"
        f.write_text("# Test — Policy\n\nContent.\n")
        normalize_titles(tmp_path / "docs" / "global")
        assert f.read_text().count("Policy") == 1


# ---------------------------------------------------------------------------
# Baseline management
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStripBaselineFrontmatter:
    def test_strips_frontmatter(self, tmp_path: Path) -> None:
        baseline = tmp_path / "agents" / "docs" / "baseline"
        baseline.mkdir(parents=True)
        f = baseline / "test.md"
        f.write_text("---\nid: test\n---\n# Title\n\nContent.\n")
        violations = strip_baseline_frontmatter(tmp_path)
        assert len(violations) == 1
        assert f.read_text().startswith("# Title")

    def test_no_frontmatter_no_change(self, tmp_path: Path) -> None:
        baseline = tmp_path / "agents" / "docs" / "baseline"
        baseline.mkdir(parents=True)
        f = baseline / "test.md"
        f.write_text("# Title\n\nContent.\n")
        violations = strip_baseline_frontmatter(tmp_path)
        assert violations == []


@pytest.mark.unit
class TestWriteBaselineIndex:
    def test_generates_index(self, tmp_path: Path) -> None:
        baseline = tmp_path / "agents" / "docs" / "baseline" / "principle"
        baseline.mkdir(parents=True)
        (baseline / "test.md").touch()
        write_baseline_index(tmp_path)
        index = tmp_path / "agents" / "docs" / "baseline" / "index.md"
        assert index.exists()
        content = index.read_text()
        assert "@~/.teleclaude/docs/baseline/principle/test.md" in content


@pytest.mark.unit
class TestWriteThirdPartyIndex:
    def test_generates_index(self, tmp_path: Path) -> None:
        tp = tmp_path / "docs" / "third-party" / "lib"
        tp.mkdir(parents=True)
        (tp / "feature.md").touch()
        write_third_party_index(tmp_path)
        index = tmp_path / "docs" / "third-party" / "index.md"
        assert index.exists()
        assert "@docs/third-party/lib/feature.md" in index.read_text()


# ---------------------------------------------------------------------------
# Required reads extraction
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractRequiredReads:
    def test_extracts_refs(self) -> None:
        content = "# Title\n\n## Required reads\n- @docs/foo.md\n- @docs/bar.md\n\n## Body\n"
        refs = extract_required_reads(content)
        assert refs == ["docs/foo.md", "docs/bar.md"]

    def test_empty_section(self) -> None:
        content = "# Title\n\n## Required reads\n\n## Body\n"
        refs = extract_required_reads(content)
        assert refs == []

    def test_no_section(self) -> None:
        content = "# Title\n\n## Body\n"
        refs = extract_required_reads(content)
        assert refs == []


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildAllIndexes:
    def test_builds_indexes_for_all_roots(self, tmp_path: Path) -> None:
        global_docs = tmp_path / "docs" / "global"
        project_docs = tmp_path / "docs" / "project"
        _write_snippet(global_docs / "policy" / "a.md", id="sd/policy/a", type="policy", scope="global")
        _write_snippet(project_docs / "ref" / "b.md", id="proj/ref/b")
        written = build_all_indexes(tmp_path)
        assert len(written) == 2
        for p in written:
            assert p.name == "index.yaml"
