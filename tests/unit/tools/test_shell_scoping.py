# guard: no-companion
"""Behavioral contract tests for worktree-scoped shell commands and staged pre-commit hooks.

Tests verify syntax validity, component routing, and config structure — never exact shell syntax.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from unittest.mock import patch

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LINT_SH = _REPO_ROOT / "tools" / "lint.sh"
_TEST_SH = _REPO_ROOT / "tools" / "test.sh"
_PRECOMMIT_SH = _REPO_ROOT / "tools" / "lint" / "precommit-hook.sh"
_PRECOMMIT_CONFIG = _REPO_ROOT / ".pre-commit-config.yaml"

_EXPECTED_COMPONENTS = frozenset({
    "guardrails", "ruff-check", "pyright", "mypy", "pylint",
    "parallel-typecheck", "markdown", "docs-validate",
})


def _syntax_check(script: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["sh", "-n", str(script)], check=False, capture_output=True, text=True)


class TestLintShWiring:
    """Worktree-scoped lint command contract."""

    def test_lint_sh_is_valid_shell(self) -> None:
        result = _syntax_check(_LINT_SH)
        assert result.returncode == 0, f"lint.sh has syntax errors: {result.stderr}"

    def test_lint_sh_dry_run_exits_cleanly(self) -> None:
        result = subprocess.run(
            ["sh", str(_LINT_SH), "--dry-run"],
            check=False, capture_output=True, text=True,
            cwd=str(_REPO_ROOT),
        )
        assert result.returncode == 0, result.stderr


class TestTestShWiring:
    """Worktree-scoped test command contract."""

    def test_test_sh_is_valid_shell(self) -> None:
        result = _syntax_check(_TEST_SH)
        assert result.returncode == 0, f"test.sh has syntax errors: {result.stderr}"


class TestPrecommitHookWiring:
    """Staged-file pre-commit contract."""

    def test_precommit_hook_is_valid_shell(self) -> None:
        result = _syntax_check(_PRECOMMIT_SH)
        assert result.returncode == 0, f"precommit-hook.sh has syntax errors: {result.stderr}"

    def test_precommit_rejects_unknown_component(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="Unknown lint component: bogus\n",
            )
            result = subprocess.run(
                ["sh", str(_PRECOMMIT_SH), "bogus"],
                check=False, capture_output=True, text=True,
            )
        assert result.returncode != 0

    def test_precommit_case_statement_covers_all_expected_components(self) -> None:
        """The case statement must route all expected components."""
        content = _PRECOMMIT_SH.read_text(encoding="utf-8")
        found = {m.group(1) for m in re.finditer(r"^\s+([\w-]+)\)\s*$", content, re.MULTILINE)} - {"*"}
        missing = _EXPECTED_COMPONENTS - found
        assert not missing, f"Components missing from precommit-hook.sh: {missing}"

    def test_precommit_config_passes_filenames_to_key_hooks(self) -> None:
        """Guardrails, docs validation, and typecheck hooks must have pass_filenames: true."""
        config = yaml.safe_load(_PRECOMMIT_CONFIG.read_text(encoding="utf-8"))
        hooks_by_id: dict[str, dict[str, object]] = {}
        for repo in config.get("repos", []):
            for hook in repo.get("hooks", []):
                hooks_by_id[hook["id"]] = hook

        for hook_id in ("guardrails", "teleclaude-docs-validate", "typecheck"):
            assert hook_id in hooks_by_id, f"Hook {hook_id!r} missing from .pre-commit-config.yaml"
            assert hooks_by_id[hook_id].get("pass_filenames") is True, (
                f"Hook {hook_id!r} must have pass_filenames: true"
            )
