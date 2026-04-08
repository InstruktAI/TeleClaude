# guard: no-companion
"""Contract tests for worktree-scoped shell commands and staged pre-commit hooks."""

from __future__ import annotations

import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LINT_SH = _REPO_ROOT / "tools" / "lint.sh"
_TEST_SH = _REPO_ROOT / "tools" / "test.sh"
_PRECOMMIT_SH = _REPO_ROOT / "tools" / "lint" / "precommit-hook.sh"
_PRECOMMIT_CONFIG = _REPO_ROOT / ".pre-commit-config.yaml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestLintShWiring:
    """Worktree-scoped lint command contract."""

    def test_lint_sh_uses_session_scope_in_worktree(self) -> None:
        """make lint must consult session_scope.py for worktree-scoped runs."""
        content = _read(_LINT_SH)
        assert "session_scope.py" in content

    def test_lint_sh_scopes_all_tools_when_worktree(self) -> None:
        """When SCOPED_FILES is set, all lint tools receive the scoped file list."""
        content = _read(_LINT_SH)
        # Each tool must have a scoped branch — including guardrails
        assert '$RUN "${REPO_ROOT}/tools/lint/guardrails.py" $SCOPED_FILES' in content
        assert '$RUN "${REPO_ROOT}/tools/lint/ruff_safe.py" --fix $SCOPED_FILES' in content
        assert "$RUFF format $SCOPED_FILES" in content
        assert "$PYRIGHT $SCOPED_FILES" in content
        assert "$MYPY $SCOPED_FILES" in content
        assert "$PYLINT $SCOPED_FILES" in content

    def test_lint_sh_runs_repo_wide_outside_worktree(self) -> None:
        """When not in a worktree, lint tools run against repo-wide dirs."""
        content = _read(_LINT_SH)
        assert '$RUN "${REPO_ROOT}/tools/lint/ruff_safe.py" --fix $dirs' in content
        assert "$RUFF format $dirs" in content
        assert "$PYLINT teleclaude" in content

    def test_lint_sh_fails_on_scope_error_in_worktree(self) -> None:
        """Worktree scope resolution failure must exit 1, never fall back to repo-wide."""
        content = _read(_LINT_SH)
        assert "ERROR: worktree lint scope resolution failed" in content
        assert "exit 1" in content

    def test_lint_sh_dry_run_still_exits_cleanly(self) -> None:
        """The lint dry-run path should still succeed without executing the full suite."""
        result = subprocess.run(
            ["sh", str(_LINT_SH), "--dry-run"],
            check=False,
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        assert result.returncode == 0, result.stderr


class TestTestShWiring:
    """Worktree-scoped test command contract."""

    def test_test_sh_uses_session_scope_in_worktree(self) -> None:
        """make test must consult session_scope.py for worktree-scoped runs."""
        content = _read(_TEST_SH)
        assert "session_scope.py" in content

    def test_test_sh_scopes_pytest_when_worktree(self) -> None:
        """When SCOPED_TEST_FILES is set, pytest receives only the scoped test files."""
        content = _read(_TEST_SH)
        assert "pytest $SCOPED_TEST_FILES" in content

    def test_test_sh_runs_repo_wide_outside_worktree(self) -> None:
        """When not in a worktree, pytest runs the full repo test suite."""
        content = _read(_TEST_SH)
        assert 'timeout "${TEST_TIMEOUT}" pytest tests/unit tests/integration -m "not expensive" -q' in content

    def test_test_sh_fails_on_scope_error_in_worktree(self) -> None:
        """Worktree scope resolution failure must exit 1, never fall back to repo-wide."""
        content = _read(_TEST_SH)
        assert "ERROR: worktree test scope resolution failed" in content
        assert "exit 1" in content


class TestPrecommitHookWiring:
    """Staged-file pre-commit contract."""

    def test_precommit_does_not_call_session_scope(self) -> None:
        """Pre-commit hooks should not resolve session-scoped file sets."""
        content = _read(_PRECOMMIT_SH)
        assert "session_scope.py" not in content

    def test_precommit_config_passes_filenames_to_guardrails_and_typecheck(self) -> None:
        """Guardrails, docs validation, and typecheck hooks must receive staged filenames."""
        content = _read(_PRECOMMIT_CONFIG)
        guardrails_start = content.find("- id: guardrails")
        docs_validate_start = content.find("- id: teleclaude-docs-validate")
        typecheck_start = content.find("- id: typecheck")
        assert guardrails_start != -1
        assert docs_validate_start != -1
        assert typecheck_start != -1
        guardrails_end = content.find("\n  - id:", guardrails_start + 1)
        docs_validate_end = content.find("\n  - id:", docs_validate_start + 1)
        typecheck_end = content.find("\n  - id:", typecheck_start + 1)
        guardrails_block = (
            content[guardrails_start:] if guardrails_end == -1 else content[guardrails_start:guardrails_end]
        )
        docs_validate_block = (
            content[docs_validate_start:] if docs_validate_end == -1 else content[docs_validate_start:docs_validate_end]
        )
        typecheck_block = content[typecheck_start:] if typecheck_end == -1 else content[typecheck_start:typecheck_end]
        assert "pass_filenames: true" in guardrails_block
        assert "pass_filenames: true" in docs_validate_block
        assert "pass_filenames: true" in typecheck_block

    def test_parallel_typecheck_routes_passed_filenames_to_all_checkers(self) -> None:
        """The parallel typecheck hook must forward staged files to all Python checkers."""
        content = _read(_PRECOMMIT_SH)
        assert 'if $PYRIGHT "$@" > "$tmpdir/pyright.out" 2>&1; then' in content
        assert 'if $MYPY "$@" > "$tmpdir/mypy.out" 2>&1; then' in content
        # Pylint splits test vs src files for separate disable flags
        assert '$PYLINT $src_files >> "$tmpdir/pylint.out"' in content
        assert '$PYLINT --disable="$PYLINT_TEST_DISABLE" $test_files >> "$tmpdir/pylint.out"' in content
