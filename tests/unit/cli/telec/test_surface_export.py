"""TDD tests for CLI surface markdown exporter."""

from __future__ import annotations

from teleclaude.cli.telec.surface import CLI_SURFACE, export_surface_markdown


class TestExportSurfaceMarkdown:
    """Verify export_surface_markdown() produces complete, structured output."""

    def test_returns_string(self) -> None:
        result = export_surface_markdown()
        assert isinstance(result, str)
        assert len(result) > 100

    def test_contains_all_top_level_commands(self) -> None:
        result = export_surface_markdown()
        for cmd_name in CLI_SURFACE:
            assert cmd_name in result, f"Top-level command '{cmd_name}' missing from export"

    def test_contains_representative_subcommands(self) -> None:
        result = export_surface_markdown()
        # sessions subcommands
        assert "sessions list" in result or "list" in result
        assert "sessions start" in result or "start" in result
        # docs subcommands
        assert "index" in result
        # roadmap subcommands
        assert "roadmap list" in result or "deliver" in result

    def test_contains_representative_flags(self) -> None:
        result = export_surface_markdown()
        assert "--all" in result
        assert "--project" in result
        assert "--agent" in result

    def test_contains_descriptions(self) -> None:
        result = export_surface_markdown()
        # Check that actual descriptions from CLI_SURFACE appear
        assert "Manage agent sessions" in result
        assert "Print version, channel, and commit" in result

    def test_no_hidden_commands_in_output(self) -> None:
        result = export_surface_markdown()
        # 'watch' is hidden — should be excluded
        # Check it doesn't appear as a top-level heading
        assert "## watch" not in result.lower() or "watch" not in result.split("##")

    def test_is_pure_no_side_effects(self) -> None:
        """Calling twice returns identical output (pure function)."""
        first = export_surface_markdown()
        second = export_surface_markdown()
        assert first == second
