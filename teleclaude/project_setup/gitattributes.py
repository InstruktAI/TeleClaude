"""Gitattributes management for TeleClaude docs filter."""

from pathlib import Path

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

_GITATTRIBUTES_UPDATED_EVENT = "project_gitattributes_updated"

FILTER_PATTERNS = [
    "docs/**/*.md filter=teleclaude-docs",
    "agents/docs/**/*.md filter=teleclaude-docs",
]


def update_gitattributes(project_root: Path) -> None:
    """Add teleclaude-docs filter patterns to .gitattributes.

    Args:
        project_root: Path to the project root directory.
    """
    gitattributes = project_root / ".gitattributes"

    existing_content = ""
    if gitattributes.exists():
        existing_content = gitattributes.read_text(encoding="utf-8")

    lines_to_add = [p for p in FILTER_PATTERNS if p not in existing_content]

    if lines_to_add:
        with open(gitattributes, "a", encoding="utf-8") as f:
            if existing_content and not existing_content.endswith("\n"):
                f.write("\n")
            f.write("\n".join(lines_to_add) + "\n")
        logger.info(_GITATTRIBUTES_UPDATED_EVENT, project_root=str(project_root))
