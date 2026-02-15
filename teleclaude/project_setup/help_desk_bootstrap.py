"""Idempotent bootstrap for the help desk operator workspace."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _resolve_help_desk_dir(teleclaude_root: Path) -> Path:
    """Resolve the help desk directory from config or default to sibling of teleclaude root."""
    try:
        from teleclaude.config import config

        configured = config.computer.help_desk_dir
        if configured:
            return Path(configured).expanduser()
    except Exception:
        logger.debug("Could not load config for help_desk_dir; using default")

    return teleclaude_root.parent / "help-desk"


def bootstrap_help_desk(teleclaude_root: Path) -> None:
    """Idempotent bootstrap for help desk workspace.

    Copies the help-desk template to the target directory, initializes a git repo,
    and creates an initial commit. Skips if the directory already exists.
    """
    help_desk_dir = _resolve_help_desk_dir(teleclaude_root)

    if help_desk_dir.exists():
        logger.info("Help desk directory already exists: %s", help_desk_dir)
        return

    template_dir = teleclaude_root / "templates" / "help-desk"
    if not template_dir.exists():
        logger.warning("Help desk template not found at %s; skipping bootstrap", template_dir)
        return

    logger.info("Bootstrapping help desk workspace at %s", help_desk_dir)

    shutil.copytree(template_dir, help_desk_dir)

    subprocess.run(["git", "init"], cwd=help_desk_dir, capture_output=True, check=True)

    subprocess.run(["git", "add", "."], cwd=help_desk_dir, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial help desk scaffold"],
        cwd=help_desk_dir,
        capture_output=True,
        check=True,
    )

    logger.info("Help desk workspace bootstrapped at %s", help_desk_dir)
