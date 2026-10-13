"""Chiptunes playback control endpoints."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from instrukt_ai_logging import get_logger

from teleclaude.api_models_chiptunes import (
    CHIPTUNES_API_PREFIX,
    ChiptunesCommandReceiptDTO,
    ChiptunesPreference,
    ChiptunesPreferenceRequest,
    ChiptunesStatusDTO,
)
from teleclaude.chiptunes.dislikes import is_disliked, remove_dislike, save_dislike
from teleclaude.chiptunes.favorites import is_favorited, remove_favorite, save_favorite
from teleclaude.config.machine import config

if TYPE_CHECKING:
    from teleclaude.chiptunes.manager import ChiptunesManager

logger = get_logger(__name__)


@dataclass(frozen=True)
class TrackPreferences:
    """Whether the current track is marked a favourite or as disliked."""

    favorited: bool = False
    disliked: bool = False


type StatePublisher = Callable[[TrackPreferences], None]

_PREFERENCE_CHANGED = "chiptunes preference changed"
_SLOT = "value"
_TRACK_PATH_FIELD = "track_path"
_NO_TRACK = ""

_MANAGER: dict[str, ChiptunesManager | None] = {"value": None}
_PUBLISHER: dict[str, StatePublisher | None] = {_SLOT: None}

# Module-level state tracking (owned by routes, not manager)
_state_version: int = 0
_pending_command_id: str = ""
_pending_action: str = ""

router = APIRouter(prefix=CHIPTUNES_API_PREFIX, tags=["chiptunes"])


def configure(manager: ChiptunesManager | None, publish_state: StatePublisher | None = None) -> None:
    """Wire chiptunes manager and the playback-state publisher; called from daemon after lifecycle start."""
    _MANAGER["value"] = manager
    _PUBLISHER[_SLOT] = publish_state


def track_preferences(sid_path: str) -> TrackPreferences:
    """Read the preference stores for one track; blocking file reads, so callers run it off the event loop."""
    if not sid_path:
        return TrackPreferences()
    return TrackPreferences(favorited=is_favorited(sid_path), disliked=is_disliked(sid_path))


def current_track_preferences() -> TrackPreferences:
    """Preferences of the track the player last reported; blocking, as ``track_preferences``."""
    manager = _MANAGER[_SLOT]
    track_path = str(manager.last_state.get(_TRACK_PATH_FIELD, _NO_TRACK)) if manager is not None else _NO_TRACK
    return track_preferences(track_path)


def increment_state_version() -> None:
    """Increment the state version counter (called by daemon on state change)."""
    global _state_version
    _state_version += 1


def clear_pending(command_id: str) -> None:
    """Clear pending command if it matches (called by daemon on command_done)."""
    global _pending_command_id, _pending_action
    if command_id == _pending_command_id:
        _pending_command_id = ""
        _pending_action = ""


def chiptunes_configured() -> bool:
    """Whether machine configuration turns chiptunes on, distinct from the player having loaded."""
    chiptunes_config = config.chiptunes
    return bool(chiptunes_config and chiptunes_config.enabled)


def _require_manager() -> ChiptunesManager:
    """Return the configured manager or raise service unavailable."""
    manager = _MANAGER["value"]
    if manager is None:
        raise HTTPException(503, "Chiptunes manager not available")
    return manager


def _build_chiptunes_status(preferences: TrackPreferences) -> ChiptunesStatusDTO:
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
        configured=chiptunes_configured(),
        loaded=manager.enabled,
        playing=playing,
        paused=paused,
        position_seconds=position,
        track=track_label,
        sid_path=track_path,
        favorited=preferences.favorited,
        disliked=preferences.disliked,
        pending_command_id=_pending_command_id,
        pending_action=_pending_action,  # type: ignore[arg-type]
    )


def _issue_command(action: str) -> ChiptunesCommandReceiptDTO:
    """Generate uuid, enqueue command on manager, return receipt."""
    global _state_version, _pending_command_id, _pending_action
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
    preferences = await asyncio.to_thread(current_track_preferences)
    return _build_chiptunes_status(preferences)


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


@router.post("/stop", status_code=200)
async def chiptunes_stop() -> dict[str, str]:
    """Stop playback and kill the worker process."""
    manager = _require_manager()
    manager.stop()
    return {"status": "stopped"}


async def _set_preference(
    request: ChiptunesPreferenceRequest,
    *,
    mark: Callable[[str, str], None],
    unmark: Callable[[str], bool],
) -> ChiptunesStatusDTO:
    """Apply one preference change on a worker thread, then publish the playback state it alters."""
    if request.marked:
        await asyncio.to_thread(mark, request.track_name, request.sid_path)
    else:
        await asyncio.to_thread(unmark, request.sid_path)
    preferences = await asyncio.to_thread(current_track_preferences)
    publish = _PUBLISHER[_SLOT]
    if publish is not None:
        publish(preferences)
    return _build_chiptunes_status(preferences)


@router.put(ChiptunesPreference.FAVORITE.route)
async def chiptunes_favorite(request: ChiptunesPreferenceRequest) -> ChiptunesStatusDTO:
    """Mark or unmark a track as a favourite."""
    logger.info(
        _PREFERENCE_CHANGED, preference=ChiptunesPreference.FAVORITE, sid_path=request.sid_path, marked=request.marked
    )
    return await _set_preference(request, mark=save_favorite, unmark=remove_favorite)


@router.put(ChiptunesPreference.DISLIKE.route)
async def chiptunes_dislike(request: ChiptunesPreferenceRequest) -> ChiptunesStatusDTO:
    """Mark or unmark a track as disliked; the player keeps disliked tracks out of discovery."""
    logger.info(
        _PREFERENCE_CHANGED, preference=ChiptunesPreference.DISLIKE, sid_path=request.sid_path, marked=request.marked
    )
    return await _set_preference(request, mark=save_dislike, unmark=remove_dislike)
