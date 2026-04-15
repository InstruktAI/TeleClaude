"""Configurable guardrail caps — per-project quality thresholds from pyproject.toml.

Defaults match current TeleClaude hardcoded baselines so projects without
explicit configuration get production-grade enforcement.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class GuardrailCaps:
    """Per-project guardrail thresholds. Defaults match TeleClaude baselines."""

    max_ignore_files: int = 8
    max_global_ignores: int = 8
    max_per_file_ignores: int = 50
    max_override_sections: int = 13
    max_module_lines: int = 1000
    required_rule_groups: frozenset[str] = field(
        default_factory=lambda: frozenset({"E", "F", "I", "C90", "B", "UP", "RUF"})
    )


def load_guardrail_caps(project_root: Path) -> GuardrailCaps:
    """Load guardrail caps from [tool.guardrails] in pyproject.toml.

    Falls back to defaults gracefully when the file, section, or individual
    keys are missing.
    """
    pyproject = project_root / "pyproject.toml"
    if not pyproject.exists():
        return GuardrailCaps()

    with open(pyproject, "rb") as f:
        data = tomllib.load(f)

    guardrails = data.get("tool", {}).get("guardrails", {})
    if not guardrails:
        return GuardrailCaps()

    defaults = GuardrailCaps()
    rule_groups_raw = guardrails.get("required_rule_groups")
    return GuardrailCaps(
        max_ignore_files=guardrails.get("max_ignore_files", defaults.max_ignore_files),
        max_global_ignores=guardrails.get("max_global_ignores", defaults.max_global_ignores),
        max_per_file_ignores=guardrails.get("max_per_file_ignores", defaults.max_per_file_ignores),
        max_override_sections=guardrails.get("max_override_sections", defaults.max_override_sections),
        max_module_lines=guardrails.get("max_module_lines", defaults.max_module_lines),
        required_rule_groups=frozenset(rule_groups_raw)
        if rule_groups_raw is not None
        else defaults.required_rule_groups,
    )
