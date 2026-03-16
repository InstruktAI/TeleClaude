"""TDD tests for config surface markdown exporter."""

from __future__ import annotations

from teleclaude.config.schema_export import export_config_markdown


class TestExportConfigMarkdown:
    """Verify export_config_markdown() produces complete, structured output."""

    def test_contains_config_model_sections(self) -> None:
        result = export_config_markdown()
        assert "Global Config" in result
        assert "Project Config" in result
        assert "Person Config" in result

    def test_contains_key_config_fields(self) -> None:
        result = export_config_markdown()
        assert "`people`" in result
        assert "`subscriptions`" in result
        assert "`project_name`" in result
        assert "`hooks`" in result
        assert "`jobs`" in result
        assert "`deployment`" in result

    def test_contains_json_schema_block(self) -> None:
        result = export_config_markdown()
        assert "```json" in result
        assert '"properties"' in result
