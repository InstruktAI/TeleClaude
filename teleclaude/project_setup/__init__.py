"""Project setup exports for TeleClaude."""

from teleclaude.project_setup.git_filters import setup_git_filters
from teleclaude.project_setup.gitattributes import update_gitattributes
from teleclaude.project_setup.hooks import install_precommit_hook
from teleclaude.project_setup.init_flow import init_project
from teleclaude.project_setup.sync import install_docs_watch, sync_project_artifacts

__all__ = [
    "init_project",
    "install_docs_watch",
    "install_precommit_hook",
    "setup_git_filters",
    "sync_project_artifacts",
    "update_gitattributes",
]
