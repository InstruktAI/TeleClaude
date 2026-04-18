"""Tests for teleclaude.quality.format — FormatRunner.

Behavioral contracts for the telec code format command: language-aware
code formatting with per-language dispatch.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# FormatRunner dispatches per-language formatters
# ---------------------------------------------------------------------------


class TestFormatRunnerDispatch:
    """FormatRunner dispatches formatters based on detected languages."""

    def test_python_files_dispatched_to_ruff(self, tmp_path: Path) -> None:
        """Python files are formatted with ruff check --fix and ruff format."""
        from teleclaude.quality.format import FormatRunner

        commands_run: list[list[str]] = []

        with patch("teleclaude.quality.format._run_format_tool") as mock_run:
            mock_run.side_effect = lambda cmd, cwd, name: commands_run.append(list(cmd))
            runner = FormatRunner(project_root=tmp_path, languages=["python"])
            runner.run(files=["teleclaude/foo.py", "teleclaude/bar.py"])

        ruff_cmds = [c for c in commands_run if "ruff" in c]
        assert len(ruff_cmds) >= 2, f"Expected ruff check + ruff format, got: {ruff_cmds}"

    def test_markdown_files_dispatched_to_prettier(self, tmp_path: Path) -> None:
        """Markdown files are formatted with prettier."""
        from teleclaude.quality.format import FormatRunner

        commands_run: list[list[str]] = []

        with patch("teleclaude.quality.format._run_format_tool") as mock_run:
            mock_run.side_effect = lambda cmd, cwd, name: commands_run.append(list(cmd))
            runner = FormatRunner(project_root=tmp_path, languages=["python"])
            runner.run(files=["docs/README.md"])

        prettier_cmds = [c for c in commands_run if "prettier" in c]
        assert len(prettier_cmds) >= 1, f"Expected prettier for markdown, got: {commands_run}"

    def test_no_files_formats_default_dirs(self, tmp_path: Path) -> None:
        """When no files specified, FormatRunner formats default directories."""
        from teleclaude.quality.format import FormatRunner

        commands_run: list[list[str]] = []

        with patch("teleclaude.quality.format._run_format_tool") as mock_run:
            mock_run.side_effect = lambda cmd, cwd, name: commands_run.append(list(cmd))
            runner = FormatRunner(project_root=tmp_path, languages=["python"])
            runner.run()

        assert len(commands_run) > 0, "FormatRunner with no files should still run formatters"

    def test_default_mode_does_not_pass_nonexistent_files(self, tmp_path: Path) -> None:
        """Default-mode markdown formatting only includes files that exist on disk."""
        from teleclaude.quality.format import FormatRunner

        calls: list[tuple[list[str], str]] = []

        with patch("teleclaude.quality.format._run_format_tool") as mock_run:
            mock_run.side_effect = lambda cmd, cwd, name: calls.append((list(cmd), name))
            runner = FormatRunner(project_root=tmp_path, languages=["python"])
            runner.run()

        # All markdown targets passed to prettier must exist on disk
        for cmd, name in calls:
            if "prettier" in cmd and "markdown" in name:
                targets = [c for c in cmd if not c.startswith("-") and c not in ("npx", "--yes", "prettier", "--write")]
                for target in targets:
                    target_path = tmp_path / target
                    assert target_path.exists() or target_path.is_dir(), (
                        f"prettier received nonexistent target {target!r}"
                    )

    def test_empty_file_list_is_noop(self, tmp_path: Path) -> None:
        """An explicit empty file list means nothing to format."""
        from teleclaude.quality.format import FormatRunner

        commands_run: list[list[str]] = []

        with patch("teleclaude.quality.format._run_format_tool") as mock_run:
            mock_run.side_effect = lambda cmd, cwd, name: commands_run.append(list(cmd))
            runner = FormatRunner(project_root=tmp_path, languages=["python"])
            runner.run(files=[])

        assert len(commands_run) == 0, "Empty file list should be a no-op"


# ---------------------------------------------------------------------------
# FormatRunner handles mixed file types
# ---------------------------------------------------------------------------


class TestFormatRunnerMixedFiles:
    """FormatRunner correctly separates file types for different formatters."""

    def test_mixed_python_and_markdown_dispatched_separately(self, tmp_path: Path) -> None:
        """Mixed .py and .md files go to their respective formatters."""
        from teleclaude.quality.format import FormatRunner

        commands_run: list[list[str]] = []

        with patch("teleclaude.quality.format._run_format_tool") as mock_run:
            mock_run.side_effect = lambda cmd, cwd, name: commands_run.append(list(cmd))
            runner = FormatRunner(project_root=tmp_path, languages=["python"])
            runner.run(files=["teleclaude/foo.py", "docs/bar.md"])

        ruff_cmds = [c for c in commands_run if "ruff" in c]
        prettier_cmds = [c for c in commands_run if "prettier" in c]
        assert len(ruff_cmds) >= 1, "Python files should go to ruff"
        assert len(prettier_cmds) >= 1, "Markdown files should go to prettier"


# ---------------------------------------------------------------------------
# FormatRunner failure handling
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# FormatRunner TypeScript support
# ---------------------------------------------------------------------------


class TestFormatRunnerTypeScript:
    """FormatRunner dispatches TypeScript files to prettier when TS is configured."""

    def test_typescript_files_dispatched_to_prettier(self, tmp_path: Path) -> None:
        """TypeScript files are formatted with prettier when typescript is in languages."""
        from teleclaude.quality.format import FormatRunner

        commands_run: list[list[str]] = []

        with patch("teleclaude.quality.format._run_format_tool") as mock_run:
            mock_run.side_effect = lambda cmd, cwd, name: commands_run.append(list(cmd))
            runner = FormatRunner(project_root=tmp_path, languages=["python", "typescript"])
            runner.run(files=["app/foo.tsx", "app/bar.ts"])

        prettier_cmds = [c for c in commands_run if "prettier" in c]
        assert len(prettier_cmds) >= 1, f"TypeScript files should go to prettier, got: {commands_run}"

    def test_typescript_default_mode_runs_prettier_from_frontend_root(self, tmp_path: Path) -> None:
        """In default mode with TS configured, prettier runs from the frontend_root directory."""
        from teleclaude.quality.format import FormatRunner

        calls: list[tuple[list[str], str, str]] = []

        with patch("teleclaude.quality.format._run_format_tool") as mock_run:
            mock_run.side_effect = lambda cmd, cwd, name: calls.append((list(cmd), str(cwd), name))
            (tmp_path / "teleclaude.yml").write_text(
                "languages:\n  - typescript\nfrontend_root: web\n",
                encoding="utf-8",
            )
            (tmp_path / "web").mkdir()
            runner = FormatRunner(project_root=tmp_path, languages=["typescript"])
            runner.run()

        ts_prettier_calls = [(cmd, cwd, name) for cmd, cwd, name in calls if "typescript" in name]
        assert len(ts_prettier_calls) >= 1, f"No TS prettier call in default mode: {calls}"
        _, cwd, _ = ts_prettier_calls[0]
        assert cwd == str(tmp_path / "web"), f"TS prettier should run from frontend_root, got cwd={cwd!r}"

    def test_typescript_files_ignored_when_not_configured(self, tmp_path: Path) -> None:
        """TypeScript files are skipped when typescript is not in languages."""
        from teleclaude.quality.format import FormatRunner

        commands_run: list[list[str]] = []

        with patch("teleclaude.quality.format._run_format_tool") as mock_run:
            mock_run.side_effect = lambda cmd, cwd, name: commands_run.append(list(cmd))
            runner = FormatRunner(project_root=tmp_path, languages=["python"])
            runner.run(files=["app/foo.tsx"])

        # No formatters should have run for TS files when TS not configured
        prettier_cmds = [c for c in commands_run if "prettier" in c]
        assert len(prettier_cmds) == 0, f"TS files should not be formatted without TS in languages: {commands_run}"


# ---------------------------------------------------------------------------
# FormatRunner failure handling
# ---------------------------------------------------------------------------


class TestFormatRunnerFailure:
    """FormatRunner propagates tool failures."""

    def test_ruff_failure_exits_nonzero(self, tmp_path: Path) -> None:
        """When ruff fails, FormatRunner exits non-zero."""
        from teleclaude.quality.format import FormatRunner

        with patch("teleclaude.quality.format._run_format_tool") as mock_run:
            mock_run.side_effect = SystemExit(1)
            runner = FormatRunner(project_root=tmp_path, languages=["python"])
            with pytest.raises(SystemExit):
                runner.run(files=["teleclaude/foo.py"])
