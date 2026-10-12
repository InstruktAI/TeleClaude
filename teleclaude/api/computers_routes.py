"""Computer listing endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import CallerIdentity, carried_caller
from teleclaude.api_models import ComputerDTO
from teleclaude.config.machine import config
from teleclaude.core import command_handlers

if TYPE_CHECKING:
    from teleclaude.core.cache import DaemonCache

logger = get_logger(__name__)

_CACHE: dict[str, DaemonCache | None] = {"value": None}

router = APIRouter()


def configure(cache: DaemonCache | None) -> None:
    """Wire cache; called from APIServer."""
    _CACHE["value"] = cache


def _known_remote_computers() -> list[ComputerDTO]:
    """Remote computers this computer has discovered (online) or has configured (offline when not discovered)."""
    # Track names already listed (case-insensitive) to avoid duplicates, starting with this computer.
    seen_names: set[str] = {config.computer.name.lower()}
    remotes: list[ComputerDTO] = []

    cache = _CACHE["value"]
    if cache:
        for comp in cache.get_computers():
            remotes.append(
                ComputerDTO(
                    name=comp.name,
                    status="online",
                    user=comp.user,
                    host=comp.host,
                    is_local=False,
                )
            )
            seen_names.add(comp.name.lower())

    for remote in config.remote_computers:
        if remote.name.lower() not in seen_names:
            remotes.append(
                ComputerDTO(
                    name=remote.name,
                    status="offline",
                    user=remote.user,
                    host=remote.host,
                    is_local=False,
                )
            )
    return remotes


def known_computer_names() -> frozenset[str]:
    """Every computer name this computer has configured or discovered, itself included."""
    return frozenset({config.computer.name, *(remote.name for remote in _known_remote_computers())})


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
        )
        return [local, *_known_remote_computers()]
    except Exception as e:
        logger.error("list_computers failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list computers.") from e
