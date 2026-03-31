# guard: no-companion
"""Contract tests for repo-wide shell commands and staged pre-commit hooks."""

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
    """Repo-wide lint command contract."""

    def test_lint_sh_no_longer_uses_session_scope(self) -> None:
        """make lint should no longer consult session-scoped helper scripts."""
        content = _read(_LINT_SH)
        assert "session_scope.py" not in content

    def test_lint_sh_runs_repo_wide_tools(self) -> None:
        """make lint should invoke repo-wide lint tools without scoped file lists."""
        content = _read(_LINT_SH)
        assert '$RUN "${REPO_ROOT}/tools/lint/ruff_safe.py" --fix $dirs' in content
        assert "$RUFF format $dirs" in content
        assert "$PYRIGHT" in content
        assert "$MYPY" in content
        assert "$PYLINT teleclaude" in content

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
    """Repo-wide test command contract."""

    def test_test_sh_no_longer_uses_session_scope(self) -> None:
        """make test should no longer consult session-scoped helper scripts."""
        content = _read(_TEST_SH)
        assert "session_scope.py" not in content

    def test_test_sh_runs_repo_wide_pytest_commands(self) -> None:
        """make test should run the full repo test suite in both normal and coverage modes."""
        content = _read(_TEST_SH)
        assert 'timeout "${TEST_TIMEOUT}" pytest tests/unit tests/integration -m "not expensive" -q' in content
        assert (
            'timeout "${TEST_TIMEOUT}" pytest tests/unit tests/integration -m "not expensive" --cov=teleclaude '
            "--cov-report=html --cov-report=term-missing"
        ) in content


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
        assert 'if $PYLINT "$@" > "$tmpdir/pylint.out" 2>&1; then' in content
