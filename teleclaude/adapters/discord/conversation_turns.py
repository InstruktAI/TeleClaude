"""Conversation turns mixin for the Discord adapter.

A direct message to the bot is conversation input to the sender's personal assistant, and so is a
message in a provisioned Team assistant channel. Each such Discord message becomes one turn handed
to the core conversation seam (`teleclaude.core.inbound.conversation`), which owns where it goes.
The turn carries the message's text and every attachment as one delivery, so the channel resolves
to its conversation once however many parts the message has
(`local/projects/teleclaude/spec/feature/integration/discord-personal-assistant-channels`).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.adapters.discord.gateway_handlers import sender_role_for_session
from teleclaude.adapters.discord.inbound_continuity import await_conclusion
from teleclaude.adapters.discord.team_channels import team_channel_conversation
from teleclaude.cli.config_handlers import get_person_config
from teleclaude.core.command_input import CommandInputMode
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.endpoints import parse_entry_identifier
from teleclaude.core.identity import (
    DiscordAvatarBindingOutcome,
    DiscordAvatarBindingReason,
    IdentityContext,
    get_identity_resolver,
    observe_discord_avatar_binding,
)
from teleclaude.core.inbound import (
    BindOutcome,
    ConversationRef,
    ConversationTurn,
    EntryGesture,
    TurnCreation,
    TurnModality,
    resolve_binding_key,
)
from teleclaude.core.inbound.conversation import handle_conversation_turn
from teleclaude.core.inbound.models import DISCORD_DM_KEY_FIELD
from teleclaude.core.injected_text import InjectedTextSourceFeature, TranscriptEntryKind
from teleclaude.core.models import DiscordMetadataField, MessageMetadata, Session, SessionEntryPoint
from teleclaude.core.origins import InputOrigin
from teleclaude.invite import bind_discord_credentials
from teleclaude.types.commands import ProcessMessageCommand

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = get_logger(__name__)

_USER_ID_FIELD = "user_id"
_DISCORD_USER_ID_FIELD = "discord_user_id"
_PLATFORM_FIELD = "platform"
_PROCESS_MESSAGE_EVENT = "process_message"
_AUTHOR_ATTR = "author"
_CHANNEL_ATTR = "channel"
_GUILD_ATTR = "guild"
_CONTENT_ATTR = "content"
_ID_ATTR = "id"
_ATTACHMENTS_ATTR = "attachments"
_CONTENT_TYPE_ATTR = "content_type"
_AUDIO_CONTENT_TYPE_PREFIX = "audio/"
_NO_TEXT = ""
_NO_INVITATION_ERROR = "a designated channel carries no invitation"


@dataclass(frozen=True)
class _MessageInput:
    """What one Discord message carries toward a conversation: its text, audio attachments and other files."""

    text: str
    audio: tuple[object, ...]
    files: tuple[object, ...]

    @property
    def modality(self) -> TurnModality:
        return TurnModality.MEDIA if self.audio or self.files else TurnModality.TEXT

    @property
    def is_empty(self) -> bool:
        return not (self.text or self.audio or self.files)


@dataclass(frozen=True)
class _MessageSender:
    """Who sent one Discord message, as the conversation seam and the delivered commands name them."""

    user_id: str
    identity: IdentityContext
    actor_id: str | None
    actor_name: str
    actor_avatar_url: str | None


def _read_message_input(message: object) -> _MessageInput:
    """Split a Discord message into its text and its attachments by kind."""
    content = getattr(message, _CONTENT_ATTR, None)
    text = content.strip() if isinstance(content, str) else _NO_TEXT
    audio: list[object] = []
    files: list[object] = []
    for attachment in getattr(message, _ATTACHMENTS_ATTR, None) or ():
        content_type = getattr(attachment, _CONTENT_TYPE_ATTR, None) or _NO_TEXT
        (audio if content_type.startswith(_AUDIO_CONTENT_TYPE_PREFIX) else files).append(attachment)
    return _MessageInput(text=text, audio=tuple(audio), files=tuple(files))


async def _invitations_not_carried(_person_slug: str) -> BindOutcome:
    """A designated channel carries no entry identifier, so no invitation is bound through it."""
    raise ValueError(_NO_INVITATION_ERROR)


class ConversationTurnsMixin:
    """Mixin providing Discord direct-message and Team-channel conversation input for DiscordAdapter.

    Required host attributes:
    - _parse_optional_int(value) -> int | None
    - _discord_actor_name(author, user_id) -> str
    - _discord_actor_avatar_url(author) -> str | None
    - _metadata(**kwargs) -> MessageMetadata
    - _dispatch_command(session, message_id, metadata, command_name, payload, handler, *, retain_refusal) (async)
    - _dispatch_voice_attachment(session, message, attachment, *, recovered_at, retain_refusal) -> Task | None (async)
    - _dispatch_file_attachments(session, message, attachments, *, recovered_at, retain_refusal) (async)
    """

    if TYPE_CHECKING:

        def _parse_optional_int(self, value: object) -> int | None: ...

        @staticmethod
        def _discord_actor_name(author: object, user_id: str) -> str: ...

        @staticmethod
        def _discord_actor_avatar_url(author: object) -> str | None: ...

        def _metadata(self, **kwargs: object) -> MessageMetadata: ...

        async def _dispatch_command(
            self,
            session: Session,
            message_id: str | None,
            metadata: MessageMetadata,
            command_name: str,
            payload: dict[str, object],  # guard: loose-dict - Command payload for UI adapters
            handler: Callable[[], Awaitable[object]],
            *,
            retain_refusal: bool = False,
        ) -> object: ...

        async def _dispatch_voice_attachment(
            self,
            session: Session,
            message: object,
            attachment: object,
            *,
            recovered_at: datetime | None = None,
            retain_refusal: bool = False,
        ) -> asyncio.Task[object] | None: ...

        async def _dispatch_file_attachments(
            self,
            session: Session,
            message: object,
            attachments: list[object],
            *,
            recovered_at: datetime | None = None,
            retain_refusal: bool = False,
        ) -> None: ...

    def _message_sender(self, message: object) -> _MessageSender | None:
        """The sender of a Discord message resolved to their identity, or ``None`` for a message without an author."""
        author = getattr(message, _AUTHOR_ATTR, None)
        if not author:
            return None
        user_id = str(getattr(author, _ID_ATTR, _NO_TEXT))
        identity = get_identity_resolver().resolve(
            InputOrigin.DISCORD.value, {_USER_ID_FIELD: user_id, _DISCORD_USER_ID_FIELD: user_id}
        )
        return _MessageSender(
            user_id=user_id,
            identity=identity,
            actor_id=resolve_binding_key(InputOrigin.DISCORD.value, {_USER_ID_FIELD: user_id}),
            actor_name=(identity.person_name or _NO_TEXT).strip() or self._discord_actor_name(author, user_id),
            actor_avatar_url=self._discord_actor_avatar_url(author),
        )

    async def _deliver_message_text(
        self,
        session: Session,
        message: object,
        text: str,
        sender: _MessageSender,
        channel_id: int,
        recovered_at: datetime | None = None,
        retain_refusal: bool = False,
    ) -> None:
        """Dispatch the text of a conversation message to its session as one input."""
        message_id = str(getattr(message, _ID_ATTR, _NO_TEXT)).strip()
        cmd = ProcessMessageCommand(
            session_id=session.session_id,
            text=text,
            origin=InputOrigin.DISCORD.value,
            text_kind=TranscriptEntryKind.ORDINARY,
            source_feature=InjectedTextSourceFeature.DISCORD,
            occurrence_key=message_id or None,
            actor_id=sender.actor_id,
            actor_name=sender.actor_name,
            actor_avatar_url=sender.actor_avatar_url,
            source_message_id=message_id or None,
            source_channel_id=str(channel_id),
            command_input_mode=CommandInputMode.INTERACTIVE_SHORTHAND,
            sender_human_role=sender_role_for_session(sender.identity, session),
            recovered_posted_at=recovered_at,
        )
        metadata = self._metadata(
            platform_message_id=message_id or None,
            actor_id=sender.actor_id,
            actor_name=sender.actor_name,
            actor_avatar_url=sender.actor_avatar_url,
        )
        await self._dispatch_command(
            session,
            message_id or None,
            metadata,
            _PROCESS_MESSAGE_EVENT,
            cmd.to_payload(),
            lambda: get_command_service().process_message(cmd),
            retain_refusal=retain_refusal,
        )

    async def _deliver_message_input(
        self,
        session: Session,
        message: object,
        content: _MessageInput,
        sender: _MessageSender,
        channel_id: int,
        recovered_at: datetime | None = None,
        retain_refusal: bool = False,
    ) -> list[asyncio.Task[object]]:
        """Deliver everything one Discord message carries to its resolved conversation session, once.

        The text accompanies the first file as its caption, and stands alone as its own input only
        when no file carries it. Each part is accepted under its provider identity. The transcriptions of
        its voice attachments run on, and their tasks are returned for a caller that must wait for them.

        A draining refusal is answered to the sender. A caller whose conversation is recovered after the restart
        sets ``retain_refusal``: the refusal is then carried on without a notice, so the message stays unprocessed.
        """
        if content.text and not content.files:
            await self._deliver_message_text(
                session, message, content.text, sender, channel_id, recovered_at, retain_refusal
            )
        if content.files:
            await self._dispatch_file_attachments(
                session, message, list(content.files), recovered_at=recovered_at, retain_refusal=retain_refusal
            )
        transcriptions: list[asyncio.Task[object]] = []
        for attachment in content.audio:
            transcription = await self._dispatch_voice_attachment(
                session, message, attachment, recovered_at=recovered_at, retain_refusal=retain_refusal
            )
            if transcription is not None:
                transcriptions.append(transcription)
        return transcriptions

    async def _handle_discord_dm(self, message: object) -> None:
        """Hand one direct message to the conversation seam: an identifier is an entry, else an ordinary turn.

        A message of attachments alone, or with text, is one turn of the DM's conversation; an entry
        identifier is exactly the text of a message that carries nothing else.
        """
        sender = self._message_sender(message)
        if sender is None:
            return
        content = _read_message_input(message)
        if content.is_empty:
            return
        channel = getattr(message, _CHANNEL_ATTR, None)
        dm_channel_id = self._parse_optional_int(getattr(channel, _ID_ATTR, None))
        if dm_channel_id is None:
            return
        identifier = parse_entry_identifier(content.text) if content.modality is TurnModality.TEXT else None

        async def _deliver(session: Session) -> None:
            await self._deliver_message_input(session, message, content, sender, dm_channel_id)

        async def _reply(reply_text: str) -> None:
            if channel is not None:
                await channel.send(reply_text)

        async def _bind(person_slug: str) -> BindOutcome:
            return self._bind_discord_invite(message, sender.user_id, person_slug)

        await handle_conversation_turn(
            ConversationTurn(
                conversation=ConversationRef(
                    origin=InputOrigin.DISCORD,
                    key_field=DISCORD_DM_KEY_FIELD,
                    key=str(dm_channel_id),
                    reaches_every_computer=True,
                    carries_desk_entry=False,
                ),
                sender=sender.identity,
                text=content.text,
                gesture=EntryGesture.IDENTIFIER if identifier is not None else EntryGesture.NONE,
                identifier=identifier,
                creation=TurnCreation(
                    entry_point=SessionEntryPoint.DISCORD,
                    origin_metadata={
                        _USER_ID_FIELD: sender.user_id,
                        _DISCORD_USER_ID_FIELD: sender.user_id,
                        _PLATFORM_FIELD: InputOrigin.DISCORD.value,
                        DiscordMetadataField.CHANNEL_ID.value: dm_channel_id,
                    },
                    command_input_mode=CommandInputMode.INTERACTIVE_SHORTHAND,
                ),
                deliver=_deliver,
                reply=_reply,
                bind_invite=_bind,
                modality=content.modality,
            )
        )

    async def _handle_team_channel_message(
        self, message: object, channel_id: int, person_slug: str, *, recovered_at: datetime | None = None
    ) -> None:
        """Hand one message of a provisioned Team assistant channel to the conversation seam.

        Provisioning designates the channel for ``person_slug``; the core admits the message only from
        that person and decides, with every other computer receiving it, which one answers. The message is
        concluded once its voice attachments have been accepted or have failed. The channel is recovered after a
        restart, so a draining refusal is not answered to the sender: it propagates to the continuity.
        """
        sender = self._message_sender(message)
        if sender is None:
            return
        content = _read_message_input(message)
        if content.is_empty:
            return
        channel = getattr(message, _CHANNEL_ATTR, None)
        guild_id = self._parse_optional_int(getattr(getattr(message, _GUILD_ATTR, None), _ID_ATTR, None))
        origin_metadata: dict[str, object] = {  # guard: loose-dict - flat origin fields of a created session
            _USER_ID_FIELD: sender.user_id,
            _DISCORD_USER_ID_FIELD: sender.user_id,
            _PLATFORM_FIELD: InputOrigin.DISCORD.value,
            DiscordMetadataField.CHANNEL_ID.value: channel_id,
        }
        if guild_id is not None:
            origin_metadata[DiscordMetadataField.GUILD_ID.value] = guild_id

        transcriptions: list[asyncio.Task[object]] = []

        async def _deliver(session: Session) -> None:
            transcriptions.extend(
                await self._deliver_message_input(
                    session, message, content, sender, channel_id, recovered_at, retain_refusal=True
                )
            )

        async def _reply(reply_text: str) -> None:
            if channel is not None:
                await channel.send(reply_text)

        await handle_conversation_turn(
            ConversationTurn(
                conversation=team_channel_conversation(channel_id),
                sender=sender.identity,
                text=content.text,
                gesture=EntryGesture.NONE,
                creation=TurnCreation(
                    entry_point=SessionEntryPoint.DISCORD,
                    origin_metadata=origin_metadata,
                    command_input_mode=CommandInputMode.INTERACTIVE_SHORTHAND,
                ),
                deliver=_deliver,
                reply=_reply,
                bind_invite=_invitations_not_carried,
                modality=content.modality,
                designated_person=person_slug,
            )
        )
        await await_conclusion(transcriptions)

    def _bind_discord_invite(self, message: object, user_id: str, person_slug: str) -> BindOutcome:
        """Bind the Discord account to the invited person, unless another account holds the invitation."""
        person_config = get_person_config(person_slug)
        bound = person_config.creds.discord.user_id if person_config.creds.discord else None
        if bound:
            return BindOutcome.ACCEPTED if bound == user_id else BindOutcome.CONFLICT
        avatar_url = self._discord_actor_avatar_url(getattr(message, _AUTHOR_ATTR, None))
        binding_id = str(getattr(message, _ID_ATTR, _NO_TEXT)).strip()
        observe_discord_avatar_binding(
            binding_id=binding_id,
            outcome=DiscordAvatarBindingOutcome.ACCEPTED,
            reason=DiscordAvatarBindingReason.UNBOUND_INVITE,
            avatar_present=avatar_url is not None,
        )
        bind_discord_credentials(person_slug, user_id, avatar_url=avatar_url, binding_id=binding_id)
        return BindOutcome.ACCEPTED
