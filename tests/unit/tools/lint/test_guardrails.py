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
_check_import_outside_toplevel_policy = _mod._check_import_outside_toplevel_policy
_check_test_companions = _mod._check_test_companions
_check_no_companion_markers = _mod._check_no_companion_markers
_warn_for_loose_dicts = _mod._warn_for_loose_dicts

# Build test fixture strings via concatenation so the guardrails scanner
# does not match them in THIS file (tests/ is in the scan scope).
_NOQA_RAW_SQL = "# noqa" + ": raw-sql"
_NOQA_LOOSE_DICT = "# noqa" + ": loose-dict"
_NOQA_CUSTOM = "# noqa" + ": custom-rule"
_LOOSE_DICT_ANNOTATION = "dict[str, " + "object]"
_NO_COMPANION_MARKER = "# guard: " + "no-companion"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_file(base: Path, rel_path: str, content: str) -> None:
    """Write a file at base/rel_path, creating directories as needed."""
    full = base / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")


def _run_scanner(
    tmp_path: Path,
    rules: list[Any] | None = None,
    *,
    selected_paths: set[str] | None = None,
) -> str | None:
    """Run _check_source_patterns and return the error message, or None if clean."""
    _ = rules  # reserved for future per-rule testing

    try:
        _check_source_patterns(tmp_path, selected_paths)
        return None
    except SystemExit as e:
        return str(e)


def _run_loose_dict_check(tmp_path: Path, *, selected_paths: set[str] | None = None) -> str | None:
    """Run _warn_for_loose_dicts and return the error message, or None if clean."""
    try:
        _warn_for_loose_dicts(tmp_path, selected_paths)
        return None
    except SystemExit as e:
        return str(e)


def _run_import_outside_toplevel_policy_check(tmp_path: Path, *, selected_paths: set[str] | None = None) -> str | None:
    """Run import-outside-toplevel policy guardrail and return failure text if any."""
    try:
        _check_import_outside_toplevel_policy(tmp_path, selected_paths)
        return None
    except SystemExit as e:
        return str(e)


def _run_test_companion_check(tmp_path: Path, *, selected_paths: set[str] | None = None) -> str | None:
    """Run test companion guardrail and return failure text if any."""
    try:
        _check_test_companions(tmp_path, selected_paths)
        return None
    except SystemExit as e:
        return str(e)


# ---------------------------------------------------------------------------
# test companion guardrail tests
# ---------------------------------------------------------------------------


class TestCompanionGuardrail:
    """Tests for retired local marker enforcement and central orphan ratcheting."""

    @pytest.mark.unit
    def test_local_no_companion_marker_is_rejected(self, tmp_path: Path) -> None:
        """A real local marker is rejected instead of bypassing companion enforcement."""
        _write_file(tmp_path, "pyproject.toml", "[tool.test-mapping]\norphan-exclude = []\n")
        _write_file(tmp_path, "teleclaude/__init__.py", "")
        _write_file(
            tmp_path, "tests/unit/test_legacy.py", "# guard: no-companion\n\nfrom __future__ import annotations\n"
        )

        result = _run_test_companion_check(tmp_path)

        assert result is not None
        assert "no-companion" in result
        assert "tests/unit/test_legacy.py" in result

    @pytest.mark.unit
    def test_orphan_exclude_cannot_exceed_cap(self, tmp_path: Path) -> None:
        """Central orphan exclusions are capped so future changes can only ratchet down."""
        entries = ",\n".join(f'    "tests/unit/test_legacy_{index}.py"' for index in range(65))
        _write_file(tmp_path, "pyproject.toml", f"[tool.test-mapping]\norphan-exclude = [\n{entries},\n]\n")
        _write_file(tmp_path, "teleclaude/__init__.py", "")
        _write_file(tmp_path, "tests/unit/test_present.py", "from __future__ import annotations\n")

        result = _run_test_companion_check(tmp_path)

        assert result is not None
        assert "orphan-exclude" in result
        assert "65" in result


def _run_no_companion_marker_check(tmp_path: Path, *, selected_paths: set[str] | None = None) -> str | None:
    """Run test-file no-companion marker guardrail and return failure text if any."""
    try:
        _check_no_companion_markers(tmp_path, selected_paths)
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

    @pytest.mark.unit
    def test_scoped_run_ignores_unselected_match(self, tmp_path: Path) -> None:
        """Scoped scans must not fail on files outside the passed selection."""
        _write_file(tmp_path, "teleclaude/selected.py", "x = 1\n")
        _write_file(tmp_path, "teleclaude/unselected.py", f"x = 1  {_NOQA_RAW_SQL}\n")
        result = _run_scanner(tmp_path, selected_paths={"teleclaude/selected.py"})
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
        """Each rule must declare at least one scan directory."""
        for rule in _SOURCE_PATTERN_RULES:
            assert len(rule.scan_dirs) > 0, f"Rule {rule.name} has empty scan_dirs"

    @pytest.mark.unit
    def test_all_rules_have_non_empty_glob(self) -> None:
        """Each rule must declare a non-empty glob filter."""
        for rule in _SOURCE_PATTERN_RULES:
            assert rule.glob, f"Rule {rule.name} has empty glob"

    @pytest.mark.unit
    def test_all_patterns_compile(self) -> None:
        """Rule patterns should be compiled regular expressions."""
        for rule in _SOURCE_PATTERN_RULES:
            assert isinstance(rule.pattern, re.Pattern), f"Rule {rule.name} pattern is not compiled"

    @pytest.mark.unit
    def test_nonexistent_scan_dir_skipped_gracefully(self, tmp_path: Path) -> None:
        """A rule with a nonexistent scan dir does not crash."""
        result = _run_scanner(tmp_path)
        assert result is None


