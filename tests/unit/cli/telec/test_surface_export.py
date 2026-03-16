"""TDD tests for CLI surface markdown exporter."""

from __future__ import annotations

from teleclaude.cli.telec.surface import CLI_SURFACE, export_surface_markdown


class TestExportSurfaceMarkdown:
    """Verify export_surface_markdown() produces complete, structured output."""

    def test_contains_all_visible_top_level_commands(self) -> None:
        result = export_surface_markdown()
        for cmd_name, cmd_def in CLI_SURFACE.items():
            if cmd_def.hidden:
                continue
            assert f"`telec {cmd_name}`" in result, f"Visible top-level command '{cmd_name}' missing from export"

    def test_excludes_hidden_commands(self) -> None:
        result = export_surface_markdown()
        for cmd_name, cmd_def in CLI_SURFACE.items():
            if cmd_def.hidden:
                assert f"`telec {cmd_name}`" not in result, f"Hidden command '{cmd_name}' should not appear in export"

    def test_renders_flags_in_expected_format(self) -> None:
        result = export_surface_markdown()
        assert "- `--all`" in result
        assert "- `--project`" in result
        assert "- `--agent`" in result

    def test_contains_descriptions(self) -> None:
        result = export_surface_markdown()
        assert "Manage agent sessions" in result
        assert "Print version, channel, and commit" in result
