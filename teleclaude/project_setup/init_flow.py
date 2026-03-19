"""Project setup orchestration flow."""

from __future__ import annotations

from pathlib import Path

from teleclaude.project_setup._orchestration import run_project_init_flow
from teleclaude.project_setup.help_desk_bootstrap import bootstrap_help_desk


def init_project(project_root: Path) -> None:
    """Initialize a project for TeleClaude.

    Sets up agent hooks, git filters, pre-commit hooks, syncs artifacts, and
    installs watchers. Optionally runs AI-driven project analysis to generate
    doc snippets that make the codebase legible to AI.
    """
    run_project_init_flow(project_root, bootstrap_help_desk=bootstrap_help_desk)
