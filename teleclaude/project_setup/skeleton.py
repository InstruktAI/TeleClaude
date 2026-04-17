"""Skeleton deployment — deploy language-appropriate project skeleton files.

Templates are sourced from TeleClaude's own optimized configuration so new
projects start with production-grade defaults, not minimal stubs.
"""

from __future__ import annotations

import difflib
import logging
import sys
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates" / "quality"

_PYTHON_FILES: list[tuple[str, str]] = [
    ("pyproject.toml.template", "pyproject.toml"),
    ("pre-commit-config.yaml", ".pre-commit-config.yaml"),
    ("Makefile.template", "Makefile"),
]

_TYPESCRIPT_FILES: list[tuple[str, str]] = [
    ("tsconfig.json", "tsconfig.json"),
    ("eslint.config.mjs", "eslint.config.mjs"),
    ("prettierrc", ".prettierrc"),
    ("vitest.config.ts", "vitest.config.ts"),
]


def deploy_skeleton(project_root: Path) -> None:
    """Deploy skeleton files for the project's declared languages.

    Reads ``teleclaude.yml`` at *project_root* to determine languages.
    When no languages are declared or the config is absent, returns silently.
    Existing identical files are skipped silently. Differing files trigger a
    diff-and-prompt in interactive mode, or are skipped in non-interactive mode.
    """
    config_path = project_root / "teleclaude.yml"
    if not config_path.exists():
        logger.info("No teleclaude.yml — skipping skeleton deployment")
        return

    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        return

    raw_languages = data.get("languages", [])
    if raw_languages and isinstance(raw_languages, list):
        languages = [str(lang) for lang in raw_languages]
    else:
        lang = data.get("language")
        languages = [str(lang)] if lang else []

    if not languages:
        logger.info("No languages declared in teleclaude.yml — skipping skeleton deployment")
        return

    frontend_root = str(data.get("frontend_root", "frontend"))

    for language in languages:
        if language == "python":
            _deploy_files(project_root, _TEMPLATES_DIR / "python", _PYTHON_FILES, project_root)
        elif language == "typescript":
            target_dir = project_root / frontend_root
            if not target_dir.exists():
                logger.info("Frontend root %s does not exist — skipping TypeScript skeleton", target_dir)
                continue
            _deploy_files(project_root, _TEMPLATES_DIR / "typescript", _TYPESCRIPT_FILES, target_dir)
        else:
            logger.info("No skeleton templates for language %r", language)


def _deploy_files(
    project_root: Path,
    template_dir: Path,
    file_list: list[tuple[str, str]],
    target_dir: Path,
) -> None:
    """Deploy template files to the target directory."""
    project_name = project_root.name

    for template_name, target_name in file_list:
        target_path = target_dir / target_name
        template_path = template_dir / template_name
        if not template_path.exists():
            logger.warning("Template %s not found at %s", template_name, template_path)
            continue

        content = template_path.read_text(encoding="utf-8")
        content = content.replace("{{project_name}}", project_name)

        if not target_path.exists():
            target_path.write_text(content, encoding="utf-8")
            logger.info("Deployed %s", target_name)
        elif target_path.read_text(encoding="utf-8") == content:
            pass  # identical — skip silently
        else:
            _handle_diff(target_path, content, target_name)


def _handle_diff(target_path: Path, template_content: str, target_name: str) -> None:
    """Show diff and prompt for override when a file differs from template."""
    if not sys.stdin.isatty():
        logger.info("Skipping %s — exists and differs (run interactively to review)", target_name)
        return

    existing = target_path.read_text(encoding="utf-8")
    diff = difflib.unified_diff(
        existing.splitlines(keepends=True),
        template_content.splitlines(keepends=True),
        fromfile=f"current/{target_name}",
        tofile=f"template/{target_name}",
    )
    diff_text = "".join(diff)
    if diff_text:
        print(f"\n--- {target_name} differs from upstream template ---")
        print(diff_text)
        answer = input(f"Override {target_name} with upstream template? [y/N] ").strip().lower()
        if answer == "y":
            target_path.write_text(template_content, encoding="utf-8")
            logger.info("Overrode %s with upstream template", target_name)
        else:
            logger.info("Kept existing %s", target_name)
