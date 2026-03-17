"""Tests for the table-driven pattern scanner in tools/lint/guardrails.py.

Covers the _check_source_patterns function and SOURCE_PATTERN_RULES,
with focus on the invalid-noqa rule (net-new behavior).
"""

from __future__ import annotations

import importlib.util
import re
import types
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Import the scanner and rules from guardrails.py
# ---------------------------------------------------------------------------

# guardrails.py lives outside the teleclaude package, so we import via
# importlib to avoid sys.path manipulation.
_GUARDRAILS_PATH = Path(__file__).resolve().parents[4] / "tools" / "lint" / "guardrails.py"
_spec = importlib.util.spec_from_file_location("guardrails", _GUARDRAILS_PATH)
assert _spec is not None and _spec.loader is not None
_mod: types.ModuleType = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

_SOURCE_PATTERN_RULES: list[Any] = _mod.SOURCE_PATTERN_RULES
_check_source_patterns = _mod._check_source_patterns

# Build test fixture strings via concatenation so the guardrails scanner
# does not match them in THIS file (tests/ is in the scan scope).
_NOQA_RAW_SQL = "# noqa" + ": raw-sql"
_NOQA_LOOSE_DICT = "# noqa" + ": loose-dict"
_NOQA_CUSTOM = "# noqa" + ": custom-rule"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_file(base: Path, rel_path: str, content: str) -> None:
    """Write a file at base/rel_path, creating directories as needed."""
    full = base / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")


def _run_scanner(tmp_path: Path, rules: list[Any] | None = None) -> str | None:
    """Run _check_source_patterns and return the error message, or None if clean."""
    _ = rules  # reserved for future per-rule testing

    try:
        _check_source_patterns(tmp_path)
        return None
    except SystemExit as e:
        return str(e)


# ---------------------------------------------------------------------------
# invalid-noqa rule tests
# ---------------------------------------------------------------------------


class TestInvalidNoqaRule:
    """Tests for the invalid-noqa pattern rule."""

    @pytest.mark.unit
    def test_catches_lowercase_noqa_directive(self, tmp_path: Path) -> None:
        """Lowercase noqa code is flagged."""
        _write_file(tmp_path, "teleclaude/example.py", f"x = 1  {_NOQA_RAW_SQL}\n")
        result = _run_scanner(tmp_path)
        assert result is not None
        assert "invalid-noqa" in result

    @pytest.mark.unit
    def test_ignores_uppercase_ruff_code(self, tmp_path: Path) -> None:
        """Valid uppercase ruff code is NOT flagged."""
        _write_file(tmp_path, "teleclaude/example.py", "x = 1  # noqa: E501\n")
        result = _run_scanner(tmp_path)
        assert result is None

    @pytest.mark.unit
    def test_ignores_uppercase_multi_code(self, tmp_path: Path) -> None:
        """Multiple valid uppercase ruff codes are NOT flagged."""
        _write_file(tmp_path, "teleclaude/example.py", "import os  # noqa: F401, E501\n")
        result = _run_scanner(tmp_path)
        assert result is None

    @pytest.mark.unit
    def test_excludes_tools_lint_directory(self, tmp_path: Path) -> None:
        """Files under tools/lint/ are excluded from the invalid-noqa rule."""
        _write_file(tmp_path, "tools/lint/guardrails.py", f'marker = "{_NOQA_LOOSE_DICT}"\n')
        result = _run_scanner(tmp_path)
        assert result is None

    @pytest.mark.unit
    def test_scans_tests_directory(self, tmp_path: Path) -> None:
        """The invalid-noqa rule scans the tests/ directory."""
        _write_file(tmp_path, "tests/test_foo.py", f"x = 1  {_NOQA_CUSTOM}\n")
        result = _run_scanner(tmp_path)
        assert result is not None
        assert "invalid-noqa" in result

    @pytest.mark.unit
    def test_clean_file_passes(self, tmp_path: Path) -> None:
        """A file with no noqa directives passes cleanly."""
        _write_file(tmp_path, "teleclaude/clean.py", "x = 1\ny = 2\n")
        result = _run_scanner(tmp_path)
        assert result is None

    @pytest.mark.unit
    def test_guard_marker_not_flagged(self, tmp_path: Path) -> None:
        """A guard: raw-sql marker is NOT flagged by invalid-noqa."""
        _write_file(tmp_path, "teleclaude/db.py", 'await conn.execute("PRAGMA")  # guard: raw-sql\n')
        result = _run_scanner(tmp_path)
        assert result is None


