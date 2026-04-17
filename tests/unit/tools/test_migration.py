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
# R6.1 — Makefile delegates to telec code lint and telec code test
# ---------------------------------------------------------------------------


class TestMakefileTargetMigration:
    """Makefile lint/test targets invoke telec code lint/test."""

    def test_makefile_lint_target_delegates_to_telec_code_lint(self) -> None:
        content = _read(_MAKEFILE)
        lint_target_start = content.find("\nlint:")
        assert lint_target_start != -1, "Makefile has no 'lint:' target"
        lint_target_end = content.find("\n\n", lint_target_start + 1)
        lint_body = content[lint_target_start : lint_target_end if lint_target_end != -1 else None]
        assert "telec code lint" in lint_body, (
            f"Makefile lint target does not delegate to 'telec code lint':\n{lint_body}"
        )

    def test_makefile_test_target_delegates_to_telec_code_test(self) -> None:
        content = _read(_MAKEFILE)
        test_target_start = content.find("\ntest:")
        assert test_target_start != -1, "Makefile has no 'test:' target"
        test_target_end = content.find("\n\n", test_target_start + 1)
        test_body = content[test_target_start : test_target_end if test_target_end != -1 else None]
        assert "telec code test" in test_body, (
            f"Makefile test target does not delegate to 'telec code test':\n{test_body}"
        )


# ---------------------------------------------------------------------------
# R6.2 — Pre-commit hooks invoke telec code lint
# ---------------------------------------------------------------------------


class TestPrecommitHookMigration:
    """Pre-commit hooks route through 'telec code lint --step'."""

    def test_precommit_format_hook_routes_through_telec_code_lint(self) -> None:
        content = _read(_PRECOMMIT_CONFIG)
        block = _hook_block(content, "format")
        assert "telec code lint --step ruff_format" in block, (
            "format hook does not route through telec code lint:\n" + block
        )

    def test_precommit_guardrails_hook_routes_through_telec_code_lint(self) -> None:
        content = _read(_PRECOMMIT_CONFIG)
        block = _hook_block(content, "guardrails")
        assert "telec code lint --step guardrails" in block, (
            "guardrails hook does not route through telec code lint:\n" + block
        )

    def test_precommit_ruff_check_hook_routes_through_telec_code_lint(self) -> None:
        content = _read(_PRECOMMIT_CONFIG)
        block = _hook_block(content, "ruff-check")
        assert "telec code lint --step ruff_check" in block, (
            "ruff-check hook does not route through telec code lint:\n" + block
        )

    def test_precommit_typecheck_hook_routes_through_telec_code_lint(self) -> None:
        content = _read(_PRECOMMIT_CONFIG)
        block = _hook_block(content, "typecheck")
        assert "telec code lint --step pyright" in block, (
            "typecheck hook does not route through telec code lint:\n" + block
        )

    def test_precommit_markdown_validate_hook_routes_through_telec_code_lint(self) -> None:
        content = _read(_PRECOMMIT_CONFIG)
        block = _hook_block(content, "markdown-validate")
        assert "telec code lint --step markdown" in block, (
            "markdown-validate hook does not route through telec code lint:\n" + block
        )

    def test_lint_sh_delegates_to_telec_code_lint(self) -> None:
        content = _read(_LINT_SH)
        assert "telec code lint" in content, "tools/lint.sh does not delegate to 'telec code lint'"

    def test_test_sh_delegates_to_telec_code_test(self) -> None:
        content = _read(_TEST_SH)
        assert "telec code test" in content, "tools/test.sh does not delegate to 'telec code test'"


def _hook_block(config: str, hook_id: str) -> str:
    start = config.find(f"- id: {hook_id}")
    if start == -1:
        return ""
    end = config.find("\n  - id:", start + 1)
    return config[start:] if end == -1 else config[start:end]
