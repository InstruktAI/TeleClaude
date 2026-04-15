"""Skeleton deployment — deploy language-appropriate project skeleton files.

Templates are sourced from TeleClaude's own optimized configuration so new
projects start with production-grade defaults, not minimal stubs.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates" / "quality"

_PYTHON_FILES: list[tuple[str, str]] = [
    ("pyproject.toml.template", "pyproject.toml"),
    ("pre-commit-config.yaml", ".pre-commit-config.yaml"),
    ("Makefile.template", "Makefile"),
]


def deploy_skeleton(project_root: Path) -> None:
    """Deploy skeleton files for the project's declared language.

    Reads ``teleclaude.yml`` at *project_root* to determine the language.
    When no language is declared or the config is absent, returns silently.
    Existing files are never overwritten.
    """
    config_path = project_root / "teleclaude.yml"
    if not config_path.exists():
        logger.info("No teleclaude.yml — skipping skeleton deployment")
        return

    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        return

    language = data.get("language")
    if not language:
        logger.info("No language declared in teleclaude.yml — skipping skeleton deployment")
        return

    if language == "python":
        _deploy_python_skeleton(project_root)
    else:
        logger.info("No skeleton templates for language %r", language)


def _deploy_python_skeleton(project_root: Path) -> None:
    """Deploy Python project skeleton files from templates."""
    template_dir = _TEMPLATES_DIR / "python"
    project_name = project_root.name

    for template_name, target_name in _PYTHON_FILES:
        target_path = project_root / target_name
        if target_path.exists():
            logger.info("Skipping %s — already exists", target_name)
            continue

        template_path = template_dir / template_name
        if not template_path.exists():
            logger.warning("Template %s not found at %s", template_name, template_path)
            continue

        content = template_path.read_text(encoding="utf-8")
        content = content.replace("{{project_name}}", project_name)
        target_path.write_text(content, encoding="utf-8")
        logger.info("Deployed %s", target_name)
