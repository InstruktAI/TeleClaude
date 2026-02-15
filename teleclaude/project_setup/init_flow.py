"""Project setup orchestration flow."""

from __future__ import annotations

from pathlib import Path

from teleclaude.install.install_hooks import main as install_agent_hooks
from teleclaude.project_setup.git_filters import setup_git_filters
from teleclaude.project_setup.git_repo import ensure_git_repo
from teleclaude.project_setup.gitattributes import update_gitattributes
from teleclaude.project_setup.hooks import install_precommit_hook
from teleclaude.project_setup.macos_setup import install_launchers, is_macos, run_permissions_probe
from teleclaude.project_setup.sync import install_docs_watch, sync_project_artifacts


def _is_teleclaude_project(project_root: Path) -> bool:
    """Check if this is the TeleClaude project itself (not a user project)."""
    marker = project_root / "teleclaude" / "project_setup" / "init_flow.py"
    return marker.exists()


def init_project(project_root: Path) -> None:
    """Initialize a project for TeleClaude.

    Sets up agent hooks, git filters, pre-commit hooks, syncs artifacts, and
    installs watchers.
    """
    install_agent_hooks()
    ensure_git_repo(project_root)
    setup_git_filters(project_root)
    update_gitattributes(project_root)
    install_precommit_hook(project_root)
    sync_project_artifacts(project_root)
    install_docs_watch(project_root)

    if is_macos():
        install_launchers(project_root)
        run_permissions_probe(project_root)

    # Bootstrap help desk workspace if running from the TeleClaude project
    if _is_teleclaude_project(project_root):
        from teleclaude.project_setup.help_desk_bootstrap import bootstrap_help_desk

        bootstrap_help_desk()

    print("telec init complete.")
