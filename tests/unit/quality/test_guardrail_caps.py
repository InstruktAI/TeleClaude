"""Tests for R5: configurable guardrail caps.

Behavioral contracts for per-project guardrail threshold configuration:
defaults match current TeleClaude baselines, custom caps override, graceful
fallback when configuration is missing.
"""

from __future__ import annotations

from pathlib import Path

from teleclaude.quality.guardrail_caps import load_guardrail_caps

# Current TeleClaude hardcoded baseline values — defaults must match these exactly.
_BASELINE_MAX_IGNORE_FILES = 8  # PYRIGHT_MAX_IGNORE_FILES
_BASELINE_MAX_GLOBAL_IGNORES = 8  # RUFF_MAX_GLOBAL_IGNORES
_BASELINE_MAX_PER_FILE_IGNORES = 50  # RUFF_MAX_PER_FILE_IGNORE_ENTRIES
_BASELINE_MAX_OVERRIDE_SECTIONS = 13  # MYPY_MAX_OVERRIDE_SECTIONS
_BASELINE_MAX_MODULE_LINES = 1000  # MODULE_MAX_LINES
_BASELINE_REQUIRED_RULE_GROUPS = frozenset({"E", "F", "I", "C90", "B", "UP", "RUF"})


# ---------------------------------------------------------------------------
# R5.1 — Default caps match current TeleClaude hardcoded values
# ---------------------------------------------------------------------------


class TestDefaultCaps:
    """Default guardrail caps match current TeleClaude baseline values."""

    def test_default_max_ignore_files(self, tmp_path: Path) -> None:
        """Default pyright ignore file limit matches TeleClaude baseline (8)."""
        caps = load_guardrail_caps(project_root=tmp_path)
        assert caps.max_ignore_files == _BASELINE_MAX_IGNORE_FILES, (
            f"Default max_ignore_files={caps.max_ignore_files}, expected {_BASELINE_MAX_IGNORE_FILES}"
        )

    def test_default_max_global_ignores(self, tmp_path: Path) -> None:
        """Default ruff global ignore limit matches TeleClaude baseline (8)."""
        caps = load_guardrail_caps(project_root=tmp_path)
        assert caps.max_global_ignores == _BASELINE_MAX_GLOBAL_IGNORES

    def test_default_max_per_file_ignores(self, tmp_path: Path) -> None:
        """Default ruff per-file ignore limit matches TeleClaude baseline (50)."""
        caps = load_guardrail_caps(project_root=tmp_path)
        assert caps.max_per_file_ignores == _BASELINE_MAX_PER_FILE_IGNORES

    def test_default_max_override_sections(self, tmp_path: Path) -> None:
        """Default mypy override section limit matches TeleClaude baseline (13)."""
        caps = load_guardrail_caps(project_root=tmp_path)
        assert caps.max_override_sections == _BASELINE_MAX_OVERRIDE_SECTIONS

    def test_default_max_module_lines(self, tmp_path: Path) -> None:
        """Default module size limit matches TeleClaude baseline (1000 lines)."""
        caps = load_guardrail_caps(project_root=tmp_path)
        assert caps.max_module_lines == _BASELINE_MAX_MODULE_LINES

    def test_default_required_rule_groups(self, tmp_path: Path) -> None:
        """Default required ruff rule groups match TeleClaude baseline."""
        caps = load_guardrail_caps(project_root=tmp_path)
        assert caps.required_rule_groups == _BASELINE_REQUIRED_RULE_GROUPS


# ---------------------------------------------------------------------------
# R5.2 — Custom caps override defaults
# ---------------------------------------------------------------------------


