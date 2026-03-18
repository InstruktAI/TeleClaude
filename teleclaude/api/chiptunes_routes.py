"""Chiptunes playback control endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from instrukt_ai_logging import get_logger

from teleclaude.api_models import ChiptunesCommandReceiptDTO, ChiptunesStatusDTO
from teleclaude.config.runtime_settings import RuntimeSettings

logger = get_logger(__name__)

_RUNTIME_SETTINGS: dict[str, RuntimeSettings | None] = {"value": None}

router = APIRouter(prefix="/api/chiptunes", tags=["chiptunes"])


def configure(runtime_settings: RuntimeSettings | None) -> None:
    """Wire runtime_settings; called from APIServer at construction."""
    _RUNTIME_SETTINGS["value"] = runtime_settings


def _require_runtime_settings() -> RuntimeSettings:
    """Return the configured runtime settings or raise service unavailable."""
    runtime_settings = _RUNTIME_SETTINGS["value"]
    if runtime_settings is None:
        raise HTTPException(503, "Runtime settings not available")
    return runtime_settings


def _require_chiptunes_manager(runtime_settings: RuntimeSettings) -> object:
    """Return the configured chiptunes manager or raise service unavailable."""
    manager = getattr(runtime_settings, "_chiptunes_manager", None)
    if manager is None:
        raise HTTPException(503, "Chiptunes manager not available")
    return manager


def _build_chiptunes_status() -> ChiptunesStatusDTO:
    """Build the current chiptunes status DTO from runtime settings."""
    runtime_settings = _require_runtime_settings()
    manager = _require_chiptunes_manager(runtime_settings)
    runtime_state = runtime_settings.get_state().chiptunes
    track_label = Path(runtime_state.track_path).stem.replace("_", " ") if runtime_state.track_path else ""
    sid_path = runtime_state.track_path
    playing = runtime_state.playback == "playing"
    paused = runtime_state.playback == "paused"
    if manager.enabled:
        runtime_state = manager.capture_runtime_state()
        track_label = manager.current_track
        sid_path = manager.current_sid_path
        playing = manager.is_playing
        paused = manager.is_paused
    return ChiptunesStatusDTO(
        playback=runtime_state.playback,
        state_version=runtime_settings.chiptunes_state_version,
        loaded=manager.enabled,
        playing=playing,
        paused=paused,
        position_seconds=runtime_state.position_seconds,
        track=track_label,
        sid_path=sid_path,
        pending_command_id=runtime_state.pending_command_id,
        pending_action=runtime_state.pending_action,
    )


@router.post("/next", status_code=202)
async def chiptunes_next() -> ChiptunesCommandReceiptDTO:
    """Queue "next track" command and return receipt."""
    runtime_settings = _require_runtime_settings()
    _require_chiptunes_manager(runtime_settings)
    command_id = runtime_settings.issue_chiptunes_command("next")
    return ChiptunesCommandReceiptDTO(command_id=command_id, action="next")


@router.get("/status")
async def chiptunes_status() -> ChiptunesStatusDTO:
    """Return current chiptunes playback state."""
    return _build_chiptunes_status()


@router.post("/prev", status_code=202)
async def chiptunes_prev() -> ChiptunesCommandReceiptDTO:
    """Queue "previous track" command and return receipt."""
    runtime_settings = _require_runtime_settings()
    _require_chiptunes_manager(runtime_settings)
    command_id = runtime_settings.issue_chiptunes_command("prev")
    return ChiptunesCommandReceiptDTO(command_id=command_id, action="prev")


@router.post("/pause", status_code=202)
async def chiptunes_pause() -> ChiptunesCommandReceiptDTO:
    """Queue pause command and return receipt."""
    runtime_settings = _require_runtime_settings()
    _require_chiptunes_manager(runtime_settings)
    command_id = runtime_settings.issue_chiptunes_command("pause")
    return ChiptunesCommandReceiptDTO(command_id=command_id, action="pause")


@router.post("/resume", status_code=202)
async def chiptunes_resume() -> ChiptunesCommandReceiptDTO:
    """Queue resume command and return receipt."""
    runtime_settings = _require_runtime_settings()
    _require_chiptunes_manager(runtime_settings)
    command_id = runtime_settings.issue_chiptunes_command("resume")
    return ChiptunesCommandReceiptDTO(command_id=command_id, action="resume")
