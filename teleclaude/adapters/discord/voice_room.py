"""Voice-room ownership, capture delivery, and Gateway-to-bridge forwarding."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from instrukt_ai_logging import get_logger

from teleclaude.adapters.discord.voice_bridge_messages import (
    OutboundBridgeMessage,
    UtteranceClosed,
    UtteranceDiscarded,
    UtteranceOpened,
    VoiceStateRequest,
)
from teleclaude.adapters.discord.voice_bridge_supervisor import VoiceBridgeSupervisor
from teleclaude.adapters.discord.voice_playback import VoicePlayback
from teleclaude.cli.config_handlers import get_global_config, get_person_config
from teleclaude.config import config
from teleclaude.core import voice_focus
from teleclaude.core.command_dispatch import dispatch_command
from teleclaude.core.identity import get_identity_resolver
from teleclaude.core.injected_text import InjectedTextSourceFeature, TranscriptEntryKind
from teleclaude.core.origins import InputOrigin
from teleclaude.core.voice_message_handler import transcribe_voice_with_retry
from teleclaude.types.commands import ProcessMessageCommand

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)


@dataclass(frozen=True)
class _ConfiguredRoom:
    person_slug: str
    user_id: str
    channel_id: int


@dataclass(frozen=True)
class _LatchedUtterance:
    person_slug: str
    user_id: str
    session_id: str
    target_computer: str | None


class VoiceRoom:
    """Own the master-only room lifecycle and deliver closed utterances once."""

    def __init__(self, client: AdapterClient, discord_client: object) -> None:
        self._client = client
        self._discord_client = discord_client
        self._identity_verified_room_ids: set[int] = set()
        self._room: _ConfiguredRoom | None = None
        self._utterances: dict[str, _LatchedUtterance] = {}
        self._supervisor = VoiceBridgeSupervisor(self._handle_bridge_message)
        self._playback = VoicePlayback(
            client, self._supervisor, lambda: self._room is not None and self._supervisor.is_open
        )

    @property
    def supervisor(self) -> VoiceBridgeSupervisor:
        return self._supervisor

    def mark_identity_verified(self, channel_id: int) -> None:
        self._identity_verified_room_ids.add(channel_id)

    def mark_identity_rejected(self, channel_id: int) -> None:
        self._identity_verified_room_ids.discard(channel_id)

    async def verify_configured_identities(self, discord_module: object) -> None:
        """Verify every declared voice token matches the already-running bot.

        The REST client is short lived and never enters the Gateway; failure
        leaves the room unavailable rather than allowing two bot identities.
        """
        running_id = getattr(getattr(self._discord_client, "user", None), "id", None)
        http_module = getattr(discord_module, "http", None)
        http_class = getattr(http_module, "HTTPClient", None)
        if not isinstance(running_id, int) or not callable(http_class):
            return
        for person in get_global_config().people:
            slug = getattr(person, "slug", None)
            if not isinstance(slug, str):
                continue
            try:
                person_config = get_person_config(slug)
                creds = person_config.creds.discord if person_config.creds else None
                if creds is None or not creds.voice_bot_token or not creds.voice_channel_id:
                    continue
                http: Any = http_class(loop=asyncio.get_running_loop())
                try:
                    profile = await http.static_login(creds.voice_bot_token)
                    bot_id = getattr(profile, "id", None)
                finally:
                    await http.close()
            except (OSError, RuntimeError, ValueError):
                logger.warning("discord_voice_config_rejected", reason="identity_unverified")
                continue
            channel_id = int(creds.voice_channel_id)
            if str(bot_id) != str(running_id):
                self.mark_identity_rejected(channel_id)
                logger.warning("discord_voice_config_rejected", room_id=channel_id, reason="bot_identity_mismatch")
                continue
            self.mark_identity_verified(channel_id)
            logger.info("discord_voice_identity_verified", room_id=channel_id)

    async def open_if_configured_person_present(self) -> None:
        """Handle the ready-time case where presence predates event registration."""
        if not config.computer.is_master:
            return
        guild_id = self._guild_id()
        guild_getter = getattr(self._discord_client, "get_guild", None)
        guild = guild_getter(guild_id) if guild_id is not None and callable(guild_getter) else None
        channel_getter = getattr(guild, "get_channel", None)
        if not callable(channel_getter):
            return
        for person in get_global_config().people:
            slug = getattr(person, "slug", None)
            if not isinstance(slug, str):
                continue
            try:
                person_config = get_person_config(slug)
                creds = person_config.creds.discord if person_config.creds else None
                if creds is None or not creds.voice_bot_token or not creds.voice_channel_id:
                    continue
                room = _ConfiguredRoom(slug, creds.user_id, int(creds.voice_channel_id))
            except (OSError, ValueError):
                continue
            members = getattr(channel_getter(room.channel_id), "members", ())
            present = any(str(getattr(member, "id", "")) == room.user_id for member in members)
            logger.info("discord_voice_ready_scan", room_id=room.channel_id, person_present=present)
            if present and self._owns(room)[0]:
                await self._open(room)
                return

    async def handle_voice_state(self, member: object, before: object, after: object) -> None:
        """Open/close only after identity, person, room, and master all agree."""
        user_id = str(getattr(member, "id", "")).strip()
        room = self._resolve_room(user_id)
        if room is None:
            return
        before_id = self._channel_id(getattr(before, "channel", None))
        after_id = self._channel_id(getattr(after, "channel", None))
        joined = after_id == room.channel_id and before_id != room.channel_id
        left = before_id == room.channel_id and after_id != room.channel_id
        if not joined and not left:
            return
        logger.info("discord_voice_state_handled", room_id=room.channel_id, joined=joined)
        owned, reason = self._owns(room)
        logger.info("discord_voice_ownership_decided", room_id=room.channel_id, owned=owned, reason=reason)
        if not owned:
            return
        if joined:
            await self._open(room)
        elif left:
            await self.close()

    async def forward_gateway_payload(self, event_type: str, payload: Mapping[str, object]) -> None:
        """Forward only this open room's raw voice Gateway events to the bridge."""
        room = self._room
        if room is None or not self._supervisor.is_open:
            return
        guild_id = payload.get("guild_id")
        if self._guild_id() is None or str(guild_id) != str(self._guild_id()):
            return
        if event_type == "VOICE_STATE_UPDATE":
            await self._supervisor.forward_voice_state(payload)
        elif event_type == "VOICE_SERVER_UPDATE":
            await self._supervisor.forward_voice_server(payload)

    async def close(self) -> None:
        await self._playback.close()
        self._room = None
        self._utterances.clear()
        await self._supervisor.close()

    async def play_current(self, session_id: str) -> None:
        room = self._room
        if room is not None:
            await self._playback.play_current(room.person_slug, session_id)

    async def focus_changed(self, session_id: str) -> None:
        room = self._room
        if room is not None:
            await self._playback.observe_focus(room.person_slug)
            await self._playback.play_current(room.person_slug, session_id)

    async def handle_observed_stop(self, session_id: str) -> None:
        """Refresh the remote owner before speaking its observed final output."""
        room = self._room
        cache = self._client.cache
        if room is None or cache is None:
            return
        snapshot = next((item for item in cache.get_sessions() if item.session_id == session_id), None)
        if snapshot is not None and snapshot.computer and snapshot.computer != config.computer.name:
            self._client.request_sessions_refresh(snapshot.computer, "observed_stop")
        await self._playback.play_current(room.person_slug, session_id)

    async def _open(self, room: _ConfiguredRoom) -> None:
        if self._supervisor.is_open:
            return
        guild_id = self._guild_id()
        if guild_id is None:
            logger.warning("discord_voice_config_rejected", room_id=room.channel_id, reason="guild_unresolved")
            return
        self._room = room
        try:
            await self._supervisor.open(
                guild_id=guild_id,
                channel_id=room.channel_id,
                configured_user_id=room.user_id,
            )
            await self._playback.observe_focus(room.person_slug)
        except (OSError, RuntimeError, TimeoutError) as exc:
            self._room = None
            logger.warning("discord_voice_connection_closed", room_id=room.channel_id, reason=type(exc).__name__)

    def _resolve_room(self, user_id: str) -> _ConfiguredRoom | None:
        identity = get_identity_resolver().resolve("discord", {"user_id": user_id, "discord_user_id": user_id})
        person_slug = identity.person_slug
        if person_slug is None:
            return None
        try:
            person_config = get_person_config(person_slug)
        except (OSError, ValueError):
            return None
        creds = person_config.creds.discord if person_config.creds else None
        if creds is None or creds.user_id != user_id or not creds.voice_channel_id or not creds.voice_bot_token:
            return None
        return _ConfiguredRoom(person_slug=person_slug, user_id=user_id, channel_id=int(creds.voice_channel_id))

    def _owns(self, room: _ConfiguredRoom) -> tuple[bool, str]:
        if room.channel_id not in self._identity_verified_room_ids:
            return False, "bot_identity_unverified"
        if not config.computer.is_master:
            return False, "not_master"
        return True, "master"

    @staticmethod
    def _channel_id(channel: object) -> int | None:
        value = getattr(channel, "id", None)
        return value if isinstance(value, int) else None

    def _guild_id(self) -> int | None:
        value = getattr(self._discord_client, "guilds", ())
        if not isinstance(value, tuple | list) or not value:
            return None
        guild_id = getattr(value[0], "id", None)
        return guild_id if isinstance(guild_id, int) else None

    async def _handle_bridge_message(self, message: OutboundBridgeMessage) -> None:
        if isinstance(message, VoiceStateRequest):
            await self._apply_voice_state_request(message)
        elif isinstance(message, UtteranceOpened):
            await self._latch_utterance(message)
        elif isinstance(message, UtteranceClosed):
            await self._deliver_utterance(message)
        elif isinstance(message, UtteranceDiscarded):
            self._utterances.pop(message.utteranceId, None)
            logger.info("voice_utterance_discarded", utterance_id=message.utteranceId, reason=message.reason)
        elif message.type == "protocol_error":
            self._room = None
            self._utterances.clear()
            logger.warning("discord_voice_connection_closed", reason="sidecar_ready_failed")
        elif message.type == "speaker_ignored":
            logger.info("voice_speaker_ignored", reason=message.reason)

    async def _apply_voice_state_request(self, message: VoiceStateRequest) -> None:
        guild_id = self._guild_id()
        if guild_id is None:
            return
        guild_getter = getattr(self._discord_client, "get_guild", None)
        guild = guild_getter(guild_id) if callable(guild_getter) else None
        change_voice_state = getattr(guild, "change_voice_state", None)
        channel_id = message.payload.get("channel_id")
        channel_getter = getattr(guild, "get_channel", None)
        channel = (
            channel_getter(int(channel_id)) if callable(channel_getter) and isinstance(channel_id, str | int) else None
        )
        if not callable(change_voice_state):
            return
        await cast(Callable[..., Awaitable[object]], change_voice_state)(
            channel=channel,
            self_mute=bool(message.payload.get("self_mute", False)),
            self_deaf=bool(message.payload.get("self_deaf", False)),
        )

    async def _latch_utterance(self, message: UtteranceOpened) -> None:
        room = self._room
        cache = self._client.cache
        if room is None or cache is None:
            return
        focus = await voice_focus.resolve(room.person_slug, cache.get_sessions())
        session_id = focus.focused_session_id
        if session_id is None:
            logger.info("voice_utterance_discarded", utterance_id=message.utteranceId, reason="no_focus")
            return
        snapshot = next((item for item in cache.get_sessions() if item.session_id == session_id), None)
        if snapshot is None:
            logger.info("voice_utterance_discarded", utterance_id=message.utteranceId, reason="session_unresolved")
            return
        self._utterances[message.utteranceId] = _LatchedUtterance(
            person_slug=room.person_slug,
            user_id=room.user_id,
            session_id=session_id,
            target_computer=snapshot.computer,
        )
        logger.info("voice_utterance_opened", utterance_id=message.utteranceId, session_id=session_id)

    async def _deliver_utterance(self, message: UtteranceClosed) -> None:
        latched = self._utterances.pop(message.utteranceId, None)
        audio_path = Path(message.audioPath)
        if latched is None or not self._supervisor.owns_recording(audio_path):
            logger.info("voice_utterance_discarded", utterance_id=message.utteranceId, reason="recording_untrusted")
            return
        try:
            text, _error = await transcribe_voice_with_retry(str(audio_path))
            if text is None:
                logger.warning(
                    "voice_utterance_discarded", utterance_id=message.utteranceId, reason="transcription_failed"
                )
                return
            command = ProcessMessageCommand(
                session_id=latched.session_id,
                text=text,
                origin=InputOrigin.DISCORD.value,
                text_kind=TranscriptEntryKind.ORDINARY,
                source_feature=InjectedTextSourceFeature.VOICE,
                occurrence_key=message.utteranceId,
                actor_id=latched.user_id,
                origin_metadata={"user_id": latched.user_id, "discord_user_id": latched.user_id},
            )
            command.computer = latched.target_computer
            await dispatch_command(self._client, command)
            logger.info(
                "voice_input_delivered", utterance_id=message.utteranceId, target_computer=latched.target_computer
            )
        except (OSError, RuntimeError, ValueError) as exc:
            logger.warning("voice_utterance_discarded", utterance_id=message.utteranceId, reason=type(exc).__name__)
        finally:
            audio_path.unlink(missing_ok=True)
