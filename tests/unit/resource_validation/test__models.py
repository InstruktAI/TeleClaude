"""Characterization tests for teleclaude.resource_validation._models."""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.resource_validation import _models

pytestmark = pytest.mark.unit


class TestStringListCoercion:
    def test_returns_list_only_when_all_items_are_strings(self) -> None:
        assert _models._as_str_list(["a", "b"]) == ["a", "b"]
        assert _models._as_str_list(["a", 2]) == []


class TestWarningAndErrorCollection:
    def test_warn_and_error_are_collected_and_clearable(self) -> None:
        _models.clear_warnings()

        _models._warn("warn_code", path="docs/a.md", reason="why")
        _models._error("error_code", path="docs/b.md", ref="@docs/project")

        assert _models.get_warnings() == [{"code": "warn_code", "path": "docs/a.md", "reason": "why"}]
        assert _models.get_errors() == [{"code": "error_code", "path": "docs/b.md", "ref": "@docs/project"}]

        _models.clear_warnings()

        assert _models.get_warnings() == []
        assert _models.get_errors() == []


class TestLoadSchema:
    def test_reads_supported_global_and_section_fields(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        schema_path = tmp_path / "snippet_schema.yaml"
        schema_path.write_text(
            """
global:
  require_h1: true
  allow_h3: false
  required_reads_title: Required reads
sections:
  policy:
    required: [Overview]
    allowed: [Overview, Steps]
""",
            encoding="utf-8",
        )
        monkeypatch.setattr(_models, "_SCHEMA_PATH", schema_path)

        schema = _models._load_schema()

        assert schema["global_"]["require_h1"] is True
        assert schema["global_"]["allow_h3"] is False
        assert schema["sections"]["policy"]["required"] == ["Overview"]
        assert schema["sections"]["policy"]["allowed"] == ["Overview", "Steps"]
