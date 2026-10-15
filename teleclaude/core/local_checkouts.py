"""The project checkouts registered on this computer."""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.cli.api_client import TelecAPIClient
from teleclaude.config.machine import config
from teleclaude.project_root import is_project_checkout

logger = get_logger(__name__)

NOT_A_CHECKOUT_EVENT = "Project skipped: it is not a checkout"


async def local_checkout_paths() -> list[str]:
    """Paths of the project checkouts on this computer, as the daemon lists its projects."""
    client = TelecAPIClient(daemon_credential=True)
    await client.connect()
    try:
        projects = await client.list_projects()
    finally:
        await client.close()
    paths: list[str] = []
    for project in projects:
        if project.computer and project.computer != config.computer.name:
            continue
        if not is_project_checkout(project.path):
            logger.debug(NOT_A_CHECKOUT_EVENT, project_path=project.path)
            continue
        paths.append(project.path)
    return paths
