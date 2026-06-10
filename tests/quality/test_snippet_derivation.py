"""Functional tests for path-derived snippet classification."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.snippet_validation import SnippetScope, SnippetTaxonomy, derive_snippet_classification

pytestmark = pytest.mark.functional


def _write(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Example\n", encoding="utf-8")
    return path


def test_derives_general_global_classification(tmp_path: Path, snapshot: object) -> None:
    path = _write(tmp_path / "docs" / "global" / "general" / "concept" / "example.md")

    classification, reason = derive_snippet_classification(
        path,
        project_root=tmp_path,
        domains={"software-development"},
    )

    assert reason is None
    assert classification is not None
    assert classification.type is SnippetTaxonomy.CONCEPT
    assert classification.scope is SnippetScope.GLOBAL
    assert {"id": classification.id, "domain": classification.domain} == snapshot


def test_derives_domain_global_classification(tmp_path: Path, snapshot: object) -> None:
    path = _write(tmp_path / "docs" / "global" / "software-development" / "policy" / "testing.md")

    classification, reason = derive_snippet_classification(
        path,
        project_root=tmp_path,
        domains={"software-development"},
    )

    assert reason is None
    assert classification is not None
    assert classification.type is SnippetTaxonomy.POLICY
    assert classification.scope is SnippetScope.GLOBAL
    assert {"id": classification.id, "domain": classification.domain} == snapshot


def test_derives_project_classification(tmp_path: Path, snapshot: object) -> None:
    path = _write(tmp_path / "docs" / "project" / "spec" / "feature" / "context" / "index-build.md")

    classification, reason = derive_snippet_classification(
        path,
        project_root=tmp_path,
        domains={"software-development"},
    )

    assert reason is None
    assert classification is not None
    assert classification.type is SnippetTaxonomy.SPEC
    assert classification.scope is SnippetScope.PROJECT
    assert {"id": classification.id, "domain": classification.domain} == snapshot


def test_companion_derives_parent_classification(tmp_path: Path, snapshot: object) -> None:
    parent = _write(tmp_path / "docs" / "global" / "general" / "procedure" / "authoring.md")
    companion = parent.with_name("authoring.example-slug.md")
    _write(companion)

    classification, reason = derive_snippet_classification(
        companion,
        project_root=tmp_path,
        domains={"software-development"},
    )

    assert reason is None
    assert classification is not None
    assert classification.type is SnippetTaxonomy.PROCEDURE
    assert classification.scope is SnippetScope.GLOBAL
    assert {"id": classification.id, "domain": classification.domain} == snapshot


def test_non_derivable_path_returns_reason(tmp_path: Path, snapshot: object) -> None:
    path = _write(tmp_path / "README.md")

    classification, reason = derive_snippet_classification(
        path,
        project_root=tmp_path,
        domains={"software-development"},
    )

    assert {"classification": classification, "reason": reason} == snapshot
