"""Project setup exports for TeleClaude."""

from teleclaude.project_setup.gitattributes import update_gitattributes
from teleclaude.project_setup.init_flow import init_project

__all__ = [
    "init_project",
    "update_gitattributes",
]
