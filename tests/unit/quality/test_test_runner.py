"""Tests for R2: telec code test command.

Behavioral contracts for the telec code test command: language-aware test execution
with automatic worktree scoping and companion file mapping.
"""

from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess

import pytest

from teleclaude.quality.scope import DirtyOp, DirtyPath, WorkspaceScopeKind, WorkspaceScopeResolution
from teleclaude.quality.test_runner import TestRunner, map_source_to_companion, resolve_test_targets, run_pytest

PACKAGE_STORAGE = "storage"
PACKAGE_WORKFLOW = "workflow"
WORKFLOW_SOURCE = "crates/workflow/src/lib.rs"
STORAGE_SOURCE = "crates/storage/src/lib.rs"
PYTHON_SOURCE = "teleclaude/foo.py"
PYTHON_TEST = "tests/unit/test_foo.py"
TYPESCRIPT_SOURCE = "frontend/app/foo.tsx"


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
# R2.1 — Companion file mapping convention
# ---------------------------------------------------------------------------


class TestCompanionMapping:
    """Session-touched source files are mapped to their test companions."""

    # guard: parametrize-cleanup-pending
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

    def test_touched_snapshot_file_not_included_directly(self, tmp_path: Path) -> None:
        """Snapshot artifacts are test data, not pytest collection targets."""
        snapshot_file = tmp_path / "tests" / "unit" / "__snapshots__" / "test_foo.ambr"
        snapshot_file.parent.mkdir(parents=True)
        snapshot_file.touch()

        targets = resolve_test_targets(
            project_root=tmp_path,
            touched_files={"tests/unit/__snapshots__/test_foo.ambr"},
        )
        assert targets == []


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
    """Shared branches without session identity run configured targets."""

    def test_worktree_maps_resolved_dirty_existing_paths_to_companions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        companion = tmp_path / "tests" / "unit" / "foo" / "test_bar.py"
        companion.parent.mkdir(parents=True)
        companion.touch()

        monkeypatch.setattr(
            "teleclaude.quality.test_runner.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.WORKTREE,
                scoped_existing_paths=("teleclaude/foo/bar.py",),
            ),
        )

        runner = TestRunner(project_root=tmp_path)
        targets = runner.resolve_targets()

        assert targets == ["tests/unit/foo/test_bar.py"]

    def test_shared_branch_without_session_targets_configured_dirs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "teleclaude.quality.test_runner.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.SHARED_BRANCH,
                scoped_existing_paths=(),
                has_session_identity=False,
            ),
        )

        (tmp_path / "pyproject.toml").write_text(
            "[tool.pytest.ini_options]\ntestpaths = ['tests/unit', 'tests/integration']\n",
            encoding="utf-8",
        )
        (tmp_path / "teleclaude.yml").write_text("language: python\n", encoding="utf-8")

        runner = TestRunner(project_root=tmp_path)
        targets = runner.resolve_targets()

        assert any("tests/unit" in str(t) for t in targets), f"Targets do not include 'tests/unit': {targets}"

    def test_shared_branch_with_session_uses_companion_mapping(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On shared branch with session, targets come from companion mapping."""
        companion = tmp_path / "tests" / "unit" / "foo" / "test_bar.py"
        companion.parent.mkdir(parents=True)
        companion.touch()

        monkeypatch.setattr(
            "teleclaude.quality.test_runner.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.SHARED_BRANCH,
                scoped_existing_paths=("teleclaude/foo/bar.py",),
            ),
        )

        runner = TestRunner(project_root=tmp_path)
        targets = runner.resolve_targets()

        assert "tests/unit/foo/test_bar.py" in targets


# ---------------------------------------------------------------------------
# R2.5 — Exit non-zero on test failure
# ---------------------------------------------------------------------------


class TestExitBehavior:
    """The test command exits non-zero when any test fails."""

    def test_pytest_uses_uv_invocation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pytest runs through the uv-managed project environment as a session leader."""
        popen_calls: list[tuple[list[str], str | None, bool]] = []

        class _FakeProc:
            pid = 12345

            def wait(self, timeout: int | None = None) -> int:
                return 0

        def _capture_popen(cmd: list[str], **kwargs: object) -> _FakeProc:
            popen_calls.append((list(cmd), kwargs.get("cwd"), kwargs.get("start_new_session", False)))
            return _FakeProc()

        def _stub_run(*_args: object, **_kwargs: object) -> CompletedProcess[str]:
            return CompletedProcess(args=[], returncode=0)

        monkeypatch.setattr("teleclaude.quality.test_runner.subprocess.Popen", _capture_popen)
        monkeypatch.setattr("teleclaude.quality.test_runner.subprocess.run", _stub_run)

        exit_code = run_pytest(["tests/unit", "-q"], cwd=tmp_path)

        assert exit_code == 0
        assert popen_calls == [(["uv", "run", "pytest", "tests/unit", "-q"], str(tmp_path), True)]

    def test_exits_nonzero_when_pytest_reports_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """TestRunner exits non-zero when the underlying pytest invocation returns failure."""

        def _failing_pytest_run(*_args: object, **_kwargs: object) -> int:
            return 1  # pytest exit code 1 = tests failed

        monkeypatch.setattr("teleclaude.quality.test_runner.run_pytest", _failing_pytest_run)

        runner = TestRunner(project_root=tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            runner.run(targets=["tests/unit"])
        assert exc_info.value.code != 0

    def test_exits_zero_when_all_tests_pass(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """TestRunner exits zero when all tests pass."""

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

        monkeypatch.setattr(
            "teleclaude.quality.test_runner.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.WORKTREE,
                scoped_existing_paths=tuple(malicious_files),
            ),
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

        monkeypatch.setattr(
            "teleclaude.quality.test_runner.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.WORKTREE,
                scoped_existing_paths=tuple(malicious_files),
            ),
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

        monkeypatch.setattr(
            "teleclaude.quality.test_runner.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.SHARED_BRANCH,
                scoped_existing_paths=("teleclaude/foo.py", "tests/unit/test_foo.py"),
            ),
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

        monkeypatch.setattr(
            "teleclaude.quality.test_runner.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.SHARED_BRANCH,
                scoped_existing_paths=("teleclaude/foo.py", "frontend/app/bar.tsx"),
            ),
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


class TestRustTestRunner:
    """TestRunner dispatches cargo test when Rust is declared."""

    def test_single_crate_scope_invokes_package_cargo_test(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Single-crate Rust scope runs cargo test -p package."""
        _write_rust_workspace(tmp_path)
        cargo_calls: list[tuple[list[str], Path]] = []
        pytest_calls: list[list[str]] = []

        monkeypatch.setattr("teleclaude.quality.test_runner.get_project_languages", lambda _path: ["rust"])
        monkeypatch.setattr(
            "teleclaude.quality.test_runner.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.WORKTREE,
                scoped_existing_paths=(WORKFLOW_SOURCE,),
            ),
        )
        monkeypatch.setattr(
            "teleclaude.quality.test_runner.run_pytest",
            lambda args, cwd=None: pytest_calls.append(list(args)) or 0,
        )
        monkeypatch.setattr(
            "teleclaude.quality.test_runner.subprocess.run",
            lambda cmd, cwd, check=False: cargo_calls.append((list(cmd), Path(cwd))) or CompletedProcess(cmd, 0),
        )

        runner = TestRunner(project_root=tmp_path)
        targets = runner.resolve_targets()
        runner.run(targets=targets)

        assert pytest_calls == []
        assert cargo_calls == [(["cargo", "test", "-p", PACKAGE_WORKFLOW], tmp_path)]

    def test_cross_crate_scope_invokes_workspace_cargo_test(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cross-crate Rust scope runs cargo test --workspace."""
        _write_rust_workspace(tmp_path)
        cargo_calls: list[tuple[list[str], Path]] = []

        monkeypatch.setattr("teleclaude.quality.test_runner.get_project_languages", lambda _path: ["rust"])
        monkeypatch.setattr(
            "teleclaude.quality.test_runner.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.WORKTREE,
                scoped_existing_paths=(WORKFLOW_SOURCE, STORAGE_SOURCE),
            ),
        )
        monkeypatch.setattr(
            "teleclaude.quality.test_runner.subprocess.run",
            lambda cmd, cwd, check=False: cargo_calls.append((list(cmd), Path(cwd))) or CompletedProcess(cmd, 0),
        )

        runner = TestRunner(project_root=tmp_path)
        targets = runner.resolve_targets()
        runner.run(targets=targets)

        assert cargo_calls == [(["cargo", "test", "--workspace"], tmp_path)]

    def test_run_all_invokes_workspace_cargo_test(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--all Rust test runs cargo test --workspace."""
        _write_rust_workspace(tmp_path)
        cargo_calls: list[tuple[list[str], Path]] = []
        pytest_calls: list[list[str]] = []

        monkeypatch.setattr("teleclaude.quality.test_runner.get_project_languages", lambda _path: ["rust"])
        monkeypatch.setattr(
            "teleclaude.quality.test_runner.run_pytest",
            lambda args, cwd=None: pytest_calls.append(list(args)) or 0,
        )
        monkeypatch.setattr(
            "teleclaude.quality.test_runner.subprocess.run",
            lambda cmd, cwd, check=False: cargo_calls.append((list(cmd), Path(cwd))) or CompletedProcess(cmd, 0),
        )

        runner = TestRunner(project_root=tmp_path)
        targets = runner.resolve_targets(run_all=True)
        runner.run(targets=targets)

        assert pytest_calls == []
        assert cargo_calls == [(["cargo", "test", "--workspace"], tmp_path)]

    def test_mixed_python_and_rust_runs_pytest_and_cargo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mixed Python+Rust scope runs pytest companions and cargo test."""
        _write_rust_workspace(tmp_path)
        (tmp_path / PYTHON_TEST).parent.mkdir(parents=True)
        (tmp_path / PYTHON_TEST).touch()
        cargo_calls: list[tuple[list[str], Path]] = []
        pytest_calls: list[list[str]] = []

        monkeypatch.setattr("teleclaude.quality.test_runner.get_project_languages", lambda _path: ["python", "rust"])
        monkeypatch.setattr(
            "teleclaude.quality.test_runner.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.WORKTREE,
                scoped_existing_paths=(PYTHON_SOURCE, WORKFLOW_SOURCE),
            ),
        )
        monkeypatch.setattr(
            "teleclaude.quality.test_runner.run_pytest",
            lambda args, cwd=None: pytest_calls.append(list(args)) or 0,
        )
        monkeypatch.setattr(
            "teleclaude.quality.test_runner.subprocess.run",
            lambda cmd, cwd, check=False: cargo_calls.append((list(cmd), Path(cwd))) or CompletedProcess(cmd, 0),
        )

        runner = TestRunner(project_root=tmp_path)
        targets = runner.resolve_targets()
        runner.run(targets=targets)

        assert pytest_calls == [[PYTHON_TEST, "-m", "not expensive", "-q"]]
        assert cargo_calls == [(["cargo", "test", "-p", PACKAGE_WORKFLOW], tmp_path)]

    def test_rust_only_scope_does_not_exit_when_no_python_companions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Rust-only scoped files bypass the old no-Python-companion early exit."""
        _write_rust_workspace(tmp_path)
        cargo_calls: list[tuple[list[str], Path]] = []

        monkeypatch.setattr("teleclaude.quality.test_runner.get_project_languages", lambda _path: ["rust"])
        monkeypatch.setattr(
            "teleclaude.quality.test_runner.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.WORKTREE,
                scoped_existing_paths=(WORKFLOW_SOURCE,),
            ),
        )
        monkeypatch.setattr(
            "teleclaude.quality.test_runner.subprocess.run",
            lambda cmd, cwd, check=False: cargo_calls.append((list(cmd), Path(cwd))) or CompletedProcess(cmd, 0),
        )

        runner = TestRunner(project_root=tmp_path)
        targets = runner.resolve_targets()
        runner.run(targets=targets)

        assert cargo_calls == [(["cargo", "test", "-p", PACKAGE_WORKFLOW], tmp_path)]

    def test_python_only_project_does_not_invoke_cargo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Rust-looking paths do not run cargo when rust is absent."""
        _write_rust_workspace(tmp_path)
        (tmp_path / PYTHON_TEST).parent.mkdir(parents=True)
        (tmp_path / PYTHON_TEST).touch()
        cargo_calls: list[tuple[list[str], Path]] = []

        monkeypatch.setattr("teleclaude.quality.test_runner.get_project_languages", lambda _path: ["python"])
        monkeypatch.setattr(
            "teleclaude.quality.test_runner.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.WORKTREE,
                scoped_existing_paths=(PYTHON_SOURCE, WORKFLOW_SOURCE),
            ),
        )
        monkeypatch.setattr("teleclaude.quality.test_runner.run_pytest", lambda _args, cwd=None: 0)
        monkeypatch.setattr(
            "teleclaude.quality.test_runner.subprocess.run",
            lambda cmd, cwd, check=False: cargo_calls.append((list(cmd), Path(cwd))) or CompletedProcess(cmd, 0),
        )

        runner = TestRunner(project_root=tmp_path)
        targets = runner.resolve_targets()
        runner.run(targets=targets)

        assert cargo_calls == []

    def test_typescript_scope_still_runs_vitest_without_cargo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Vitest behavior remains unchanged and independent from Rust."""
        vitest_calls: list[bool] = []
        cargo_calls: list[tuple[list[str], Path]] = []

        monkeypatch.setattr("teleclaude.quality.test_runner.get_project_languages", lambda _path: ["typescript"])
        monkeypatch.setattr(
            "teleclaude.quality.test_runner.resolve_workspace_scope_resolution",
            lambda _path: _workspace_resolution(
                kind=WorkspaceScopeKind.WORKTREE,
                scoped_existing_paths=(TYPESCRIPT_SOURCE,),
            ),
        )
        monkeypatch.setattr(TestRunner, "_run_vitest", lambda self_runner: vitest_calls.append(True))
        monkeypatch.setattr(
            "teleclaude.quality.test_runner.subprocess.run",
            lambda cmd, cwd, check=False: cargo_calls.append((list(cmd), Path(cwd))) or CompletedProcess(cmd, 0),
        )

        runner = TestRunner(project_root=tmp_path)
        targets = runner.resolve_targets()
        runner.run(targets=targets)

        assert vitest_calls == [True]
        assert cargo_calls == []

    def test_explicit_empty_rust_scope_skips_cargo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """File-scoped runs with no Rust-owned paths skip cargo test."""
        _write_rust_workspace(tmp_path)
        cargo_calls: list[tuple[list[str], Path]] = []

        monkeypatch.setattr("teleclaude.quality.test_runner.get_project_languages", lambda _path: ["rust"])
        monkeypatch.setattr(
            "teleclaude.quality.test_runner.subprocess.run",
            lambda cmd, cwd, check=False: cargo_calls.append((list(cmd), Path(cwd))) or CompletedProcess(cmd, 0),
        )

        runner = TestRunner(project_root=tmp_path)
        targets = runner.resolve_targets(files=["docs/x.md"])
        runner.run(targets=targets)

        assert cargo_calls == []
