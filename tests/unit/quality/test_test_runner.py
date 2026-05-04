"""Tests for R2: telec code test command.

Behavioral contracts for the telec code test command: language-aware test execution
with automatic worktree scoping and companion file mapping.
"""

from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess

import pytest

from teleclaude.quality.test_runner import TestRunner, map_source_to_companion, resolve_test_targets, run_pytest

# ---------------------------------------------------------------------------
# R2.1 — Companion file mapping convention
# ---------------------------------------------------------------------------


class TestCompanionMapping:
    """Session-touched source files are mapped to their test companions."""

    @pytest.mark.parametrize(
        "source_path, expected_companion",
        [
            ("teleclaude/foo/bar.py", "tests/unit/foo/test_bar.py"),
            ("teleclaude/cli/handler.py", "tests/unit/cli/test_handler.py"),
            ("teleclaude/quality/toolchain.py", "tests/unit/quality/test_toolchain.py"),
            ("teleclaude/project_setup/skeleton.py", "tests/unit/project_setup/test_skeleton.py"),
            # Boundary: top-level file (no subdirectory)
            ("teleclaude/top_level.py", "tests/unit/test_top_level.py"),
            # Boundary: deeply nested path
            ("teleclaude/a/b/c/deep.py", "tests/unit/a/b/c/test_deep.py"),
        ],
    )
    def test_source_maps_to_correct_companion(self, source_path: str, expected_companion: str) -> None:
        """teleclaude/x/y.py maps to tests/unit/x/test_y.py."""
        companion = map_source_to_companion(source_path)
        assert companion == expected_companion

    def test_missing_companion_not_included_in_targets(self, tmp_path: Path) -> None:
        """resolve_test_targets omits source files whose companion does not exist on disk."""
        targets = resolve_test_targets(
            project_root=tmp_path,
            touched_files={"teleclaude/nonexistent_module.py"},
        )
        assert "tests/unit/test_nonexistent_module.py" not in targets


# ---------------------------------------------------------------------------
# R2.2 — Test files directly touched by session are included
# ---------------------------------------------------------------------------


class TestDirectlyTouchedTestFiles:
    """Test files already under tests/ appear in targets without remapping."""

    def test_touched_test_file_included_directly(self, tmp_path: Path) -> None:
        """A file already under tests/ is included directly, not remapped."""
        test_file = tmp_path / "tests" / "unit" / "test_direct.py"
        test_file.parent.mkdir(parents=True)
        test_file.touch()

        targets = resolve_test_targets(
            project_root=tmp_path,
            touched_files={"tests/unit/test_direct.py"},
        )
        assert "tests/unit/test_direct.py" in targets

    def test_touched_test_file_appears_exactly_once(self, tmp_path: Path) -> None:
        """A test file already under tests/ is not duplicated via companion mapping."""
        test_file = tmp_path / "tests" / "unit" / "test_foo.py"
        test_file.parent.mkdir(parents=True)
        test_file.touch()

        targets = resolve_test_targets(
            project_root=tmp_path,
            touched_files={"tests/unit/test_foo.py"},
        )
        assert targets.count("tests/unit/test_foo.py") == 1


# ---------------------------------------------------------------------------
# R2.3 — Expensive tests excluded by default
# ---------------------------------------------------------------------------


class TestExpensiveTestExclusion:
    """Expensive tests are excluded by default; opt-in required to run them."""

    def test_default_pytest_args_exclude_expensive_marker(self, tmp_path: Path) -> None:
        """Default test runner args include -m 'not expensive' to exclude slow tests."""
        runner = TestRunner(project_root=tmp_path)
        pytest_args = runner.build_pytest_args(targets=["tests/unit"])

        args_str = " ".join(pytest_args)
        assert "not expensive" in args_str, f"Default args do not exclude expensive tests: {args_str}"

    def test_include_expensive_flag_removes_exclusion(self, tmp_path: Path) -> None:
        """When include_expensive=True, the expensive exclusion is not present."""
        runner = TestRunner(project_root=tmp_path, include_expensive=True)
        pytest_args = runner.build_pytest_args(targets=["tests/unit"])

        args_str = " ".join(pytest_args)
        assert "not expensive" not in args_str


# ---------------------------------------------------------------------------
# R2.4 — Non-worktree context runs full test suite
# ---------------------------------------------------------------------------


