"""Chiptunes API DTOs: playback status, state and track events, command receipts, and preference requests."""

import posixpath
from enum import StrEnum
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

CHIPTUNES_API_PREFIX: Final = "/api/chiptunes"


class ChiptunesPreference(StrEnum):
    """The marks a listener can put on a track; each has its own route under the chiptunes API."""

    FAVORITE = "favorite"
    DISLIKE = "dislike"

    @property
    def route(self) -> str:
        """The route, under the chiptunes router, that marks or unmarks a track with this preference."""
        return posixpath.join(posixpath.sep, self.value)

    @property
    def path(self) -> str:
        """The full path of that route."""
        return posixpath.join(CHIPTUNES_API_PREFIX, self.value)


class ChiptunesTrackEventDTO(BaseModel):
    """WebSocket event when a new chiptunes track starts playing."""

    model_config = ConfigDict(frozen=True)

    event: Literal["chiptunes_track"] = "chiptunes_track"
    track: str
    sid_path: str = ""
    favorited: bool = False
    disliked: bool = False


class ChiptunesStatusDTO(BaseModel):
    """Current chiptunes playback state."""

    model_config = ConfigDict(frozen=True)

    playback: Literal["cold", "loading", "playing", "paused"] = "cold"
    state_version: int = 0
    configured: bool = False
    loaded: bool = False
    playing: bool = False
    paused: bool = False
    position_seconds: float = 0.0
    track: str = ""
    sid_path: str = ""
    favorited: bool = False
    disliked: bool = False
    pending_command_id: str = ""
    pending_action: Literal["", "resume", "pause", "next", "prev"] = ""


class ChiptunesStateEventDTO(BaseModel):
    """WebSocket event for chiptunes playback state transitions."""

    model_config = ConfigDict(frozen=True)

    event: Literal["chiptunes_state"] = "chiptunes_state"
    playback: Literal["cold", "loading", "playing", "paused"] = "cold"
    state_version: int = 0
    configured: bool = False
    loaded: bool = False
    playing: bool = False
    paused: bool = False
    position_seconds: float = 0.0
    track: str = ""
    sid_path: str = ""
    favorited: bool = False
    disliked: bool = False
    pending_command_id: str = ""
    pending_action: Literal["", "resume", "pause", "next", "prev"] = ""


class ChiptunesCommandReceiptDTO(BaseModel):
    """Receipt for accepted chiptunes command (asynchronous execution)."""

    model_config = ConfigDict(frozen=True)

    status: Literal["accepted"] = "accepted"
    command_id: str
    action: Literal["resume", "pause", "next", "prev"]


class ChiptunesPreferenceRequest(BaseModel):
    """Mark or unmark a track as a favourite or as disliked, naming it by its SID path with its display name."""

    model_config = ConfigDict(frozen=True)

    sid_path: str = Field(min_length=1)
    track_name: str = ""
    marked: bool
