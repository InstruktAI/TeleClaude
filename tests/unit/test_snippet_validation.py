"""Characterization tests for teleclaude.snippet_validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude import snippet_validation

pytestmark = pytest.mark.unit


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

    def test_baseline_index_has_no_expected_id(self, tmp_path: Path) -> None:
        path = tmp_path / "docs" / "global" / "baseline" / "index.md"
        path.parent.mkdir(parents=True)
        path.write_text("body", encoding="utf-8")

        assert snippet_validation.expected_snippet_id_for_path(
            path,
            project_root=tmp_path,
            domains={"software-development"},
        ) == (None, None)


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
    def test_loads_domains_from_project_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = tmp_path / "teleclaude.yml"
        config_path.write_text("business:\n  domains:\n    - engineering\n    - support\n", encoding="utf-8")
        monkeypatch.setenv("TELECLAUDE_PROJECT_CONFIG_PATH", str(config_path))

        domains = snippet_validation.load_domains(tmp_path)

        assert domains == {"engineering", "support"}
