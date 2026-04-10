"""Shared typed state models for the chiptunes subsystem."""

from __future__ import annotations

from typing import Literal, TypedDict, cast

ChiptunesPlayback = Literal["cold", "paused", "playing"]


class ChiptunesState(TypedDict, total=False):
    """Serializable playback state shared between worker, manager, and API."""

    playback: ChiptunesPlayback
    track_path: str
    position_seconds: float
    history: list[str]
    history_index: int


def coerce_chiptunes_state(raw_state: object) -> ChiptunesState:
    """Return a typed playback state from untrusted JSON-decoded input."""
    if not isinstance(raw_state, dict):
        return {}

    state: ChiptunesState = {}

    playback = raw_state.get("playback")
    if isinstance(playback, str) and playback in {"cold", "paused", "playing"}:
        state["playback"] = cast(ChiptunesPlayback, playback)

    track_path = raw_state.get("track_path")
    if isinstance(track_path, str):
        state["track_path"] = track_path

    position_seconds = raw_state.get("position_seconds")
    if isinstance(position_seconds, int | float) and not isinstance(position_seconds, bool):
        state["position_seconds"] = float(position_seconds)

    history = raw_state.get("history")
    if isinstance(history, list):
        state["history"] = [item for item in history if isinstance(item, str)]

    history_index = raw_state.get("history_index")
    if isinstance(history_index, int) and not isinstance(history_index, bool):
        state["history_index"] = history_index
    elif isinstance(history_index, float) and history_index.is_integer():
        state["history_index"] = int(history_index)

    return state
