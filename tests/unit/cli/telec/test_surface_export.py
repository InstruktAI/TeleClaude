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

    def test_hidden_detach_is_absent_from_sessions_start_usage_and_flags(self) -> None:
        """--detach must not surface in the Usage line or **Flags:** list of sessions start."""
        result = export_surface_markdown()
        start = result.find("### `telec sessions start`")
        send = result.find("### `telec sessions send`")
        block = result[start:send]
        usage_and_flags = block.split("**Notes:**", 1)[0]
        assert "--detach" not in usage_and_flags, (
            f"--detach leaked into sessions start Usage/Flags block: {usage_and_flags!r}"
        )

    def test_hidden_detach_is_absent_from_sessions_run_usage_and_flags(self) -> None:
        """--detach must not surface in the Usage line or **Flags:** list of sessions run."""
        result = export_surface_markdown()
        run = result.find("### `telec sessions run`")
        revive = result.find("### `telec sessions revive`")
        block = result[run:revive]
        usage_and_flags = block.split("**Notes:**", 1)[0]
        assert "--detach" not in usage_and_flags, (
            f"--detach leaked into sessions run Usage/Flags block: {usage_and_flags!r}"
        )

    def test_hidden_detach_warning_remains_in_notes(self) -> None:
        """The concise warning must remain in Notes for both sessions start and sessions run."""
        result = export_surface_markdown()
        for header, end_header in (
            ("### `telec sessions start`", "### `telec sessions send`"),
            ("### `telec sessions run`", "### `telec sessions revive`"),
        ):
            block = result[result.find(header) : result.find(end_header)]
            notes = block.split("**Notes:**", 1)[1] if "**Notes:**" in block else ""
            assert "--detach" in notes, f"expected --detach warning in Notes for {header}"
