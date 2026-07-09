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

from teleclaude.quality.scope import get_project_languages

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates" / "quality"

_LIFECYCLE_FILES: list[tuple[str, str]] = [("Makefile.template", "Makefile")]

_PYTHON_FILES: list[tuple[str, str]] = [
    ("pyproject.toml.template", "pyproject.toml"),
    ("pre-commit-config.yaml", ".pre-commit-config.yaml"),
    (".githooks/pre-commit", ".githooks/pre-commit"),
    (".githooks/post-merge", ".githooks/post-merge"),
]

_TYPESCRIPT_FILES: list[tuple[str, str]] = [
    ("tsconfig.json", "tsconfig.json"),
    ("eslint.config.mjs", "eslint.config.mjs"),
    ("prettierrc", ".prettierrc"),
    ("vitest.config.ts", "vitest.config.ts"),
]


def deploy_skeleton(project_root: Path) -> None:
    """Deploy skeleton files for detected project languages.

    Languages are detected from repo artifacts (pyproject.toml, tsconfig.json,
    Cargo.toml). frontend_root is read from teleclaude.yml when present,
    defaulting to 'frontend'. Existing identical files are skipped silently.
    Differing files trigger a diff-and-prompt in interactive mode, or are
    skipped in non-interactive mode.
    """
    languages = get_project_languages(project_root)
    if not languages:
        logger.info("No recognised language artifacts — skipping skeleton deployment")
        return

    _deploy_files(project_root, _TEMPLATES_DIR, _LIFECYCLE_FILES, project_root)

    config_path = project_root / "teleclaude.yml"
    frontend_root = "frontend"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict):
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

    _merge_gitignore(project_root, languages)


def _blessed_gitignore_lines(languages: list[str]) -> list[str]:
    """The blessed .gitignore lines: language-neutral base plus per-language additions.

    Every source is required — a missing template is a packaging omission, not a
    reason to silently degrade the defaults, so an absent file fails loudly.
    """
    sources = [_TEMPLATES_DIR / "gitignore"]
    sources.extend(_TEMPLATES_DIR / language / "gitignore" for language in languages)
    lines: list[str] = []
    for source in sources:
        if not source.exists():
            raise FileNotFoundError(f"Blessed .gitignore template missing: {source}")
        lines.extend(source.read_text(encoding="utf-8").splitlines())
    return lines


def _merge_gitignore(project_root: Path, languages: list[str]) -> None:
    """Union the blessed .gitignore patterns into the project's .gitignore.

    A .gitignore is the one skeleton file every project already owns and
    customizes, so it is merged, never copied over: this appends only the
    blessed patterns the project does not already ignore and never touches its
    existing entries. Idempotent — a re-run appends nothing.
    """
    target = project_root / ".gitignore"
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    # ``seen`` dedupes against the project's own entries and within the blessed
    # set itself (e.g. ``dist/`` shipped by both the python and typescript sets).
    seen = {line.strip() for line in existing.splitlines() if line.strip() and not line.strip().startswith("#")}
    missing: list[str] = []
    for line in _blessed_gitignore_lines(languages):
        pattern = line.strip()
        if pattern and not pattern.startswith("#") and pattern not in seen:
            missing.append(pattern)
            seen.add(pattern)
    if not missing:
        return

    addition = "\n".join(["# TeleClaude blessed defaults", *missing])
    body = existing.rstrip("\n")
    target.write_text(f"{body}\n\n{addition}\n" if body else f"{addition}\n", encoding="utf-8")
    logger.info("Merged %d blessed .gitignore pattern(s)", len(missing))


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

        target_path.parent.mkdir(parents=True, exist_ok=True)
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
