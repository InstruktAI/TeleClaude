"""Test runner — the ``telec code test`` implementation.

Context-aware test execution with companion file mapping and multi-language
test dispatch (pytest + vitest). See design doc
``software-development/design/workspace-scoping`` for the scoping contract.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

from teleclaude.quality.package_manager import commands_for
from teleclaude.quality.scope import (
    CargoWorkspaceError,
    RustScope,
    RustScopeKind,
    WorkspaceScopeKind,
    WorkspaceScopeResolution,
    get_project_languages,
    resolve_rust_scope,
    resolve_workspace_scope_resolution,
    typescript_files,
    validate_scoped_paths,
)

logger = logging.getLogger(__name__)


def resolve_test_targets(project_root: Path, touched_files: set[str]) -> list[str]:
    """Return the changed test files themselves, deduplicated and sorted.

    The spec-anchored model has no per-source companion file, so changed source
    files yield no targets here; the caller runs the full lean suite in that case.
    """
    targets = {f for f in touched_files if f.startswith("tests/") and f.endswith(".py") and (project_root / f).exists()}
    return sorted(targets)


def run_pytest(args: list[str], cwd: Path | None = None) -> int:
    """Run pytest with the given arguments. Returns its exit code."""
    result = subprocess.run(["uv", "run", "pytest", *args], cwd=str(cwd) if cwd else None, check=False)
    return result.returncode


class TestRunner:
    """Orchestrates context-aware test execution.

    File target resolution follows the workspace-scoping design:
    explicit files bypass scoping, worktrees use dirty existing files,
    and shared branches session-scope to companion-mapped test files.
    """

    def __init__(
        self,
        project_root: Path,
        update_snapshots: bool = False,
    ) -> None:
        self._project_root = project_root
        self._update_snapshots = update_snapshots
        self._is_full_suite = True
        self._scoped_files: set[str] = set()

    def resolve_targets(self, files: list[str] | None = None, *, run_all: bool = False) -> list[str]:
        """Resolve the test targets based on execution context.

        Args:
            files: Explicit file targets. When provided, all scoping is
                   bypassed — files are validated and returned directly.
            run_all: When True, skip scoping and run all configured test
                     directories (equivalent to Makefile invocation).
        """
        if files is not None:
            validated = validate_scoped_paths(files, self._project_root)
            if not validated and files:
                logger.error("All provided files rejected by path validation")
                sys.exit(1)
            if validated:
                logger.info("Explicit files provided — bypassing scoping (%d files)", len(validated))
                self._is_full_suite = False
                self._scoped_files = set(validated)
                return resolve_test_targets(self._project_root, self._scoped_files)
            return []

        if run_all:
            logger.info("--all flag — using configured test directories")
            self._is_full_suite = True
            return self._read_configured_test_paths()

        return self._resolve_workspace_targets()

    def _resolve_workspace_targets(self) -> list[str]:
        scope_resolution = self._resolve_workspace_scope_resolution()
        if scope_resolution.kind is WorkspaceScopeKind.SHARED_BRANCH and not scope_resolution.has_session_identity:
            logger.info("No session identity — using configured test directories")
            self._is_full_suite = True
            return self._read_configured_test_paths()

        self._is_full_suite = False
        validated = validate_scoped_paths(list(scope_resolution.scoped_existing_paths), self._project_root)
        self._scoped_files = set(validated)
        targets = resolve_test_targets(self._project_root, self._scoped_files)
        if not targets and not self._has_non_python_scoped_tests():
            # The spec-anchored model has no per-source companion file. If the change
            # touched Python at all, run the full (lean) suite rather than silently
            # skipping; only skip when nothing Python is in scope.
            if any(f.endswith(".py") for f in self._scoped_files):
                logger.info("No scoped companion — running the full Python suite")
                self._is_full_suite = True
                return self._read_configured_test_paths()
            logger.info("No Python test targets in scope — skipping")
            sys.exit(0)
        return targets

    def _resolve_workspace_scope_resolution(self) -> WorkspaceScopeResolution:
        try:
            return resolve_workspace_scope_resolution(self._project_root)
        except (RuntimeError, OSError) as exc:
            logger.error(
                "Workspace scope unavailable. Pass files explicitly: telec code test <files...>\nReason: %s",
                exc,
            )
            sys.exit(1)

    def build_pytest_args(self, targets: list[str]) -> list[str]:
        """Construct pytest CLI arguments from targets and configuration."""
        args = list(targets)
        if self._update_snapshots:
            args.append("--snapshot-update")
        return args

    def run(self, targets: list[str] | None = None) -> None:
        """Run pytest against the given or resolved targets, then vitest if TS is configured."""
        if targets is None:
            targets = self.resolve_targets()

        # Run TypeScript tests when configured AND relevant
        languages = get_project_languages(self._project_root)
        should_run_pytest = self._should_run_pytest(languages)
        should_run_vitest = "typescript" in languages and self._should_run_vitest()
        should_run_rust = "rust" in languages and self._should_run_rust_tests()

        if targets and should_run_pytest:
            args = self.build_pytest_args(targets)
            exit_code = run_pytest(args, cwd=self._project_root)
            if exit_code != 0:
                sys.exit(exit_code)
        elif not should_run_vitest and not should_run_rust:
            logger.info("No Python test targets in scope — skipping pytest")

        if should_run_vitest:
            self._run_vitest()

        if should_run_rust:
            self._run_cargo_test()

    def _should_run_vitest(self) -> bool:
        """Determine whether vitest should run based on scope context.

        Full suite (non-worktree): always run vitest.
        Targeted (worktree): only if scoped files include TypeScript sources.
        """
        if self._is_full_suite:
            return True
        return bool(typescript_files(list(self._scoped_files)))

    def _should_run_pytest(self, languages: list[str]) -> bool:
        return "python" in languages

    def _has_non_python_scoped_tests(self) -> bool:
        languages = get_project_languages(self._project_root)
        return ("typescript" in languages and bool(typescript_files(list(self._scoped_files)))) or (
            "rust" in languages and self._rust_scope_kind() is not RustScopeKind.EMPTY
        )

    def _run_vitest(self) -> None:
        """Run the frontend test suite via its declared package.json ``test`` script."""
        frontend_root = self._resolve_frontend_root()
        if not frontend_root.exists():
            logger.info("Frontend root %s does not exist — skipping frontend tests", frontend_root)
            return
        commands = commands_for(frontend_root)
        logger.info("Running frontend tests via %s from %s", commands.manager.value, frontend_root)
        # The frontend owns its runner and config in package.json; invoke its
        # ``test`` script. Snapshot updates forward through to the underlying runner.
        cmd = commands.run_script("test", ["-u"] if self._update_snapshots else [])
        result = subprocess.run(cmd, cwd=str(frontend_root), check=False)
        if result.returncode != 0:
            logger.error("frontend tests failed (exit %d)", result.returncode)
            sys.exit(result.returncode)

    def _should_run_rust_tests(self) -> bool:
        """Determine whether cargo test should run based on scope context."""
        if self._is_full_suite:
            return True
        return self._rust_scope_kind() is not RustScopeKind.EMPTY

    def _rust_scope_kind(self) -> RustScopeKind:
        return self._resolve_rust_scope().kind

    def _run_cargo_test(self) -> None:
        """Run cargo test for package or workspace Rust scope."""
        scope = self._resolve_rust_scope()
        if scope.kind is RustScopeKind.EMPTY:
            return
        cmd = _cargo_test_command(scope)
        logger.info("Running cargo test from %s", _rust_cwd(scope))
        # Justified subprocess: cargo test is an external Rust tool with no Python API.
        result = subprocess.run(cmd, cwd=str(_rust_cwd(scope)), check=False)
        if result.returncode != 0:
            logger.error("cargo test failed (exit %d)", result.returncode)
            sys.exit(result.returncode)

    def _resolve_rust_scope(self) -> RustScope:
        try:
            return resolve_rust_scope(
                self._project_root,
                list(self._scoped_files),
                run_all=self._is_full_suite,
            )
        except CargoWorkspaceError as exc:
            logger.error("Rust workspace unavailable: %s", exc)
            raise SystemExit(1) from exc

    def _resolve_frontend_root(self) -> Path:
        """Read frontend_root from teleclaude.yml, defaulting to 'frontend'."""
        config_path = self._project_root / "teleclaude.yml"
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                fr = data.get("frontend_root")
                if fr:
                    return self._project_root / str(fr)
        return self._project_root / "frontend"

    def _read_configured_test_paths(self) -> list[str]:
        """Read testpaths from [tool.pytest.ini_options] in pyproject.toml."""
        pyproject = self._project_root / "pyproject.toml"
        if pyproject.exists():
            with open(pyproject, "rb") as f:
                data = tomllib.load(f)
            testpaths = data.get("tool", {}).get("pytest", {}).get("ini_options", {}).get("testpaths", [])
            if testpaths:
                return list(testpaths)
        return ["tests"]


def _cargo_test_command(scope: RustScope) -> list[str]:
    if scope.kind is RustScopeKind.PACKAGE and scope.package is not None:
        return ["cargo", "test", "-p", scope.package, "--lib"]
    return ["cargo", "test", "--workspace", "--lib"]


def _rust_cwd(scope: RustScope) -> Path:
    if scope.workspace_root is None:
        raise RuntimeError("Rust scope has no workspace root")
    return scope.workspace_root