class TestNonWorktreeFullSuite:
    """Outside a worktree, the full test suite runs against configured targets."""

    def test_worktree_targets_configured_dirs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """In worktree context, targets are the project's configured test directories."""
        monkeypatch.setattr("teleclaude.quality.test_runner.is_worktree", lambda _p: True)

        (tmp_path / "pyproject.toml").write_text(
            "[tool.pytest.ini_options]\ntestpaths = ['tests/unit', 'tests/integration']\n",
            encoding="utf-8",
        )
        (tmp_path / "teleclaude.yml").write_text("language: python\n", encoding="utf-8")

        runner = TestRunner(project_root=tmp_path)
        targets = runner.resolve_targets()

        assert any("tests/unit" in str(t) for t in targets), f"Worktree targets do not include 'tests/unit': {targets}"

    def test_shared_branch_with_session_uses_companion_mapping(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On shared branch with session, targets come from companion mapping."""
        companion = tmp_path / "tests" / "unit" / "foo" / "test_bar.py"
        companion.parent.mkdir(parents=True)
        companion.touch()

        monkeypatch.setattr("teleclaude.quality.test_runner.is_worktree", lambda _p: False)
        monkeypatch.setattr("teleclaude.session_identity.get_session_id", lambda: "sess-123")
        monkeypatch.setattr(
            "teleclaude.quality.test_runner.resolve_session_scope",
            lambda _p: {"teleclaude/foo/bar.py"},
        )

        runner = TestRunner(project_root=tmp_path)
        targets = runner.resolve_targets()

        assert "tests/unit/foo/test_bar.py" in targets


# ---------------------------------------------------------------------------
# R2.5 — Exit non-zero on test failure
# ---------------------------------------------------------------------------


class TestExitBehavior:
    """The test command exits non-zero when any test fails."""

    def test_pytest_uses_uv_invocation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pytest runs through the uv-managed project environment."""
        calls: list[tuple[list[str], str | None, bool]] = []

        def _capture_run(cmd: list[str], cwd: str | None = None, check: bool = False) -> CompletedProcess[str]:
            calls.append((list(cmd), cwd, check))
            return CompletedProcess(args=cmd, returncode=0)

        monkeypatch.setattr("teleclaude.quality.test_runner.subprocess.run", _capture_run)

        exit_code = run_pytest(["tests/unit", "-q"], cwd=tmp_path)

        assert exit_code == 0
        assert calls == [(["uv", "run", "pytest", "tests/unit", "-q"], str(tmp_path), False)]

    def test_exits_nonzero_when_pytest_reports_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """TestRunner exits non-zero when the underlying pytest invocation returns failure."""
        monkeypatch.setattr("teleclaude.quality.test_runner.is_worktree", lambda _p: False)

        def _failing_pytest_run(*_args: object, **_kwargs: object) -> int:
            return 1  # pytest exit code 1 = tests failed

        monkeypatch.setattr("teleclaude.quality.test_runner.run_pytest", _failing_pytest_run)

        runner = TestRunner(project_root=tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            runner.run(targets=["tests/unit"])
        assert exc_info.value.code != 0

    def test_exits_zero_when_all_tests_pass(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """TestRunner exits zero when all tests pass."""
        monkeypatch.setattr("teleclaude.quality.test_runner.is_worktree", lambda _p: False)

        def _passing_pytest_run(*_args: object, **_kwargs: object) -> int:
            return 0  # pytest exit code 0 = all passed

        monkeypatch.setattr("teleclaude.quality.test_runner.run_pytest", _passing_pytest_run)

        runner = TestRunner(project_root=tmp_path)
        # Should not raise SystemExit or raise SystemExit(0)
        try:
            runner.run(targets=["tests/unit"])
        except SystemExit as exc:
            assert exc.code == 0, f"Expected exit 0 on all-passing tests, got {exc.code}"


class TestExplicitFileTargets:
    """Explicit-file mode remains language-aware instead of passing arbitrary files to pytest."""

    def test_explicit_python_source_maps_to_companion(self, tmp_path: Path) -> None:
        """A direct Python source file resolves to its existing pytest companion."""
        companion = tmp_path / "tests" / "unit" / "foo" / "test_bar.py"
        companion.parent.mkdir(parents=True)
        companion.touch()

        runner = TestRunner(project_root=tmp_path)
        targets = runner.resolve_targets(files=["teleclaude/foo/bar.py"])

        assert targets == ["tests/unit/foo/test_bar.py"]

    def test_explicit_typescript_file_runs_vitest_without_pytest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A direct TS file triggers vitest only and does not hand source files to pytest."""
        pytest_calls: list[list[str]] = []
        vitest_calls: list[bool] = []

        monkeypatch.setattr(
            "teleclaude.quality.test_runner.get_project_languages",
            lambda _path: ["python", "typescript"],
        )
        monkeypatch.setattr(
            "teleclaude.quality.test_runner.run_pytest",
            lambda args, cwd=None: pytest_calls.append(list(args)) or 0,
        )
        monkeypatch.setattr(TestRunner, "_run_vitest", lambda self_runner: vitest_calls.append(True))

        runner = TestRunner(project_root=tmp_path)
        targets = runner.resolve_targets(files=["frontend/app/foo.tsx"])
        runner.run(targets=targets)

        assert targets == []
        assert pytest_calls == []
        assert vitest_calls == [True]


# ---------------------------------------------------------------------------
# R2 DoD §5 — Path validation: no traversal or injection via session scope
# ---------------------------------------------------------------------------


class TestPathValidation:
    """File path inputs from session scope must be validated against traversal and injection."""

    def test_traversal_paths_rejected_from_session_scope(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Paths containing '../' traversal sequences from session scope are rejected or stripped."""
        malicious_files = ["../../etc/passwd", "teleclaude/../../../shadow", "../traversal.py"]

        monkeypatch.setattr("teleclaude.quality.test_runner.is_worktree", lambda _p: True)
        monkeypatch.setattr(
            "teleclaude.quality.test_runner.resolve_session_scope",
            lambda _p: set(malicious_files),
        )

        runner = TestRunner(project_root=tmp_path)
        # Either raises on invalid paths or filters them out
        try:
            targets = runner.resolve_targets()
        except (SystemExit, ValueError, RuntimeError):
            return  # Raising on traversal paths is a valid response

        # If it didn't raise, traversal paths must have been filtered
        for t in targets:
            assert ".." not in str(t), f"Traversal path '{t}' in test targets — path validation failed"

    def test_absolute_paths_outside_project_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Absolute paths outside the project root from session scope are rejected or stripped."""
        malicious_files = ["/etc/passwd", "/tmp/evil.py"]

        monkeypatch.setattr("teleclaude.quality.test_runner.is_worktree", lambda _p: True)
        monkeypatch.setattr(
            "teleclaude.quality.test_runner.resolve_session_scope",
            lambda _p: set(malicious_files),
        )

        runner = TestRunner(project_root=tmp_path)
        try:
            targets = runner.resolve_targets()
        except (SystemExit, ValueError, RuntimeError):
            return  # Raising on invalid paths is a valid response

        # Absolute paths outside project must be filtered
        for t in targets:
            t_str = str(t)
            assert not t_str.startswith("/") or t_str.startswith(str(tmp_path)), (
                f"Absolute path '{t_str}' outside project root in test targets"
            )


# ---------------------------------------------------------------------------
# Vitest scoping — only run vitest when TypeScript files are in scope
# ---------------------------------------------------------------------------


class TestVitestScoping:
    """vitest only runs when TypeScript files are in scope or running full suite."""

    def test_vitest_skipped_for_python_only_session_scope(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On shared branch with session scope of only Python files, vitest is not invoked."""
        vitest_calls: list[object] = []

        monkeypatch.setattr("teleclaude.quality.test_runner.is_worktree", lambda _p: False)
        monkeypatch.setattr("teleclaude.session_identity.get_session_id", lambda: "sess-123")
        monkeypatch.setattr(
            "teleclaude.quality.test_runner.resolve_session_scope",
            lambda _p: ["teleclaude/foo.py", "tests/unit/test_foo.py"],
        )
        monkeypatch.setattr("teleclaude.quality.test_runner.run_pytest", lambda _args, cwd=None: 0)
        monkeypatch.setattr(
            "teleclaude.quality.test_runner.get_project_languages",
            lambda _p: ["python", "typescript"],
        )

        # Create the test companion so resolve_targets finds it
        test_file = tmp_path / "tests" / "unit" / "test_foo.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("", encoding="utf-8")

        def _spy_vitest(self_runner: TestRunner) -> None:
            vitest_calls.append(True)

        monkeypatch.setattr(TestRunner, "_run_vitest", _spy_vitest)

        runner = TestRunner(project_root=tmp_path)
        targets = runner.resolve_targets()
        runner.run(targets=targets)

        assert len(vitest_calls) == 0, "vitest should NOT run when scope has only Python files"

    def test_vitest_runs_when_typescript_files_in_session_scope(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On shared branch with session scope including TypeScript files, vitest is invoked."""
        vitest_calls: list[object] = []

        monkeypatch.setattr("teleclaude.quality.test_runner.is_worktree", lambda _p: False)
        monkeypatch.setattr("teleclaude.session_identity.get_session_id", lambda: "sess-123")
        monkeypatch.setattr(
            "teleclaude.quality.test_runner.resolve_session_scope",
            lambda _p: ["teleclaude/foo.py", "frontend/app/bar.tsx"],
        )
        monkeypatch.setattr("teleclaude.quality.test_runner.run_pytest", lambda _args, cwd=None: 0)
        monkeypatch.setattr(
            "teleclaude.quality.test_runner.get_project_languages",
            lambda _p: ["python", "typescript"],
        )

        # Create the test companion so resolve_targets finds something
        test_file = tmp_path / "tests" / "unit" / "test_foo.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("", encoding="utf-8")

        def _spy_vitest(self_runner: TestRunner) -> None:
            vitest_calls.append(True)

        monkeypatch.setattr(TestRunner, "_run_vitest", _spy_vitest)

        runner = TestRunner(project_root=tmp_path)
        targets = runner.resolve_targets()
        runner.run(targets=targets)

        assert len(vitest_calls) == 1, "vitest SHOULD run when scope includes TypeScript files"
