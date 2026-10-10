"""Projection options a UI connection declares when it opens the shared WebSocket.

The options name the resource streams a connection receives and whether
soft-removed todos are included. They never name a computer and grant no reach:
what a stream carries is decided by the viewer's identity reach.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum


class WsStream(StrEnum):
    """Closed vocabulary of resource streams a UI connection can select."""

    SESSIONS = "sessions"
    PROJECTS = "projects"
    PREPARATION = "preparation"
    TODOS = "todos"


WS_STREAM_PARAM = "stream"
WS_INCLUDE_REMOVED_PARAM = "include_removed"
WS_FLAG_TRUE = "true"
WS_FLAG_FALSE = "false"

_UNKNOWN_STREAM_MESSAGE = "Unknown WebSocket stream: {stream}"
_MALFORMED_FLAG_MESSAGE = "Malformed include_removed flag: {value}"
_FLAG_WITHOUT_STREAM_MESSAGE = "include_removed requires at least one stream"


class WsProjectionOptionError(ValueError):
    """A connection declared projection options outside the closed vocabulary."""


@dataclass(frozen=True)
class WsProjectionOptions:
    """Streams a connection selects and whether soft-removed todos are included."""

    streams: frozenset[WsStream]
    include_removed: bool = False


def parse_ws_streams(raw_streams: Iterable[str]) -> frozenset[WsStream]:
    """Resolve stream names against the closed vocabulary, refusing any unknown name."""
    streams: set[WsStream] = set()
    for raw in raw_streams:
        try:
            streams.add(WsStream(raw))
        except ValueError as exc:
            raise WsProjectionOptionError(_UNKNOWN_STREAM_MESSAGE.format(stream=raw)) from exc
    return frozenset(streams)


def parse_ws_projection_options(
    raw_streams: Sequence[str],
    raw_include_removed: str | None,
) -> WsProjectionOptions | None:
    """Resolve connection query values into options.

    Returns None when the connection declares no options: it is then a legacy
    client that selects its streams with subscription frames. Unknown streams
    and malformed flags are refused, never coerced.
    """
    if not raw_streams:
        if raw_include_removed is not None:
            raise WsProjectionOptionError(_FLAG_WITHOUT_STREAM_MESSAGE)
        return None
    streams = parse_ws_streams(raw_streams)
    if raw_include_removed is None or raw_include_removed == WS_FLAG_FALSE:
        return WsProjectionOptions(streams=streams)
    if raw_include_removed == WS_FLAG_TRUE:
        return WsProjectionOptions(streams=streams, include_removed=True)
    raise WsProjectionOptionError(_MALFORMED_FLAG_MESSAGE.format(value=raw_include_removed))
