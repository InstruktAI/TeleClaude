"""Computer listing endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import CallerIdentity, carried_caller
from teleclaude.api_models import ComputerDTO
from teleclaude.config.machine import config
from teleclaude.core import command_handlers
from teleclaude.core.inbound.fleet import configure_known_computers, known_remote_computers

if TYPE_CHECKING:
    from teleclaude.core.cache import DaemonCache

logger = get_logger(__name__)

router = APIRouter()


def configure(cache: DaemonCache | None) -> None:
    """Wire cache; called from APIServer."""
    configure_known_computers(cache)


def _known_remote_computers() -> list[ComputerDTO]:
    """Remote computers this computer has discovered (online) or has configured (offline when not discovered)."""
    return [
        ComputerDTO(name=remote.name, status=remote.status.value, user=remote.user, host=remote.host, is_local=False)
        for remote in known_remote_computers()
    ]


@router.get("/computers")
async def list_computers(
    _identity: CallerIdentity = Depends(carried_caller),
) -> list[ComputerDTO]:
    """List available computers (local + cached remote computers)."""
    try:
        info = await command_handlers.get_computer_info()
        local = ComputerDTO(
            name=config.computer.name,
            status="online",
            user=info.user,
            host=info.host,
            is_local=True,
            tmux_binary=config.computer.tmux_binary,
        )
        return [local, *_known_remote_computers()]
    except Exception as e:
        logger.error("list_computers failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list computers.") from e
