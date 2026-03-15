"""Characterization tests for teleclaude.events.schema_export."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from teleclaude.events.schema_export import export_json_schema, export_json_schema_file


def _props() -> dict[str, Any]:  # guard: loose-dict-func - JSON schema properties are untyped at runtime
    return cast(dict[str, Any], export_json_schema()["properties"])


class TestExportJsonSchema:
    def test_returns_dict(self) -> None:
        schema = export_json_schema()
        assert isinstance(schema, dict)

    def test_schema_has_title(self) -> None:
        schema = export_json_schema()
        assert "title" in schema

    def test_schema_has_properties(self) -> None:
        schema = export_json_schema()
        assert "properties" in schema

    def test_schema_includes_event_field(self) -> None:
        assert "event" in _props()

    def test_schema_includes_source_field(self) -> None:
        assert "source" in _props()

    def test_schema_includes_level_field(self) -> None:
        assert "level" in _props()

    def test_schema_includes_payload_field(self) -> None:
        assert "payload" in _props()


class TestExportJsonSchemaFile:
    def test_writes_file(self, tmp_path: Path) -> None:
        output = tmp_path / "schema.json"
        export_json_schema_file(output)
        assert output.exists()

    def test_written_file_is_valid_json(self, tmp_path: Path) -> None:
        output = tmp_path / "schema.json"
        export_json_schema_file(output)
        content = output.read_text()
        parsed = json.loads(content)
        assert isinstance(parsed, dict)

    def test_written_schema_matches_export_json_schema(self, tmp_path: Path) -> None:
        output = tmp_path / "schema.json"
        export_json_schema_file(output)
        from_file = json.loads(output.read_text())
        from_function = export_json_schema()
        assert from_file == from_function
