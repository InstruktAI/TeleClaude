"""Idempotent bootstrap for the help desk workspace."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


def _resolve_help_desk_dir() -> Path:
    """Resolve help desk directory from config or default sibling location."""
    from teleclaude.config import config

    configured = config.computer.help_desk_dir
    if configured:
        return Path(configured).expanduser().resolve()
    # Default: sibling of TeleClaude project root
    teleclaude_root = Path(__file__).resolve().parents[2]
    return teleclaude_root.parent / "help-desk"


def bootstrap_help_desk() -> None:
    """Scaffold the help desk workspace if it does not exist.

    Idempotent: skips if the directory already exists.
    """
    help_desk_dir = _resolve_help_desk_dir()
    if help_desk_dir.exists():
        logger.info("help_desk_exists", path=str(help_desk_dir))
        return

    teleclaude_root = Path(__file__).resolve().parents[2]
    template_dir = teleclaude_root / "templates" / "help-desk"
    if not template_dir.exists():
        logger.warning("help_desk_template_missing", path=str(template_dir))
        return

    logger.info("help_desk_bootstrap_start", path=str(help_desk_dir))

    # Copy templates
    shutil.copytree(template_dir, help_desk_dir)

    try:
        # git init
        subprocess.run(["git", "init"], cwd=help_desk_dir, check=True, capture_output=True)

        # Run telec init inside the new directory
        from teleclaude.project_setup.init_flow import init_project

        init_project(help_desk_dir)

        # Initial commit
        subprocess.run(["git", "add", "."], cwd=help_desk_dir, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial help desk scaffold"],
            cwd=help_desk_dir,
            check=True,
            capture_output=True,
        )
    except Exception:
        shutil.rmtree(help_desk_dir, ignore_errors=True)
        raise

    logger.info("help_desk_bootstrap_complete", path=str(help_desk_dir))