class TestImportOutsideTopLevelPolicy:
    """Tests for startup-boundary import-outside-toplevel enforcement."""

    @pytest.mark.unit
    def test_allowlisted_file_with_suppression_passes(self, tmp_path: Path) -> None:
        """Approved startup-boundary file may use PLC0415 when the reason is explicit."""
        _write_file(
            tmp_path,
            "teleclaude/daemon.py",
            "def f():\n    from pkg import thing  # noqa: PLC0415  # startup boundary\n",
        )
        result = _run_import_outside_toplevel_policy_check(tmp_path)
        assert result is None

    @pytest.mark.unit
    def test_allowlisted_file_with_reason_without_suppression_passes(self, tmp_path: Path) -> None:
        """Approved startup-boundary file without PLC0415 suppression is clean when reasoned."""
        _write_file(
            tmp_path,
            "teleclaude/daemon_event_platform.py",
            "def f():\n    from pkg import thing  # startup boundary\n",
        )
        result = _run_import_outside_toplevel_policy_check(tmp_path)
        assert result is None

    @pytest.mark.unit
    def test_allowlisted_file_missing_startup_reason_fails(self, tmp_path: Path) -> None:
        """Approved lazy imports must still carry the startup-boundary reason."""
        _write_file(
            tmp_path,
            "teleclaude/daemon.py",
            "def f():\n    from pkg import thing\n",
        )
        result = _run_import_outside_toplevel_policy_check(tmp_path)
        assert result is not None
        assert "startup-boundary" in result

    @pytest.mark.unit
    def test_startup_reason_outside_allowlist_fails(self, tmp_path: Path) -> None:
        """The startup-boundary reason is reserved for the approved files."""
        _write_file(
            tmp_path,
            "teleclaude/other.py",
            "def f():\n    from pkg import thing  # startup boundary\n",
        )
        result = _run_import_outside_toplevel_policy_check(tmp_path)
        assert result is not None
        assert "approved files" in result

    @pytest.mark.unit
    def test_plc0415_suppression_outside_allowlist_fails(self, tmp_path: Path) -> None:
        """PLC0415 suppression is rejected outside the approved files."""
        _write_file(
            tmp_path,
            "teleclaude/other.py",
            "def f():\n    from pkg import thing  # noqa: PLC0415\n",
        )
        result = _run_import_outside_toplevel_policy_check(tmp_path)
        assert result is not None
        assert "only allowed" in result


class TestNoCompanionMarkerPolicy:
    """Tests may not self-exempt from companion mapping with inline markers."""

    @pytest.mark.unit
    def test_rejects_no_companion_marker_inside_test_file(self, tmp_path: Path) -> None:
        """The no-companion marker is not valid in test files."""
        _write_file(tmp_path, "tests/unit/foo/test_bar.py", f"{_NO_COMPANION_MARKER}\n")

        result = _run_no_companion_marker_check(tmp_path)

        assert result is not None
        assert "test files may not use" in result
        assert "tests/unit/foo/test_bar.py" in result

    @pytest.mark.unit
    def test_scoped_run_reports_selected_test_marker(self, tmp_path: Path) -> None:
        """Scoped guardrail runs still reject selected test files carrying the marker."""
        _write_file(tmp_path, "tests/unit/foo/test_bar.py", f"{_NO_COMPANION_MARKER}\n")
        _write_file(tmp_path, "tests/unit/foo/test_baz.py", "def test_ok():\n    assert True\n")

        result = _run_no_companion_marker_check(tmp_path, selected_paths={"tests/unit/foo/test_bar.py"})

        assert result is not None
        assert "tests/unit/foo/test_bar.py" in result
        assert "tests/unit/foo/test_baz.py" not in result

    @pytest.mark.unit
    def test_marker_outside_tests_is_not_owned_by_test_marker_guard(self, tmp_path: Path) -> None:
        """This guardrail only rejects test-file markers."""
        _write_file(tmp_path, "teleclaude/foo.py", f"{_NO_COMPANION_MARKER}\n")

        result = _run_no_companion_marker_check(tmp_path)

        assert result is None


class TestLooseDictScoping:
    """Scoped-file behavior for loose-dict guardrails."""

    @pytest.mark.unit
    def test_scoped_run_ignores_unselected_loose_dict_match(self, tmp_path: Path) -> None:
        """Scoped loose-dict runs should ignore matches outside the selection."""
        _write_file(tmp_path, "teleclaude/selected.py", "value = 1\n")
        _write_file(tmp_path, "teleclaude/unselected.py", f"data: {_LOOSE_DICT_ANNOTATION} = {{}}\n")
        result = _run_loose_dict_check(tmp_path, selected_paths={"teleclaude/selected.py"})
        assert result is None

    @pytest.mark.unit
    def test_scoped_run_reports_selected_loose_dict_match(self, tmp_path: Path) -> None:
        """Scoped loose-dict runs should still report matches in selected files."""
        _write_file(tmp_path, "teleclaude/selected.py", f"data: {_LOOSE_DICT_ANNOTATION} = {{}}\n")
        result = _run_loose_dict_check(tmp_path, selected_paths={"teleclaude/selected.py"})
        assert result is not None
        assert "loose dict typings detected" in result