class TestCustomCapsOverride:
    """Per-project configuration in [tool.guardrails] overrides the defaults."""

    def test_custom_max_ignore_files_overrides_default(self, tmp_path: Path) -> None:
        """A custom max_ignore_files in pyproject.toml overrides the default."""
        (tmp_path / "pyproject.toml").write_text(
            "[tool.guardrails]\nmax_ignore_files = 3\n",
            encoding="utf-8",
        )

        caps = load_guardrail_caps(project_root=tmp_path)
        assert caps.max_ignore_files == 3, f"Custom max_ignore_files not applied: got {caps.max_ignore_files}"

    def test_custom_max_module_lines_overrides_default(self, tmp_path: Path) -> None:
        """A custom max_module_lines in pyproject.toml overrides the default."""
        (tmp_path / "pyproject.toml").write_text(
            "[tool.guardrails]\nmax_module_lines = 500\n",
            encoding="utf-8",
        )

        caps = load_guardrail_caps(project_root=tmp_path)
        assert caps.max_module_lines == 500

    def test_partial_config_falls_back_for_unspecified_caps(self, tmp_path: Path) -> None:
        """Specifying only some caps leaves unspecified caps at their defaults."""
        (tmp_path / "pyproject.toml").write_text(
            "[tool.guardrails]\nmax_ignore_files = 2\n",
            encoding="utf-8",
        )

        caps = load_guardrail_caps(project_root=tmp_path)
        assert caps.max_ignore_files == 2, "Custom value was not applied"
        assert caps.max_module_lines == _BASELINE_MAX_MODULE_LINES, "Unspecified cap should have defaulted to baseline"

    def test_tightened_cap_below_default_is_respected(self, tmp_path: Path) -> None:
        """A project can tighten caps below the default (stricter enforcement)."""
        (tmp_path / "pyproject.toml").write_text(
            "[tool.guardrails]\nmax_global_ignores = 2\n",
            encoding="utf-8",
        )

        caps = load_guardrail_caps(project_root=tmp_path)
        assert caps.max_global_ignores == 2, "Tightened cap (2) was not respected"

    def test_loosened_cap_above_default_is_respected(self, tmp_path: Path) -> None:
        """A project can loosen caps above the default (less strict enforcement)."""
        (tmp_path / "pyproject.toml").write_text(
            "[tool.guardrails]\nmax_module_lines = 2000\n",
            encoding="utf-8",
        )

        caps = load_guardrail_caps(project_root=tmp_path)
        assert caps.max_module_lines == 2000, "Loosened cap (2000) was not respected"

    def test_custom_required_rule_groups_overrides_default(self, tmp_path: Path) -> None:
        """A custom required_rule_groups in pyproject.toml overrides the default set."""
        (tmp_path / "pyproject.toml").write_text(
            '[tool.guardrails]\nrequired_rule_groups = ["E", "F"]\n',
            encoding="utf-8",
        )

        caps = load_guardrail_caps(project_root=tmp_path)
        assert caps.required_rule_groups == frozenset({"E", "F"}), (
            f"Custom required_rule_groups not applied: got {caps.required_rule_groups}"
        )


# ---------------------------------------------------------------------------
# R5.3 — Missing configuration falls back gracefully
# ---------------------------------------------------------------------------


class TestMissingConfigFallback:
    """When [tool.guardrails] is absent, all caps fall back to defaults gracefully."""

    def test_missing_pyproject_falls_back_to_defaults(self, tmp_path: Path) -> None:
        """load_guardrail_caps with no pyproject.toml returns all-default caps."""
        # No pyproject.toml in tmp_path
        caps = load_guardrail_caps(project_root=tmp_path)
        assert caps.max_ignore_files == _BASELINE_MAX_IGNORE_FILES
        assert caps.max_module_lines == _BASELINE_MAX_MODULE_LINES

    def test_pyproject_without_guardrails_section_falls_back(self, tmp_path: Path) -> None:
        """A pyproject.toml without [tool.guardrails] falls back to all defaults."""
        (tmp_path / "pyproject.toml").write_text(
            "[project]\nname = 'test'\n[tool.ruff]\nselect = ['E', 'F']\n",
            encoding="utf-8",
        )

        caps = load_guardrail_caps(project_root=tmp_path)
        assert caps.max_ignore_files == _BASELINE_MAX_IGNORE_FILES
        assert caps.max_global_ignores == _BASELINE_MAX_GLOBAL_IGNORES
        assert caps.max_module_lines == _BASELINE_MAX_MODULE_LINES

    def test_caps_object_is_usable_without_pyproject(self, tmp_path: Path) -> None:
        """Caps loaded without any config do not raise errors when accessed."""
        caps = load_guardrail_caps(project_root=tmp_path)
        # All attributes must be accessible without raising
        _ = caps.max_ignore_files
        _ = caps.max_global_ignores
        _ = caps.max_per_file_ignores
        _ = caps.max_override_sections
        _ = caps.max_module_lines
        _ = caps.required_rule_groups
