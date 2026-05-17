"""Tests for teleclaude.quality.format — FormatRunner.

Behavioral contracts for the telec code format command: language-aware
code formatting with per-language dispatch.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from teleclaude.quality.format import FormatRunner
from teleclaude.quality.scope import DirtyOp, DirtyPath, WorkspaceScopeKind, WorkspaceScopeResolution

PACKAGE_STORAGE = "storage"
PACKAGE_WORKFLOW = "workflow"
WORKFLOW_SOURCE = "crates/workflow/src/lib.rs"
STORAGE_SOURCE = "crates/storage/src/lib.rs"
PYTHON_SOURCE = "teleclaude/foo.py"


def _workspace_resolution(
    *,
    kind: WorkspaceScopeKind,
    scoped_existing_paths: tuple[str, ...],
    has_session_identity: bool = True,
) -> WorkspaceScopeResolution:
    return WorkspaceScopeResolution(
        kind=kind,
        has_session_identity=has_session_identity,
        dirty_paths=tuple(DirtyPath(path, DirtyOp.MODIFIED) for path in scoped_existing_paths),
        scoped_dirty_paths=scoped_existing_paths,
        scoped_existing_paths=scoped_existing_paths,
    )


def _write_rust_workspace(root: Path) -> None:
    (root / "Cargo.toml").write_text(
        '[workspace]\nmembers = ["crates/workflow", "crates/storage"]\n',
        encoding="utf-8",
    )
    _write_rust_crate(root, "workflow", PACKAGE_WORKFLOW)
    _write_rust_crate(root, "storage", PACKAGE_STORAGE)


def _write_rust_crate(root: Path, member: str, package: str) -> None:
    crate = root / "crates" / member
    (crate / "src").mkdir(parents=True)
    (crate / "Cargo.toml").write_text(
        f'[package]\nname = "{package}"\nversion = "0.1.0"\nedition = "2021"\n',
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# FormatRunner dispatches per-language formatters
# ---------------------------------------------------------------------------


class TestFormatRunnerDispatch:
    """FormatRunner dispatches formatters based on detected languages."""

    def test_python_files_dispatched_to_ruff(self, tmp_path: Path) -> None:
        """Python files are formatted with ruff check --fix and ruff format."""
        commands_run: list[list[str]] = []

        with patch("teleclaude.quality.format._run_format_tool") as mock_run:
            mock_run.side_effect = lambda cmd, cwd, name: commands_run.append(list(cmd))
            runner = FormatRunner(project_root=tmp_path, languages=["python"])
            runner.run(files=["teleclaude/foo.py", "teleclaude/bar.py"])

        ruff_cmds = [c for c in commands_run if "ruff" in c]
        assert len(ruff_cmds) >= 2, f"Expected ruff check + ruff format, got: {ruff_cmds}"

    def test_markdown_files_dispatched_to_prettier(self, tmp_path: Path) -> None:
        """Markdown files are formatted with prettier."""
        commands_run: list[list[str]] = []

        with patch("teleclaude.quality.format._run_format_tool") as mock_run:
            mock_run.side_effect = lambda cmd, cwd, name: commands_run.append(list(cmd))
            runner = FormatRunner(project_root=tmp_path, languages=["python"])
            runner.run(files=["docs/README.md"])

        prettier_cmds = [c for c in commands_run if "prettier" in c]
        assert len(prettier_cmds) >= 1, f"Expected prettier for markdown, got: {commands_run}"

    def test_yaml_files_dispatched_to_prettier(self, tmp_path: Path) -> None:
        """YAML files are formatted with prettier, not Python formatters."""
        commands_run: list[list[str]] = []

        with patch("teleclaude.quality.format._run_format_tool") as mock_run:
            mock_run.side_effect = lambda cmd, cwd, name: commands_run.append(list(cmd))
            runner = FormatRunner(project_root=tmp_path, languages=["python", "typescript"])
            runner.run(files=[".github/workflows/lint-test.yaml"])

        prettier_cmds = [c for c in commands_run if "prettier" in c]
        ruff_cmds = [c for c in commands_run if "ruff" in c]
        assert len(prettier_cmds) >= 1, f"Expected prettier for YAML, got: {commands_run}"
        assert len(ruff_cmds) == 0, f"YAML should not be sent to ruff: {commands_run}"

    def test_no_files_formats_default_dirs(self, tmp_path: Path) -> None:
        """When no files specified, FormatRunner formats default directories."""
        commands_run: list[list[str]] = []

        with patch("teleclaude.quality.format._run_format_tool") as mock_run:
            mock_run.side_effect = lambda cmd, cwd, name: commands_run.append(list(cmd))
            runner = FormatRunner(project_root=tmp_path, languages=["python"])
            runner.run()

        assert len(commands_run) > 0, "FormatRunner with no files should still run formatters"

    def test_default_mode_does_not_pass_nonexistent_files(self, tmp_path: Path) -> None:
        """Default-mode markdown formatting only includes files that exist on disk."""
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
        commands_run: list[list[str]] = []

        with patch("teleclaude.quality.format._run_format_tool") as mock_run:
            mock_run.side_effect = lambda cmd, cwd, name: commands_run.append(list(cmd))
            runner = FormatRunner(project_root=tmp_path, languages=["python", "typescript"])
            runner.run(files=["app/foo.tsx", "app/bar.ts"])

        prettier_cmds = [c for c in commands_run if "prettier" in c]
        assert len(prettier_cmds) >= 1, f"TypeScript files should go to prettier, got: {commands_run}"

    def test_typescript_default_mode_runs_prettier_from_frontend_root(self, tmp_path: Path) -> None:
        """In default mode with TS configured, prettier runs from the frontend_root directory."""
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
        commands_run: list[list[str]] = []

        with patch("teleclaude.quality.format._run_format_tool") as mock_run:
            mock_run.side_effect = lambda cmd, cwd, name: commands_run.append(list(cmd))
            runner = FormatRunner(project_root=tmp_path, languages=["python"])
            runner.run(files=["app/foo.tsx"])

        # No formatters should have run for TS files when TS not configured
        prettier_cmds = [c for c in commands_run if "prettier" in c]
        assert len(prettier_cmds) == 0, f"TS files should not be formatted without TS in languages: {commands_run}"


class TestFormatRunnerRust:
    """FormatRunner dispatches Rust files to cargo fmt when Rust is declared."""

    def test_no_arg_rust_format_uses_single_package_scope(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No-arg Rust formatting derives workspace scope and uses cargo -p."""
        _write_rust_workspace(tmp_path)
        calls: list[tuple[list[str], Path, str]] = []

        monkeypatch.setattr(
            "teleclaude.quality.format.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.WORKTREE,
                scoped_existing_paths=(WORKFLOW_SOURCE,),
            ),
        )

        with patch("teleclaude.quality.format._run_format_tool") as mock_run:
            mock_run.side_effect = lambda cmd, cwd, name: calls.append((list(cmd), cwd, name))
            FormatRunner(project_root=tmp_path, languages=["rust"]).run()

        assert calls == [(["cargo", "fmt", "-p", PACKAGE_WORKFLOW], tmp_path, "cargo fmt")]

    def test_run_all_rust_format_uses_workspace_scope(self, tmp_path: Path) -> None:
        """--all Rust formatting runs cargo fmt --all from workspace root."""
        _write_rust_workspace(tmp_path)
        calls: list[tuple[list[str], Path, str]] = []

        with patch("teleclaude.quality.format._run_format_tool") as mock_run:
            mock_run.side_effect = lambda cmd, cwd, name: calls.append((list(cmd), cwd, name))
            FormatRunner(project_root=tmp_path, languages=["rust"]).run(run_all=True)

        assert calls == [(["cargo", "fmt", "--all"], tmp_path, "cargo fmt")]

    def test_cross_crate_rust_format_uses_workspace_scope(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cross-crate Rust scope formats the whole Cargo workspace."""
        _write_rust_workspace(tmp_path)
        calls: list[tuple[list[str], Path, str]] = []

        monkeypatch.setattr(
            "teleclaude.quality.format.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.WORKTREE,
                scoped_existing_paths=(WORKFLOW_SOURCE, STORAGE_SOURCE),
            ),
        )

        with patch("teleclaude.quality.format._run_format_tool") as mock_run:
            mock_run.side_effect = lambda cmd, cwd, name: calls.append((list(cmd), cwd, name))
            FormatRunner(project_root=tmp_path, languages=["rust"]).run()

        assert calls == [(["cargo", "fmt", "--all"], tmp_path, "cargo fmt")]

    def test_explicit_rust_file_formats_package_scope(self, tmp_path: Path) -> None:
        """Explicit .rs files trigger package-scoped cargo fmt."""
        _write_rust_workspace(tmp_path)
        calls: list[tuple[list[str], Path, str]] = []

        with patch("teleclaude.quality.format._run_format_tool") as mock_run:
            mock_run.side_effect = lambda cmd, cwd, name: calls.append((list(cmd), cwd, name))
            FormatRunner(project_root=tmp_path, languages=["rust"]).run(files=[WORKFLOW_SOURCE])

        assert calls == [(["cargo", "fmt", "-p", PACKAGE_WORKFLOW], tmp_path, "cargo fmt")]

    def test_explicit_non_rust_file_does_not_invoke_cargo(self, tmp_path: Path) -> None:
        """Non-Rust explicit files do not launch cargo fmt."""
        _write_rust_workspace(tmp_path)
        calls: list[tuple[list[str], Path, str]] = []

        with patch("teleclaude.quality.format._run_format_tool") as mock_run:
            mock_run.side_effect = lambda cmd, cwd, name: calls.append((list(cmd), cwd, name))
            FormatRunner(project_root=tmp_path, languages=["rust"]).run(files=["docs/x.md"])

        assert [call for call in calls if call[0] and call[0][0] == "cargo"] == []

    def test_python_only_project_does_not_invoke_cargo_for_rust_path(self, tmp_path: Path) -> None:
        """Rust-looking paths are ignored when rust is not declared."""
        _write_rust_workspace(tmp_path)
        calls: list[tuple[list[str], Path, str]] = []

        with patch("teleclaude.quality.format._run_format_tool") as mock_run:
            mock_run.side_effect = lambda cmd, cwd, name: calls.append((list(cmd), cwd, name))
            FormatRunner(project_root=tmp_path, languages=["python"]).run(files=[WORKFLOW_SOURCE])

        assert [call for call in calls if call[0] and call[0][0] == "cargo"] == []

    def test_rust_only_project_does_not_format_python_files(self, tmp_path: Path) -> None:
        """Explicit Python files do not run ruff in declared Rust-only projects."""
        _write_rust_workspace(tmp_path)
        calls: list[tuple[list[str], Path, str]] = []

        with patch("teleclaude.quality.format._run_format_tool") as mock_run:
            mock_run.side_effect = lambda cmd, cwd, name: calls.append((list(cmd), cwd, name))
            FormatRunner(project_root=tmp_path, languages=["rust"]).run(files=[PYTHON_SOURCE])

        assert [call for call in calls if call[0] and call[0][0] == "ruff"] == []
        assert [call for call in calls if call[0] and call[0][0] == "cargo"] == []

    def test_no_arg_rust_format_with_empty_scope_skips_cargo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Declared Rust with no Rust-owned scoped files does not launch cargo."""
        _write_rust_workspace(tmp_path)
        calls: list[tuple[list[str], Path, str]] = []

        monkeypatch.setattr(
            "teleclaude.quality.format.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.WORKTREE,
                scoped_existing_paths=("docs/x.md",),
            ),
        )

        with patch("teleclaude.quality.format._run_format_tool") as mock_run:
            mock_run.side_effect = lambda cmd, cwd, name: calls.append((list(cmd), cwd, name))
            FormatRunner(project_root=tmp_path, languages=["rust"]).run()

        assert calls == []


# ---------------------------------------------------------------------------
# FormatRunner failure handling
# ---------------------------------------------------------------------------


class TestFormatRunnerFailure:
    """FormatRunner propagates tool failures."""

    def test_ruff_failure_exits_nonzero(self, tmp_path: Path) -> None:
        """When ruff fails, FormatRunner exits non-zero."""
        with patch("teleclaude.quality.format._run_format_tool") as mock_run:
            mock_run.side_effect = SystemExit(1)
            runner = FormatRunner(project_root=tmp_path, languages=["python"])
            with pytest.raises(SystemExit):
                runner.run(files=["teleclaude/foo.py"])
