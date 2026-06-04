"""Characterization tests for teleclaude.snippet_validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude import snippet_validation

pytestmark = pytest.mark.unit

_SNIPPET_ID = "project/policy/example"


def _write_project_snippet(root: Path, content: str) -> Path:
    snippet_path = root / "docs" / "project" / "policy" / "example.md"
    snippet_path.parent.mkdir(parents=True)
    snippet_path.write_text(content, encoding="utf-8")
    index_path = root / "docs" / "project" / "index.yaml"
    index_path.write_text(
        (
            f"project_root: {root}\n"
            "snippets:\n"
            f"- id: {_SNIPPET_ID}\n"
            "  description: Example\n"
            "  type: policy\n"
            "  scope: project\n"
            "  path: docs/project/policy/example.md\n"
        ),
        encoding="utf-8",
    )
    return snippet_path


def _snippet_content(delivered_by: str, body: str) -> str:
    delivered_line = f"delivered_by: {delivered_by}\n" if delivered_by else ""
    return (
        "---\n"
        f"id: {_SNIPPET_ID}\n"
        "type: policy\n"
        "scope: project\n"
        "description: Example\n"
        f"{delivered_line}"
        "---\n"
        "# Example\n\n"
        f"{body}\n"
    )


class TestValidateSnippetIdFormat:
    def test_accepts_valid_snippet_id(self) -> None:
        parts, error = snippet_validation.validate_snippet_id_format(
            "project/policy/getting-started",
            domains={"software-development"},
        )

        assert error is None
        assert parts is not None
        assert parts.value() == "project/policy/getting-started"

    def test_rejects_values_that_look_like_paths(self) -> None:
        parts, error = snippet_validation.validate_snippet_id_format(
            "docs/project/policy/getting-started.md",
            domains={"software-development"},
        )

        assert parts is None
        assert error == "looks_like_path"


class TestExpectedSnippetIdForPath:
    def test_builds_expected_project_id(self, tmp_path: Path) -> None:
        path = tmp_path / "docs" / "project" / "policy" / "getting-started.md"
        path.parent.mkdir(parents=True)
        path.write_text("body", encoding="utf-8")

        expected, error = snippet_validation.expected_snippet_id_for_path(
            path,
            project_root=tmp_path,
            domains={"software-development"},
        )

        assert (expected, error) == ("project/policy/getting-started", None)


class TestValidateInlineRefFormat:
    def test_validates_project_and_global_inline_refs(self) -> None:
        assert (
            snippet_validation.validate_inline_ref_format(
                "@docs/project/policy/getting-started.md",
                domains={"software-development"},
            )
            is None
        )
        assert (
            snippet_validation.validate_inline_ref_format(
                f"@{snippet_validation.Path.home()}/.teleclaude/docs/general/policy/shared.md",
                domains={"software-development"},
            )
            is None
        )


class TestLoadDomains:
    def test_returns_canonical_domain_scopes(self, tmp_path: Path) -> None:
        domains = snippet_validation.load_domains(tmp_path)

        assert domains == {"software-development", "creative", "marketing", "customer-relations"}


class TestSnippetBodyDigest:
    def test_ignores_delivered_by_frontmatter_churn(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        snippet_path = _write_project_snippet(tmp_path, _snippet_content("[slug-a]", "Stable body."))
        first = snippet_validation.snippet_body_digest(_SNIPPET_ID)
        snippet_path.write_text(_snippet_content("[slug-a, slug-b]", "Stable body."), encoding="utf-8")

        second = snippet_validation.snippet_body_digest(_SNIPPET_ID)

        assert first == second

    def test_body_edit_changes_digest(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        snippet_path = _write_project_snippet(tmp_path, _snippet_content("[slug-a]", "Stable body."))
        first = snippet_validation.snippet_body_digest(_SNIPPET_ID)
        snippet_path.write_text(_snippet_content("[slug-a]", "Changed body."), encoding="utf-8")

        second = snippet_validation.snippet_body_digest(_SNIPPET_ID)

        assert first != second

    def test_empty_delivered_by_matches_absent_delivered_by(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        snippet_path = _write_project_snippet(tmp_path, _snippet_content("[]", "Stable body."))
        first = snippet_validation.snippet_body_digest(_SNIPPET_ID)
        snippet_path.write_text(_snippet_content("", "Stable body."), encoding="utf-8")

        second = snippet_validation.snippet_body_digest(_SNIPPET_ID)

        assert first == second
