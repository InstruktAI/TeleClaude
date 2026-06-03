"""Test runner — the ``telec code test`` implementation.

Context-aware test execution with companion file mapping and multi-language
test dispatch (pytest + vitest). See design doc
``software-development/design/workspace-scoping`` for the scoping contract.
"""

from __future__ import annotations

import logging
import resource
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

from teleclaude.quality import test_watchdog
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


def map_source_to_companion(source_path: str) -> str:
    """Map a source file to its test companion.

    ``teleclaude/x/y.py`` becomes ``tests/unit/x/test_y.py``.
    """
    parts = source_path.split("/")
    if len(parts) < 2:
        return f"tests/unit/test_{parts[0]}"
    # Strip leading package directory, prepend tests/unit/, prefix filename with test_
    subpath = parts[1:]
    subpath[-1] = f"test_{subpath[-1]}"
    return "tests/unit/" + "/".join(subpath)


def resolve_test_targets(project_root: Path, touched_files: set[str]) -> list[str]:
    """Map source files to companion test files, include directly-touched tests.

    Companions that do not exist on disk are omitted. Results are deduplicated
    and sorted for determinism.
    """
    targets: set[str] = set()

    for f in touched_files:
        if f.startswith("tests/") and f.endswith(".py"):
            if (project_root / f).exists():
                targets.add(f)
        elif f.endswith(".py"):
            companion = map_source_to_companion(f)
            if (project_root / companion).exists():
                targets.add(companion)

    return sorted(targets)


def run_pytest(args: list[str], cwd: Path | None = None) -> int:
    """Run pytest with the given arguments. Returns exit code.

    Three-layer hang defense:
    - Per-test ``timeout`` (unit=1s, functional/integration=5s in
      ``tests/conftest.py``) flags a runaway test body via pytest-timeout.
    - Master-process watchdog (``teleclaude.quality.test_watchdog``) polls
      ``${TMPDIR}/teleclaude_pytest_worker_*.json`` every 500 ms and SIGKILLs
      any xdist worker whose current test has exceeded 2x its tier budget,
      logging the offending nodeid before the kill. Sits outside the worker
      so a syscall-level deadlock cannot suppress the diagnostic.
    - ``session_timeout = 35`` (pyproject) caps total wall clock as a backstop;
      ``pytest_sessionfinish`` / ``pytest_keyboard_interrupt`` print per-worker
      in-flight tests at that instant.

    Sweeps zombie pytest trees from prior runs before invoking, and cleans up
    leftover worker files on exit.

    Justified subprocess: pytest is an external tool invocation.
    Per ``software-development/policy/test-resource-discipline`` rules 14-15.
    """
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        if soft < 4096:
            resource.setrlimit(resource.RLIMIT_NOFILE, (min(4096, hard), hard))
    except (OSError, ValueError) as exc:
        # Best-effort: a low fd limit only risks "too many open files" under heavy
        # xdist fan-out; surface it without aborting the run.
        logger.warning("Could not raise file-descriptor limit for pytest: %s", exc)
    subprocess.run(["pkill", "-9", "-f", "pytest tests"], check=False)
    subprocess.run(["pkill", "-9", "-f", "uv run pytest"], check=False)
    test_watchdog.cleanup_inflight_files()
    proc = subprocess.Popen(
        ["uv", "run", "pytest", *args],
        cwd=str(cwd) if cwd else None,
        start_new_session=True,
    )
    try:
        poller = test_watchdog.WatchdogPoller(pytest_proc_poll=proc.poll)
        return poller.poll_until_exit()
    finally:
        test_watchdog.cleanup_inflight_files()


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
            logger.info("No test companions found for scoped files — skipping")
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
        """Run pytest for declared Python or legacy no-language projects."""
        return not languages or "python" in languages

    def _has_non_python_scoped_tests(self) -> bool:
        languages = get_project_languages(self._project_root)
        return ("typescript" in languages and bool(typescript_files(list(self._scoped_files)))) or (
            "rust" in languages and self._rust_scope_kind() is not RustScopeKind.EMPTY
        )

    def _run_vitest(self) -> None:
        """Run vitest for TypeScript tests from frontend_root."""
        frontend_root = self._resolve_frontend_root()
        if not frontend_root.exists():
            logger.info("Frontend root %s does not exist — skipping vitest", frontend_root)
            return
        logger.info("Running vitest from %s", frontend_root)
        # Justified subprocess: vitest is an external Node.js tool with no Python API
        vitest_args = ["-u", "--run"] if self._update_snapshots else ["run"]
        vitest_args.extend(["--config", "vitest.cli.config.ts"])
        result = subprocess.run(["npx", "--yes", "vitest", *vitest_args], cwd=str(frontend_root), check=False)
        if result.returncode != 0:
            logger.error("vitest failed (exit %d)", result.returncode)
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
        return ["tests/unit", "tests/integration"]


def _cargo_test_command(scope: RustScope) -> list[str]:
    if scope.kind is RustScopeKind.PACKAGE and scope.package is not None:
        return ["cargo", "test", "-p", scope.package, "--lib"]
    return ["cargo", "test", "--workspace", "--lib"]


def _rust_cwd(scope: RustScope) -> Path:
    if scope.workspace_root is None:
        raise RuntimeError("Rust scope has no workspace root")
    return scope.workspace_root
