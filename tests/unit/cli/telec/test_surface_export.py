"""TDD tests for CLI surface markdown exporter."""

from __future__ import annotations

from syrupy.assertion import SnapshotAssertion

from teleclaude.cli.telec.surface import export_surface_markdown


def _command_heading(path: str) -> str:
    depth = min(len(path.split()) + 1, 6)
    return f"{'#' * depth} `telec {path}`"


def _command_block(markdown: str, path: str, next_path: str) -> str:
    start = markdown.index(_command_heading(path))
    end = markdown.index(_command_heading(next_path), start + len(path))
    return markdown[start:end]


class TestExportSurfaceMarkdown:
    """Verify export_surface_markdown() produces complete, structured output."""

    def test_export_surface_markdown(self, snapshot: SnapshotAssertion) -> None:
        result = export_surface_markdown()
        assert result == snapshot

    def test_sessions_start_block_renders_completely(self, snapshot: SnapshotAssertion) -> None:
        """Full agent-surface markdown block for sessions start. Captures the
        Usage line, Flags list, and Notes — the entire contract surface for
        the hidden-flag behavior in one assertion. Future drift produces a
        reviewable snapshot delta."""
        result = export_surface_markdown()
        assert _command_block(result, "sessions start", "sessions send") == snapshot

    def test_sessions_run_block_renders_completely(self, snapshot: SnapshotAssertion) -> None:
        """Full agent-surface markdown block for sessions run."""
        result = export_surface_markdown()
        assert _command_block(result, "sessions run", "sessions revive") == snapshot

    def test_todo_remove_block_documents_recoverable_soft_removal(self, snapshot: SnapshotAssertion) -> None:
        """The exported `telec todo remove` block must declare recoverable
        soft-removal + retention + row-id reactivation. Future drift produces a
        reviewable snapshot delta — the wording is the contract operators read."""
        result = export_surface_markdown()
        assert _command_block(result, "todo remove", "todo prepare") == snapshot
