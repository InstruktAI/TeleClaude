"""Chiptunes playback control endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from instrukt_ai_logging import get_logger

from teleclaude.api_models import ChiptunesCommandReceiptDTO, ChiptunesStatusDTO

if TYPE_CHECKING:
    from teleclaude.chiptunes.manager import ChiptunesManager

logger = get_logger(__name__)

_MANAGER: dict[str, ChiptunesManager | None] = {"value": None}

# Module-level state tracking (owned by routes, not manager)
_state_version: int = 0
_pending_command_id: str = ""
_pending_action: str = ""

router = APIRouter(prefix="/api/chiptunes", tags=["chiptunes"])


def configure(manager: ChiptunesManager | None) -> None:
    """Wire chiptunes manager; called from daemon after lifecycle start."""
    _MANAGER["value"] = manager


def increment_state_version() -> None:
    """Increment the state version counter (called by daemon on state change)."""
    global _state_version  # noqa: PLW0603
    _state_version += 1


def clear_pending(command_id: str) -> None:
    """Clear pending command if it matches (called by daemon on command_done)."""
    global _pending_command_id, _pending_action  # noqa: PLW0603
    if command_id == _pending_command_id:
        _pending_command_id = ""
        _pending_action = ""


def _require_manager() -> ChiptunesManager:
    """Return the configured manager or raise service unavailable."""
    manager = _MANAGER["value"]
    if manager is None:
        raise HTTPException(503, "Chiptunes manager not available")
    return manager


def _build_chiptunes_status() -> ChiptunesStatusDTO:
    """Build the current chiptunes status DTO from manager state."""
    manager = _require_manager()
    state = manager.last_state
    track_path = str(state.get("track_path", ""))
    track_label = Path(track_path).stem.replace("_", " ") if track_path else ""
    playback = str(state.get("playback", "cold"))
    playing = playback == "playing"
    paused = playback == "paused"
    position = float(state.get("position_seconds", 0.0))
    return ChiptunesStatusDTO(
        playback=playback,  # type: ignore[arg-type]
        state_version=_state_version,
        loaded=manager.enabled,
        playing=playing,
        paused=paused,
        position_seconds=position,
        track=track_label,
        sid_path=track_path,
        pending_command_id=_pending_command_id,
        pending_action=_pending_action,  # type: ignore[arg-type]
    )


def _issue_command(action: str) -> ChiptunesCommandReceiptDTO:
    """Generate uuid, enqueue command on manager, return receipt."""
    global _state_version, _pending_command_id, _pending_action  # noqa: PLW0603
    manager = _require_manager()
    command_id = uuid4().hex
    _pending_command_id = command_id
    _pending_action = action
    _state_version += 1
    manager.enqueue_command(command_id, action)  # type: ignore[arg-type]
    return ChiptunesCommandReceiptDTO(command_id=command_id, action=action)  # type: ignore[arg-type]


@router.post("/next", status_code=202)
async def chiptunes_next() -> ChiptunesCommandReceiptDTO:
    """Queue "next track" command and return receipt."""
    return _issue_command("next")


@router.get("/status")
async def chiptunes_status() -> ChiptunesStatusDTO:
    """Return current chiptunes playback state."""
    return _build_chiptunes_status()


@router.post("/prev", status_code=202)
async def chiptunes_prev() -> ChiptunesCommandReceiptDTO:
    """Queue "previous track" command and return receipt."""
    return _issue_command("prev")


@router.post("/pause", status_code=202)
async def chiptunes_pause() -> ChiptunesCommandReceiptDTO:
    """Queue pause command and return receipt."""
    return _issue_command("pause")


@router.post("/resume", status_code=202)
async def chiptunes_resume() -> ChiptunesCommandReceiptDTO:
    """Queue resume command and return receipt."""
    return _issue_command("resume")
