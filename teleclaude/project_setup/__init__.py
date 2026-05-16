"""Project setup exports for TeleClaude."""

from teleclaude.project_setup.git_filters import setup_git_filters
from teleclaude.project_setup.gitattributes import update_gitattributes
from teleclaude.project_setup.init_flow import init_project
from teleclaude.project_setup.sync import sync_project_artifacts

__all__ = [
    "init_project",
    "setup_git_filters",
    "sync_project_artifacts",
    "update_gitattributes",
]
