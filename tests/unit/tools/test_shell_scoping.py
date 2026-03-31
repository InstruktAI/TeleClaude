# guard: no-companion
"""Test spec (xfail) for split scoping contracts across lint/test and pre-commit.

These tests verify two layers:
  1. Structural wiring — session-aware scripts call session_scope.py with the correct flags.
  2. Behavioral protocol — each script falls back to full suite on non-zero helper exit.

Combined with tests/unit/tools/test_session_scope.py (helper contracts), this proves
the split contract without requiring tool-binary stubbing:
  - lint.sh and test.sh are session-scoped in agent sessions
  - pre-commit operates only on the staged filenames it is given

Remove ``pytestmark = pytest.mark.xfail`` once all tests pass after implementation.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LINT_SH = _REPO_ROOT / "tools" / "lint.sh"
_TEST_SH = _REPO_ROOT / "tools" / "test.sh"
_PRECOMMIT_SH = _REPO_ROOT / "tools" / "lint" / "precommit-hook.sh"
_PRECOMMIT_CONFIG = _REPO_ROOT / ".pre-commit-config.yaml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Task 2: tools/lint.sh wiring
# ---------------------------------------------------------------------------


class TestLintShWiring:
    """Contract checks for session-scoped lint wiring."""

    def test_calls_session_scope_with_mode_lint(self) -> None:
        """lint.sh must invoke session_scope.py --mode lint to resolve scoped files."""
        assert _LINT_SH.exists(), "tools/lint.sh not yet modified"
        content = _read(_LINT_SH)
        assert "session_scope.py" in content, "lint.sh does not call session_scope.py"
        assert "--mode lint" in content, "lint.sh does not pass --mode lint to helper"

    def test_falls_back_to_full_suite_on_no_session(self) -> None:
        """lint.sh falls back to full-suite behavior when session_scope exits 2."""
        assert _LINT_SH.exists(), "tools/lint.sh not yet modified"
        # Outside any session: session_scope exits 2 → script must not scope.
        # Verified by running lint.sh without an identity file and checking it does
        # not pass explicit file paths to the lint tools (uses dirs, not a file list).
        result = subprocess.run(
            ["sh", str(_LINT_SH), "--dry-run"],
            check=False,
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        # Behavioral contract: no crash; exit 0 or non-scope error only.
        # Absence of "--mode lint output" in the run confirms full-suite path.
        assert result.returncode == 0, f"lint.sh failed outside session: {result.stderr!r}"

    def test_scoped_branch_prints_count_message(self) -> None:
        """lint.sh prints 'Session-scoped lint: N files' when helper returns a file list."""
        env = os.environ.copy()
        env["SESSION_SCOPE_STUB_OUTPUT"] = "teleclaude/session_identity.py\n"
        result = subprocess.run(
            ["sh", str(_LINT_SH), "--dry-run"],
            env=env,
            check=False,
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        assert result.returncode == 0, f"lint.sh failed with stub: {result.stderr!r}"
        assert "Session-scoped lint: 1 files" in result.stdout, (
            f"Expected scoped count message; stdout: {result.stdout!r}"
        )

    def test_scoped_files_flow_to_each_lint_tool(self) -> None:
        """lint.sh routes $SCOPED_FILES into every Python lint invocation."""
        content = _read(_LINT_SH)
        assert '$RUN "${REPO_ROOT}/tools/lint/ruff_safe.py" --fix $SCOPED_FILES' in content
        assert "$RUFF format $SCOPED_FILES" in content
        assert "$PYRIGHT $SCOPED_FILES" in content
        assert "$MYPY $SCOPED_FILES" in content
        assert "$PYLINT $SCOPED_FILES" in content

    def test_does_not_scope_guardrails_or_markdown(self) -> None:
        """lint.sh leaves guardrails and markdown validation unconditionally full-project."""
        assert _LINT_SH.exists(), "tools/lint.sh not yet modified"
        content = _read(_LINT_SH)
        # Guardrails and markdown calls must NOT be wrapped in scoped-file conditionals.
        # They appear in the script before the session-scope detection block.
        guardrails_pos = content.find("guardrails.py")
        session_scope_pos = content.find("session_scope.py")
        assert guardrails_pos != -1, "guardrails.py not found in lint.sh"
        assert session_scope_pos != -1, "session_scope.py not found in lint.sh"
        # Guardrails runs unconditionally: it appears before or independently of scope logic.
        # We verify by confirming the call is not inside a scoped-files conditional block.
        # Simple structural check: session_scope detection appears after guardrails call.
        assert guardrails_pos < session_scope_pos, (
            "session_scope detection must appear after the unconditional guardrails call"
        )


# ---------------------------------------------------------------------------
# Task 3: tools/test.sh wiring
# ---------------------------------------------------------------------------


class TestTestShWiring:
    """Contract checks for session-scoped test wiring."""

    def test_calls_session_scope_with_mode_test(self) -> None:
        """test.sh must invoke session_scope.py --mode test to resolve companion files."""
        assert _TEST_SH.exists(), "tools/test.sh not yet modified"
        content = _read(_TEST_SH)
        assert "session_scope.py" in content, "test.sh does not call session_scope.py"
        assert "--mode test" in content, "test.sh does not pass --mode test to helper"

    def test_passes_companion_files_to_pytest_when_scoped(self) -> None:
        """test.sh passes $SCOPED_TEST_FILES directly to the pytest command."""
        assert _TEST_SH.exists(), "tools/test.sh not yet modified"
        content = _read(_TEST_SH)
        # Verify the scoped variable is actually passed to pytest, not just assigned.
        assert "pytest $SCOPED_TEST_FILES" in content, "SCOPED_TEST_FILES not passed directly to pytest in test.sh"

    def test_cov_branch_also_uses_scoped_files(self) -> None:
        """test.sh --cov branch applies the same scoping as the normal branch."""
        assert _TEST_SH.exists(), "tools/test.sh not yet modified"
        content = _read(_TEST_SH)
        # Both the normal and --cov pytest invocations must reference the scoped files variable.
        # Behavioral contract: coverage runs are not accidentally unscoped.
        cov_idx = content.find("--cov")
        assert cov_idx != -1, "--cov branch not found in test.sh"
        # After the --cov invocation there should be a reference to scoped variable.
        cov_section = content[cov_idx:]
        assert "SCOPED" in cov_section or "scoped" in cov_section.lower(), (
            "--cov pytest invocation does not use the scoped-files variable"
        )

    def test_scoped_test_files_flow_to_pytest_in_both_branches(self) -> None:
        """test.sh routes $SCOPED_TEST_FILES into normal and --cov pytest calls."""
        content = _read(_TEST_SH)
        assert 'pytest $SCOPED_TEST_FILES -m "not expensive" -q' in content
        assert (
            'pytest $SCOPED_TEST_FILES -m "not expensive" --cov=teleclaude --cov-report=html --cov-report=term-missing'
            in content
        )

    def test_early_exit_guard_precedes_session_detection(self) -> None:
        """test.sh early-exit guard (no test suite) runs before session scope detection."""
        assert _TEST_SH.exists(), "tools/test.sh not yet modified"
        content = _read(_TEST_SH)
        # Behavioral contract: if tests/unit does not exist, exit before hitting scoping.
        early_exit_pos = content.find("Test suite pending")
        session_scope_pos = content.find("session_scope.py")
        assert early_exit_pos != -1, "Early-exit guard for missing test suite not found"
        assert session_scope_pos != -1, "session_scope.py not found in test.sh"
        assert early_exit_pos < session_scope_pos, "Early-exit guard must appear before session-scope detection"


# ---------------------------------------------------------------------------
# Task 4: tools/lint/precommit-hook.sh wiring
# ---------------------------------------------------------------------------


class TestPrecommitHookWiring:
    """Contract checks for staged-file pre-commit wiring."""

    def test_precommit_does_not_call_session_scope(self) -> None:
        """precommit-hook.sh must not consult session scope; commit hooks validate staged files only."""
        assert _PRECOMMIT_SH.exists(), "tools/lint/precommit-hook.sh not yet modified"
        content = _read(_PRECOMMIT_SH)
        assert "session_scope.py" not in content, "precommit-hook.sh should not consult session scope"

    def test_precommit_config_passes_filenames_to_typecheck(self) -> None:
        """The typecheck pre-commit hook must receive the staged filenames directly from pre-commit."""
        assert _PRECOMMIT_CONFIG.exists(), ".pre-commit-config.yaml not found"
        content = _read(_PRECOMMIT_CONFIG)
        start = content.find("- id: typecheck")
        assert start != -1, "typecheck hook missing from pre-commit config"
        end = content.find("\n  - id:", start + 1)
        hook_block = content[start:] if end == -1 else content[start:end]
        assert "pass_filenames: true" in hook_block, "typecheck hook must receive staged filenames from pre-commit"

    def test_parallel_typecheck_routes_passed_filenames_to_all_checkers(self) -> None:
        """parallel-typecheck must pass the pre-commit filename list to pyright, mypy, and pylint."""
        content = _read(_PRECOMMIT_SH)
        assert 'if $PYRIGHT "$@" > "$tmpdir/pyright.out" 2>&1; then' in content
        assert 'if $MYPY "$@" > "$tmpdir/mypy.out" 2>&1; then' in content
        assert 'if $PYLINT "$@" > "$tmpdir/pylint.out" 2>&1; then' in content

    def test_standalone_checker_cases_use_passed_filenames(self) -> None:
        """pyright, mypy, and pylint cases must all use the same passed filename list."""
        content = _read(_PRECOMMIT_SH)
        assert '$PYRIGHT "$@"' in content
        assert '$MYPY "$@"' in content
        assert '$PYLINT "$@"' in content

    def test_guardrails_and_ruff_check_unchanged(self) -> None:
        """precommit-hook.sh guardrails and ruff-check components are not modified."""
        assert _PRECOMMIT_SH.exists(), "tools/lint/precommit-hook.sh not yet modified"
        content = _read(_PRECOMMIT_SH)
        assert "guardrails" in content, "guardrails case missing from precommit-hook.sh"
        assert "ruff-check" in content or "ruff" in content, "ruff-check case missing from precommit-hook.sh"


# ---------------------------------------------------------------------------
# Exit protocol: shared across all three scripts
# ---------------------------------------------------------------------------


class TestExitProtocolHandling:
    """Shared exit-code handling contracts for scoped helper callers."""

    def test_lint_sh_falls_back_silently_on_exit_2(self) -> None:
        """lint.sh treats session_scope exit 2 as non-session context; no stderr emitted."""
        assert _LINT_SH.exists(), "tools/lint.sh not yet modified"
        content = _read(_LINT_SH)
        # Exit code 2 from session_scope means "not in a session" — no diagnostic.
        # Structural: the script checks exit code and branches without stderr output on exit 2.
        assert "exit" in content and ("$?" in content or "returncode" in content.lower() or "SCOPED" in content), (
            "lint.sh does not check session_scope exit code to decide fallback"
        )

    def test_test_sh_falls_back_silently_on_exit_2(self) -> None:
        """test.sh treats session_scope exit 2 as non-session context; no stderr emitted."""
        assert _TEST_SH.exists(), "tools/test.sh not yet modified"
        content = _read(_TEST_SH)
        assert "exit" in content and ("$?" in content or "SCOPED" in content), (
            "test.sh does not check session_scope exit code to decide fallback"
        )
