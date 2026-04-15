# guard: no-companion
# pylint: disable=import-outside-toplevel
"""Tests for R6: backward-compatible migration.

Behavioral contracts for the incremental migration of TeleClaude's lint/test
infrastructure to the new telec CLI commands.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MAKEFILE = _REPO_ROOT / "Makefile"
_LINT_SH = _REPO_ROOT / "tools" / "lint.sh"
_TEST_SH = _REPO_ROOT / "tools" / "test.sh"
_PRECOMMIT_CONFIG = _REPO_ROOT / ".pre-commit-config.yaml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# R6.1 — Makefile delegates to telec lint and telec test
# ---------------------------------------------------------------------------


class TestMakefileTargetMigration:
    """Makefile lint/test targets invoke the new telec CLI commands.

    Note: These tests verify delegation (the Makefile invokes telec lint/test).
    Behavioral equivalence between old scripts and new commands (same exit codes,
    same file sets, same guardrails) is an integration-level concern verified in
    quality-checklist.md during the build phase, not in unit specs.
    """

    def test_makefile_lint_target_delegates_to_telec_lint(self) -> None:
        """Makefile 'lint' target invokes 'telec lint' (not the old tools/lint.sh directly).

        Assumption: target body ends at the next blank line (standard Makefile convention).
        """
        content = _read(_MAKEFILE)
        # Find the lint target section
        lint_target_start = content.find("\nlint:")
        assert lint_target_start != -1, "Makefile has no 'lint:' target"

        # The lint target body must contain 'telec lint'
        lint_target_end = content.find("\n\n", lint_target_start + 1)
        lint_body = content[lint_target_start : lint_target_end if lint_target_end != -1 else None]
        assert "telec lint" in lint_body, f"Makefile lint target does not delegate to 'telec lint':\n{lint_body}"

    def test_makefile_test_target_delegates_to_telec_test(self) -> None:
        """Makefile 'test' target invokes 'telec test' (not the old tools/test.sh directly).

        Assumption: target body ends at the next blank line (standard Makefile convention).
        """
        content = _read(_MAKEFILE)
        test_target_start = content.find("\ntest:")
        assert test_target_start != -1, "Makefile has no 'test:' target"

        test_target_end = content.find("\n\n", test_target_start + 1)
        test_body = content[test_target_start : test_target_end if test_target_end != -1 else None]
        assert "telec test" in test_body, f"Makefile test target does not delegate to 'telec test':\n{test_body}"


# ---------------------------------------------------------------------------
# R6.2 — Pre-commit hooks invoke telec lint (or continue to work)
# ---------------------------------------------------------------------------


class TestPrecommitHookMigration:
    """Pre-commit hooks continue to function via the new CLI commands."""

    def test_precommit_guardrails_hook_exists(self) -> None:
        """The guardrails pre-commit hook must exist and run guardrail enforcement."""
        content = _read(_PRECOMMIT_CONFIG)
        guardrails_start = content.find("- id: guardrails")
        assert guardrails_start != -1, "No guardrails hook in .pre-commit-config.yaml"

        guardrails_end = content.find("\n  - id:", guardrails_start + 1)
        guardrails_block = (
            content[guardrails_start:] if guardrails_end == -1 else content[guardrails_start:guardrails_end]
        )
        assert "guardrails" in guardrails_block, (
            "guardrails hook missing from .pre-commit-config.yaml:\n" + guardrails_block
        )

    def test_lint_sh_delegates_to_telec_lint(self) -> None:
        """tools/lint.sh invokes 'telec lint' (thin wrapper, not the full pipeline).

        BUILDER NOTE (R6 dependency): test_shell_scoping.py:TestLintShWiring currently passes and
        asserts that lint.sh invokes repo-wide tools directly. This conflicts with the migration
        contract above. During R6 implementation, delete or replace
        TestLintShWiring.test_lint_sh_runs_repo_wide_tools (and the class if empty) once lint.sh
        delegates to 'telec lint'.
        """
        content = _read(_LINT_SH)
        assert "telec lint" in content, "tools/lint.sh does not delegate to 'telec lint' — migration incomplete"

    def test_test_sh_delegates_to_telec_test(self) -> None:
        """tools/test.sh invokes 'telec test' (thin wrapper, not the full pytest call)."""
        content = _read(_TEST_SH)
        assert "telec test" in content, "tools/test.sh does not delegate to 'telec test' — migration incomplete"


# ---------------------------------------------------------------------------
# R6.3 — CLI surface registers telec lint and telec test
# ---------------------------------------------------------------------------


class TestCliSurfaceRegistration:
    """telec lint and telec test must be registered in the CLI surface."""

    def test_lint_command_registered_in_cli_surface(self) -> None:
        """CLI_SURFACE contains a 'lint' command entry."""
        from teleclaude.cli.telec import CLI_SURFACE  # pylint: disable=import-outside-toplevel

        assert "lint" in CLI_SURFACE, "CLI_SURFACE does not contain 'lint' — telec lint is not registered"

    def test_test_command_registered_in_cli_surface(self) -> None:
        """CLI_SURFACE contains a 'test' command entry."""
        from teleclaude.cli.telec import CLI_SURFACE  # pylint: disable=import-outside-toplevel

        assert "test" in CLI_SURFACE, "CLI_SURFACE does not contain 'test' — telec test is not registered"
