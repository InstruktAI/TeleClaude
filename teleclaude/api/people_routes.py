"""People listing endpoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from instrukt_ai_logging import get_logger

from teleclaude.api_models import PersonDTO
from teleclaude.cli.config_handlers import get_global_config

logger = get_logger(__name__)

router = APIRouter(prefix="/api/people", tags=["people"])


@router.get("")
async def list_people() -> list[PersonDTO]:
    """List people from global config (safe subset only)."""
    try:
        global_cfg = get_global_config()
        return [
            PersonDTO(
                name=p.name,
                email=p.email,
                role=p.role,
                expertise=p.expertise,
                proficiency=p.proficiency,
            )
            for p in global_cfg.people
        ]
    except (OSError, ValueError) as exc:
        logger.error("list_people failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list people: {exc}") from exc
