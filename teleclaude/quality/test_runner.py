"""Test runner — the ``telec test`` implementation.

Context-aware test execution with companion file mapping, expensive test
exclusion, and multi-language test dispatch (pytest + vitest). See design doc
``software-development/design/session-file-scoping`` for the scoping
contract.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

from teleclaude.quality.scope import (
    get_project_languages,
    is_worktree,
    resolve_session_scope,
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
        if f.startswith("tests/"):
            if (project_root / f).exists():
                targets.add(f)
        elif f.endswith(".py"):
            companion = map_source_to_companion(f)
            if (project_root / companion).exists():
                targets.add(companion)

    return sorted(targets)


def run_pytest(args: list[str]) -> int:
    """Run pytest with the given arguments. Returns exit code.

    Justified subprocess: pytest is an external tool invocation.
    """
    result = subprocess.run(["pytest", *args], check=False)
    return result.returncode


class TestRunner:
    """Orchestrates context-aware test execution.

    File target resolution follows the session-file-scoping design:
    explicit files bypass scoping, worktrees run configured test dirs,
    shared branches session-scope to companion-mapped test files.
    """

    def __init__(self, project_root: Path, include_expensive: bool = False) -> None:
        self._project_root = project_root
        self._include_expensive = include_expensive
        self._is_full_suite = True
        self._scoped_files: set[str] = set()

    def resolve_targets(self, files: list[str] | None = None) -> list[str]:
        """Resolve the test targets based on execution context.

        Args:
            files: Explicit file targets. When provided, all scoping is
                   bypassed — files are validated and returned directly.
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
            return validated

        if is_worktree(self._project_root):
            logger.info("Worktree detected — using configured test directories")
            self._is_full_suite = True
            return self._read_configured_test_paths()

        return self._resolve_shared_branch_targets()

    def _resolve_shared_branch_targets(self) -> list[str]:
        """Resolve targets on a shared branch: session-scoped or configured dirs.

        With a session identity, scope to companion tests of transcript-touched files.
        Without a session identity (human/CI), fall back to configured test dirs.
        With a session identity but scope failure, exit with guidance.
        """
        from teleclaude.session_identity import (  # pylint: disable=import-outside-toplevel  # deferred: heavy transitive imports
            get_session_id,
        )

        session_id = get_session_id()
        if not session_id:
            logger.info("No session identity — using configured test directories")
            self._is_full_suite = True
            return self._read_configured_test_paths()

        logger.info("Shared branch with session — scoping to companion tests")
        self._is_full_suite = False
        try:
            scoped = resolve_session_scope(self._project_root)
        except (RuntimeError, OSError) as exc:
            logger.error(
                "Session scope unavailable. Pass files explicitly: telec test <files...>\nReason: %s",
                exc,
            )
            sys.exit(1)
        validated = validate_scoped_paths(list(scoped), self._project_root)
        self._scoped_files = set(validated)
        targets = resolve_test_targets(self._project_root, self._scoped_files)
        if not targets:
            logger.info("No test companions found for session-touched files — skipping")
            sys.exit(0)
        return targets

    def build_pytest_args(self, targets: list[str]) -> list[str]:
        """Construct pytest CLI arguments from targets and configuration."""
        args = list(targets)
        if not self._include_expensive:
            args.extend(["-m", "not expensive"])
        args.append("-q")
        return args

    def run(self, targets: list[str] | None = None) -> None:
        """Run pytest against the given or resolved targets, then vitest if TS is configured."""
        if targets is None:
            targets = self.resolve_targets()
        args = self.build_pytest_args(targets)
        exit_code = run_pytest(args)
        if exit_code != 0:
            sys.exit(exit_code)

        # Run TypeScript tests when configured AND relevant
        languages = get_project_languages(self._project_root)
        if "typescript" in languages and self._should_run_vitest():
            self._run_vitest()

    def _should_run_vitest(self) -> bool:
        """Determine whether vitest should run based on scope context.

        Full suite (non-worktree): always run vitest.
        Targeted (worktree): only if scoped files include TypeScript sources.
        """
        if self._is_full_suite:
            return True
        ts_exts = (".ts", ".tsx", ".js", ".jsx")
        return any(f.endswith(ts_exts) for f in self._scoped_files)

    def _run_vitest(self) -> None:
        """Run vitest for TypeScript tests from frontend_root."""
        frontend_root = self._resolve_frontend_root()
        if not frontend_root.exists():
            logger.info("Frontend root %s does not exist — skipping vitest", frontend_root)
            return
        logger.info("Running vitest from %s", frontend_root)
        # Justified subprocess: vitest is an external Node.js tool with no Python API
        result = subprocess.run(["npx", "--yes", "vitest", "run"], cwd=str(frontend_root), check=False)
        if result.returncode != 0:
            logger.error("vitest failed (exit %d)", result.returncode)
            sys.exit(result.returncode)

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
