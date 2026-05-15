"""Characterization tests for teleclaude.resource_validation._snippet."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude import paths as tc_paths
from teleclaude.resource_validation import _models as resource_models
from teleclaude.resource_validation import _snippet

pytestmark = pytest.mark.unit


class TestResolveRefPath:
    def test_rejects_partials_traversal_to_prevent_escaping_anchor(self, tmp_path: Path) -> None:
        # Traversal must short-circuit to None so validate_artifact_refs_exist
        # (which only checks existence) cannot follow .. out of agents/_partials/.
        assert (
            _snippet.resolve_ref_path(
                "./_partials/../foo.md",
                root_path=tmp_path,
                current_path=tmp_path / "agents" / "commands" / "next-build.md",
            )
            is None
        )

    def test_falls_back_to_project_docs_when_plain_docs_target_is_missing(self, tmp_path: Path) -> None:
        project_root = tmp_path
        current_path = project_root / "docs" / "project" / "policy" / "current.md"
        current_path.parent.mkdir(parents=True)
        current_path.write_text("current", encoding="utf-8")
        target = project_root / "docs" / "project" / "policy" / "target.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("target", encoding="utf-8")

        resolved = _snippet.resolve_ref_path("docs/policy/target.md", root_path=project_root, current_path=current_path)

        assert resolved == target.resolve()


class TestIterInlineRefs:
    def test_skips_code_fence_contents(self) -> None:
        refs = _snippet.iter_inline_refs(
            [
                "@docs/project/policy/one.md",
                "```md",
                "@docs/project/policy/two.md",
                "```",
                "- @docs/project/policy/three.md",
            ]
        )

        assert refs == ["@docs/project/policy/one.md", "@docs/project/policy/three.md"]


class TestCollectInlineRefErrors:
    def test_reports_missing_and_non_file_targets(self, tmp_path: Path) -> None:
        project_root = tmp_path
        snippet_path = project_root / "docs" / "project" / "policy" / "snippet.md"
        snippet_path.parent.mkdir(parents=True)
        snippet_path.write_text("body", encoding="utf-8")
        existing_dir = project_root / "docs" / "project" / "policy" / "folder.md"
        existing_dir.mkdir()

        errors = _snippet.collect_inline_ref_errors(
            project_root,
            snippet_path,
            [
                "@docs/project/policy/missing.md",
                "@docs/project/policy/folder.md",
            ],
            domains={"software-development"},
        )

        assert {error["code"] for error in errors} == {
            "snippet_inline_ref_missing",
            "snippet_inline_ref_not_file",
        }

    def test_resolves_existing_partial_to_no_errors(self, tmp_path: Path) -> None:
        project_root = tmp_path
        snippet_path = project_root / "docs" / "project" / "policy" / "snippet.md"
        snippet_path.parent.mkdir(parents=True)
        snippet_path.write_text("body", encoding="utf-8")
        partial = project_root / "agents" / "_partials" / "foo.md"
        partial.parent.mkdir(parents=True)
        partial.write_text("partial", encoding="utf-8")

        errors = _snippet.collect_inline_ref_errors(
            project_root,
            snippet_path,
            ["@./_partials/foo.md"],
            domains={"software-development"},
        )

        assert errors == []

    def test_reports_missing_partial(self, tmp_path: Path) -> None:
        project_root = tmp_path
        snippet_path = project_root / "docs" / "project" / "policy" / "snippet.md"
        snippet_path.parent.mkdir(parents=True)
        snippet_path.write_text("body", encoding="utf-8")

        errors = _snippet.collect_inline_ref_errors(
            project_root,
            snippet_path,
            ["@./_partials/missing.md"],
            domains={"software-development"},
        )

        assert [error["code"] for error in errors] == ["snippet_inline_ref_missing"]


class TestSeeAlsoValidation:
    def test_global_docs_require_global_prefix(self, tmp_path: Path) -> None:
        resource_models.clear_errors()
        path = tmp_path / "docs" / "global" / "general" / "policy" / "doc.md"
        path.parent.mkdir(parents=True)
        path.write_text("body", encoding="utf-8")

        _snippet._validate_see_also_ref("docs/project/policy/other.md", path, tmp_path)

        assert resource_models.get_errors()[0]["code"] == "snippet_see_also_bad_prefix"

    def test_global_docs_accept_smudged_home_prefix(self, tmp_path: Path) -> None:
        resource_models.clear_errors()
        path = tmp_path / "docs" / "global" / "general" / "policy" / "doc.md"
        path.parent.mkdir(parents=True)
        path.write_text("body", encoding="utf-8")
        target = tmp_path / "docs" / "global" / "general" / "concept" / "other.md"
        target.parent.mkdir(parents=True)
        target.write_text("body", encoding="utf-8")

        smudged_ref = str(tc_paths.GLOBAL_SNIPPETS_DIR / "general" / "concept" / "other.md")

        _snippet._validate_see_also_ref(smudged_ref, path, tmp_path)

        assert not resource_models.get_errors()


class TestThirdPartyValidation:
    def test_accepts_valid_third_party_frontmatter(self, tmp_path: Path) -> None:
        resource_models.clear_errors()
        doc_path = tmp_path / "docs" / "third-party" / "library" / "guide.md"
        doc_path.parent.mkdir(parents=True)
        doc_path.write_text(
            (
                "---\n"
                "id: third-party/library/guide\n"
                "type: third-party\n"
                "scope: project\n"
                "description: Library guide\n"
                "---\n"
                "# Library Guide\n\n"
                "## Sources\n"
                "- https://example.com\n"
            ),
            encoding="utf-8",
        )

        _snippet.validate_snippet(
            doc_path,
            doc_path.read_text(encoding="utf-8"),
            tmp_path,
            domains={"software-development"},
        )

        assert resource_models.get_errors() == []

    def test_reports_all_missing_third_party_frontmatter_fields(self, tmp_path: Path) -> None:
        resource_models.clear_errors()
        doc_path = tmp_path / "docs" / "third-party" / "guide.md"
        doc_path.parent.mkdir(parents=True)
        doc_path.write_text("# Guide\n\n## Sources\n- https://example.com\n", encoding="utf-8")

        _snippet.validate_snippet(
            doc_path,
            doc_path.read_text(encoding="utf-8"),
            tmp_path,
            domains={"software-development"},
        )

        assert [
            (error["code"], error.get("field"))
            for error in resource_models.get_errors()
            if error["code"] == "snippet_missing_frontmatter_field"
        ] == [
            ("snippet_missing_frontmatter_field", "id"),
            ("snippet_missing_frontmatter_field", "type"),
            ("snippet_missing_frontmatter_field", "scope"),
            ("snippet_missing_frontmatter_field", "description"),
        ]

    def test_reports_non_url_source_entries_as_errors(self, tmp_path: Path) -> None:
        resource_models.clear_errors()
        doc_path = tmp_path / "docs" / "third-party" / "guide.md"
        doc_path.parent.mkdir(parents=True)
        doc_path.write_text(
            (
                "---\n"
                "id: third-party/guide\n"
                "type: third-party\n"
                "scope: project\n"
                "description: Guide\n"
                "---\n"
                "# Guide\n\n"
                "## Sources\n"
                "- not-a-url\n"
                "- /context7/library\n"
                "- https://example.com\n"
            ),
            encoding="utf-8",
        )

        _snippet.validate_third_party_docs(tmp_path)

        assert resource_models.get_errors() == [
            {"code": "third_party_source_invalid", "path": str(doc_path), "source": "not-a-url"}
        ]
