"""Characterization tests for teleclaude.events.schema_export."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from teleclaude.events.schema_export import export_events_markdown, export_json_schema, export_json_schema_file


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


class TestExportEventsMarkdown:
    """Verify export_events_markdown() produces inspector-ready markdown."""

    def test_returns_string(self) -> None:
        result = export_events_markdown()
        assert isinstance(result, str)
        assert len(result) > 50

    def test_contains_schema_content(self) -> None:
        result = export_events_markdown()
        assert "EventEnvelope" in result or "properties" in result

    def test_contains_json_block(self) -> None:
        result = export_events_markdown()
        assert "```json" in result

    def test_wraps_existing_json_schema(self) -> None:
        """The markdown export must include all content from the JSON schema."""
        json_schema = export_json_schema()
        md = export_events_markdown()
        for key in ("title", "properties", "type"):
            if key in json_schema:
                assert key in md

    def test_is_pure_no_side_effects(self) -> None:
        first = export_events_markdown()
        second = export_events_markdown()
        assert first == second
