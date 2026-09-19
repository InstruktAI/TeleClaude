"""Typed, versioned messages for the private Discord voice bridge.

The definitions mirror ``voice_bridge/src/protocol.ts``.  This module owns
boundary validation; callers receive a closed message vocabulary rather than
raw JSON from the sidecar.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class _BridgeMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    v: Literal[1] = 1
    generation: int = Field(ge=1)


class VoiceStateUpdate(_BridgeMessage):
    type: Literal["voice_state_update"]
    payload: dict[str, object]  # guard: loose-dict - opaque Discord Gateway payload


class VoiceServerUpdate(_BridgeMessage):
    type: Literal["voice_server_update"]
    payload: dict[str, object]  # guard: loose-dict - opaque Discord Gateway payload


class Join(_BridgeMessage):
    type: Literal["join"]
    guildId: str
    channelId: str


class Leave(_BridgeMessage):
    type: Literal["leave"]


class PlayArtifact(_BridgeMessage):
    type: Literal["play_artifact"]
    path: str


class CancelPlayback(_BridgeMessage):
    type: Literal["cancel_playback"]


InboundBridgeMessage = Annotated[
    VoiceStateUpdate | VoiceServerUpdate | Join | Leave | PlayArtifact | CancelPlayback,
    Field(discriminator="type"),
]


class Ready(_BridgeMessage):
    type: Literal["ready"]


class VoiceStateRequest(_BridgeMessage):
    type: Literal["voice_state_request"]
    payload: dict[str, object]  # guard: loose-dict - opaque Discord Gateway payload


class UtteranceOpened(_BridgeMessage):
    type: Literal["utterance_opened"]
    utteranceId: str


class UtteranceClosed(_BridgeMessage):
    type: Literal["utterance_closed"]
    utteranceId: str
    frames: int = Field(ge=0)
    audioPath: str


class UtteranceDiscarded(_BridgeMessage):
    type: Literal["utterance_discarded"]
    utteranceId: str
    reason: Literal["no_stop_sequence", "continuity_unproven"]


class SpeakerIgnored(_BridgeMessage):
    type: Literal["speaker_ignored"]
    reason: Literal["not_configured_user"]


class PlaybackFinished(_BridgeMessage):
    type: Literal["playback_finished"]


class ProtocolError(_BridgeMessage):
    type: Literal["protocol_error"]
    message: str


OutboundBridgeMessage = Annotated[
    Ready
    | VoiceStateRequest
    | UtteranceOpened
    | UtteranceClosed
    | UtteranceDiscarded
    | SpeakerIgnored
    | PlaybackFinished
    | ProtocolError,
    Field(discriminator="type"),
]

OUTBOUND_MESSAGES: TypeAdapter[OutboundBridgeMessage] = TypeAdapter(OutboundBridgeMessage)
