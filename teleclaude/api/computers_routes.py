"""Computer listing endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from instrukt_ai_logging import get_logger

from teleclaude.api.auth import CallerIdentity, clearance_computers_list
from teleclaude.api_models import ComputerDTO
from teleclaude.config import config
from teleclaude.core import command_handlers

if TYPE_CHECKING:
    from teleclaude.core.cache import DaemonCache

logger = get_logger(__name__)

_CACHE: dict[str, DaemonCache | None] = {"value": None}

router = APIRouter()


def configure(cache: DaemonCache | None) -> None:
    """Wire cache; called from APIServer."""
    _CACHE["value"] = cache


@router.get("/computers")
async def list_computers(
    _identity: CallerIdentity = Depends(clearance_computers_list),
) -> list[ComputerDTO]:
    """List available computers (local + cached remote computers)."""
    try:
        # Local computer
        info = await command_handlers.get_computer_info()
        result: list[ComputerDTO] = [
            ComputerDTO(
                name=config.computer.name,
                status="online",
                user=info.user,
                host=info.host,
                is_local=True,
                tmux_binary=info.tmux_binary,
            )
        ]

        # Add cached remote computers (if available)
        cache = _CACHE["value"]
        if cache:
            cached_computers = cache.get_computers()
            for comp in cached_computers:
                result.append(
                    ComputerDTO(
                        name=comp.name,
                        status="online",
                        user=comp.user,
                        host=comp.host,
                        is_local=False,
                    )
                )

        return result
    except Exception as e:
        logger.error("list_computers failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list computers: {e}") from e