# ---------------------------------------------------------------------------
# debug-probes rule tests
# ---------------------------------------------------------------------------


class TestDebugProbesRule:
    """Tests for the debug-probes pattern rule."""

    @pytest.mark.unit
    def test_catches_debug_print(self, tmp_path: Path) -> None:
        """A print with DEBUG: marker is flagged."""
        _write_file(tmp_path, "teleclaude/module.py", 'print("DEBUG: test value")\n')
        result = _run_scanner(tmp_path)
        assert result is not None
        assert "debug-probes" in result

    @pytest.mark.unit
    def test_clean_print_passes(self, tmp_path: Path) -> None:
        """A regular print() statement is NOT flagged."""
        _write_file(tmp_path, "teleclaude/module.py", 'print("Hello world")\n')
        result = _run_scanner(tmp_path)
        assert result is None

    @pytest.mark.unit
    def test_excludes_scripts_fixtures(self, tmp_path: Path) -> None:
        """Files under scripts/fixtures/ are excluded."""
        _write_file(tmp_path, "scripts/fixtures/test_data.py", 'print("DEBUG: fixture")\n')
        result = _run_scanner(tmp_path)
        assert result is None


# ---------------------------------------------------------------------------
# stash-in-artifacts rule tests
# ---------------------------------------------------------------------------


class TestStashInArtifactsRule:
    """Tests for the stash-in-artifacts pattern rule."""

    @pytest.mark.unit
    def test_catches_git_stash_in_agent_md(self, tmp_path: Path) -> None:
        """A git stash command in agents/*.md is flagged."""
        _write_file(tmp_path, "agents/worker.md", "Run `git stash pop` to restore.\n")
        result = _run_scanner(tmp_path)
        assert result is not None
        assert "stash-in-artifacts" in result

    @pytest.mark.unit
    def test_exception_marker_same_line(self, tmp_path: Path) -> None:
        """guard: allow-git-stash on the same line suppresses the finding."""
        _write_file(
            tmp_path,
            "agents/worker.md",
            "Run `git stash pop` to restore.  <!-- guard: allow-git-stash -->\n",
        )
        result = _run_scanner(tmp_path)
        assert result is None

    @pytest.mark.unit
    def test_exception_marker_previous_line(self, tmp_path: Path) -> None:
        """guard: allow-git-stash on the previous line suppresses the finding."""
        _write_file(
            tmp_path,
            "agents/worker.md",
            "<!-- guard: allow-git-stash -->\nRun `git stash pop` to restore.\n",
        )
        result = _run_scanner(tmp_path)
        assert result is None

    @pytest.mark.unit
    def test_exception_marker_two_lines_above_does_not_suppress(self, tmp_path: Path) -> None:
        """guard: allow-git-stash two lines above does NOT suppress."""
        _write_file(
            tmp_path,
            "agents/worker.md",
            "<!-- guard: allow-git-stash -->\n\nRun `git stash pop` to restore.\n",
        )
        result = _run_scanner(tmp_path)
        assert result is not None
        assert "stash-in-artifacts" in result


# ---------------------------------------------------------------------------
# Structural tests for SOURCE_PATTERN_RULES
# ---------------------------------------------------------------------------


class TestPatternRuleIntegrity:
    """Structural validation of the rules table."""

    @pytest.mark.unit
    def test_all_rules_have_non_empty_scan_dirs(self) -> None:
        for rule in _SOURCE_PATTERN_RULES:
            assert len(rule.scan_dirs) > 0, f"Rule {rule.name} has empty scan_dirs"

    @pytest.mark.unit
    def test_all_rules_have_non_empty_glob(self) -> None:
        for rule in _SOURCE_PATTERN_RULES:
            assert rule.glob, f"Rule {rule.name} has empty glob"

    @pytest.mark.unit
    def test_all_patterns_compile(self) -> None:
        for rule in _SOURCE_PATTERN_RULES:
            assert isinstance(rule.pattern, re.Pattern), f"Rule {rule.name} pattern is not compiled"

    @pytest.mark.unit
    def test_nonexistent_scan_dir_skipped_gracefully(self, tmp_path: Path) -> None:
        """A rule with a nonexistent scan dir does not crash."""
        result = _run_scanner(tmp_path)
        assert result is None
