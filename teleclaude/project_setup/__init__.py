"""Project setup exports for TeleClaude."""

from teleclaude.project_setup.gitattributes import update_gitattributes
from teleclaude.project_setup.init_flow import adopt_project, converge_project, create_project

__all__ = [
    "adopt_project",
    "converge_project",
    "create_project",
    "update_gitattributes",
]
