"""Characterization tests for teleclaude.resource_validation._models."""
# pylint: disable=protected-access,too-few-public-methods

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.resource_validation import _models

pytestmark = pytest.mark.unit


class TestStringListCoercion:
    """Validate string-list coercion for schema fragments."""

    def test_returns_list_only_when_all_items_are_strings(self) -> None:
        """Reject mixed-type lists when normalizing schema values."""
        assert _models._as_str_list(["a", "b"]) == ["a", "b"]
        assert not _models._as_str_list(["a", 2])


class TestWarningAndErrorCollection:
    """Exercise the in-memory warning and error registries."""

    def test_warn_and_error_are_collected_and_clearable(self) -> None:
        """Keep warnings/errors observable and resettable between validations."""
        _models.clear_warnings()

        _models._warn("warn_code", path="docs/a.md", reason="why")
        _models._error("error_code", path="docs/b.md", ref="@docs/project")

        assert _models.get_warnings() == [{"code": "warn_code", "path": "docs/a.md", "reason": "why"}]
        assert _models.get_errors() == [{"code": "error_code", "path": "docs/b.md", "ref": "@docs/project"}]

        _models.clear_warnings()

        assert not _models.get_warnings()
        assert not _models.get_errors()


class TestLoadSchema:
    """Cover schema loading and the default procedure contract."""

    def test_reads_supported_global_and_section_fields(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Load the YAML schema into the normalized runtime shape."""
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

    def test_default_procedure_schema_does_not_allow_required_tools(self) -> None:
        """Keep the procedure schema limited to the canonical section set."""
        procedure_schema = _models._SCHEMA["sections"].get("procedure", {})
        assert "Required tools" not in procedure_schema.get("allowed", [])
