"""Message operations mixin for Discord adapter.

Handles sending, editing, deleting messages, chunking, webhook reflections,
QoS scheduling, output limits, and peer discovery.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from types import ModuleType
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import AdapterError
from teleclaude.adapters.discord._runtime import AsyncDiscordCallable, cast_async_callable, recoverable_operation_errors
from teleclaude.core.db import db
from teleclaude.core.delivery import Destination
from teleclaude.core.models import MessageMetadata

if TYPE_CHECKING:
    from teleclaude.adapters.qos.output_scheduler import OutputQoSScheduler
    from teleclaude.core.models import PeerInfo, Session

logger = get_logger(__name__)

_OWN_REFLECTION_SUPPRESSED_EVENT = "discord_own_reflection_suppressed"
_SEND_EVENT = "discord_message_send"
_SEND_CHUNKED_EVENT = "discord_message_send_chunked"
_SENT_EVENT = "discord_message_sent"
_REFLECTION_WEBHOOK_SEND_FAILED_EVENT = "discord_reflection_webhook_send_failed"
_WEBHOOK_LIST_FAILED_EVENT = "discord_webhook_list_failed"
_REFLECTION_WEBHOOK_CREATE_FAILED_EVENT = "discord_reflection_webhook_create_failed"
_EDIT_EVENT = "discord_message_edit"
_EDITED_EVENT = "discord_message_edited"
_EDIT_FAILED_EVENT = "discord_message_edit_failed"
_WEBHOOK_EDIT_DESTINATION_FAILED_EVENT = "discord_webhook_edit_destination_failed"
_WEBHOOK_EDIT_NO_CHANNEL_EVENT = "discord_webhook_edit_no_channel_id"
_WEBHOOK_EDIT_UNAVAILABLE_EVENT = "discord_webhook_edit_webhook_unavailable"
_WEBHOOK_EDITED_EVENT = "discord_webhook_message_edited"
_WEBHOOK_EDIT_FAILED_EVENT = "discord_webhook_edit_failed"
_DELETE_DESTINATION_FAILED_EVENT = "discord_message_delete_destination_failed"
_DELETE_FAILED_EVENT = "discord_message_delete_failed"
_MESSAGE_TRUNCATED_EVENT = "discord_message_truncated"
_SEND_INTENT_RECONCILED_EVENT = "discord_send_intent_reconciled_omitted"


class MessageOperationsMixin:
    """Mixin providing message send/edit/delete and output operations for DiscordAdapter.

    Required host attributes:
    - max_message_size: int
    - _TRUNCATION_SUFFIX: str
    - _qos_scheduler: OutputQoSScheduler
    - _discord: ModuleType
    - ADAPTER_KEY: str
    - _reflection_webhook_cache: dict[int, object]
    - _resolve_destination_channel(destination) -> object (async)
    - _is_thread_channel(channel) -> bool
    - _require_async_callable(fn, *, label) -> Callable
    - _fetch_destination_message(destination, message_id) -> object (async)
    - format_output(tmux_output) -> str
    - _parse_optional_int(value) -> int | None
    """

    max_message_size: int
    _TRUNCATION_SUFFIX: str
    ADAPTER_KEY: str
    _reflection_webhook_cache: dict[int, object]
    _qos_scheduler: OutputQoSScheduler
    _discord: ModuleType
    format_output: Callable[[str], str]
    _resolve_destination_channel: Callable[..., Awaitable[object]]
    _fetch_destination_message: Callable[..., Awaitable[object]]

    if TYPE_CHECKING:

        @staticmethod
        def _is_thread_channel(channel: object) -> bool: ...

        @staticmethod
        def _require_async_callable(fn: object, *, label: str) -> AsyncDiscordCallable: ...

    # =========================================================================
    # Message Chunking
    # =========================================================================

    @staticmethod
    def _pack_complete_lines(text: str, limit: int) -> list[str]:
        """Pack complete newline-delimited lines into chunks up to *limit* chars."""
        if limit <= 0:
            raise ValueError("Discord message packing requires a positive limit")
        if len(text) <= limit:
            return [text]

        chunks: list[str] = []
        remaining = text
        while remaining:
            if len(remaining) <= limit:
                chunks.append(remaining)
                break
            split_at = remaining.rfind("\n", 0, limit + 1)
            separator_len = 1
            if split_at < 0:
                split_at = remaining.rfind(" ", 0, limit + 1)
            if split_at < 0:
                split_at = limit
                separator_len = 0
            if split_at == 0:
                remaining = remaining[1:]
                continue
            chunks.append(remaining[:split_at])
            remaining = remaining[split_at + separator_len :]
        return chunks

    def _split_message_chunks(self, text: str) -> list[str]:
        """Split text into chunks that fit within Discord's message size limit."""
        limit = self.max_message_size
        return self._pack_complete_lines(text, limit)

    # =========================================================================
    # Send / Edit / Delete
    # =========================================================================

    async def send_message(
        self,
        destination: Destination,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
        multi_message: bool = False,
    ) -> str:
        """Send Discord text, optionally chunking oversized multi-part payloads."""
        channel = await self._resolve_destination_channel(destination)
        logger.debug(
            _SEND_EVENT,
            session_id=destination.session_id,
            destination=type(channel).__name__,
            text_len=len(text),
            multi_message=multi_message,
        )

        if multi_message and len(text) > self.max_message_size:
            chunks = self._split_message_chunks(text)
            logger.debug(
                _SEND_CHUNKED_EVENT,
                session_id=destination.session_id,
                text_len=len(text),
                chunk_count=len(chunks),
            )
            last_id = ""
            for chunk in chunks:
                last_id = await self._send_single_message(
                    channel, chunk, session_id=destination.session_id, metadata=metadata
                )
            return last_id

        text = self._fit_message_text(text, context="send_message")
        return await self._send_single_message(channel, text, session_id=destination.session_id, metadata=metadata)

    async def _send_single_message(
        self,
        channel: object,
        text: str,
        *,
        session_id: str,
        metadata: MessageMetadata | None = None,
    ) -> str:
        if self._is_reflection_intended(metadata):
            return await self._send_reflection_via_webhook(channel, text, metadata, session_id=session_id)

        send_fn = cast_async_callable(
            self._require_async_callable,
            getattr(channel, "send", None),
            label="Discord channel send",
        )
        sent = await send_fn(text)
        message_id = getattr(sent, "id", None)
        if message_id is None:
            raise AdapterError("Discord send_message returned message without id")
        logger.debug(_SENT_EVENT, message_id=message_id, channel_id=getattr(channel, "id", None))
        return str(message_id)

    @staticmethod
    def _is_reflection_intended(metadata: MessageMetadata | None) -> bool:
        if metadata is None:
            return False
        return any(
            (
                metadata.reflection_origin,
                metadata.reflection_actor_id,
                metadata.reflection_actor_name,
                metadata.reflection_actor_avatar_url,
            )
        )

    async def _send_reflection_via_webhook(
        self,
        channel: object,
        text: str,
        metadata: MessageMetadata,
        *,
        session_id: str,
    ) -> str:
        """Create a webhook reflection message, tracked by a durable send intent.

        The intent is persisted BEFORE dispatch and resolved with the
        returned platform id AFTER a confirmed send (Task 4's contract): a
        crash between those two points leaves the intent pending, never
        resolved by guessing and never blind-resent — ``reconcile_pending_
        discord_send_intents`` closes it as omitted on the next startup.
        """
        actor_name = (metadata.reflection_actor_name or "").strip()
        if not actor_name:
            raise AdapterError("Discord reflection requires actor attribution")

        thread = channel if self._is_thread_channel(channel) else None
        webhook_channel = getattr(channel, "parent", None) if thread is not None else channel

        channel_id = self._parse_optional_int(getattr(webhook_channel, "id", None))
        if channel_id is None:
            raise AdapterError("Discord reflection destination has no channel id")

        webhook = await self._get_or_create_reflection_webhook(webhook_channel, channel_id)
        if webhook is None:
            raise AdapterError("Discord reflection webhook unavailable")

        send_fn = cast_async_callable(
            self._require_async_callable,
            getattr(webhook, "send", None),
            label="Discord webhook send",
        )
        text = self._fit_message_text(text, context="reflection_webhook")

        generation = await db.get_latest_output_generation(session_id)
        intent = (
            await db.create_discord_send_intent(
                intent_id=str(uuid.uuid4()),
                session_id=session_id,
                generation_id=generation.generation_id,
                channel_id=str(channel_id),
            )
            if generation is not None
            else None
        )

        recoverable_errors = recoverable_operation_errors(self._discord)
        try:
            if thread is not None and metadata.reflection_actor_avatar_url:
                sent = await send_fn(
                    content=text,
                    username=actor_name,
                    wait=True,
                    avatar_url=metadata.reflection_actor_avatar_url,
                    thread=thread,
                )
            elif thread is not None:
                sent = await send_fn(
                    content=text,
                    username=actor_name,
                    wait=True,
                    thread=thread,
                )
            elif metadata.reflection_actor_avatar_url:
                sent = await send_fn(
                    content=text,
                    username=actor_name,
                    wait=True,
                    avatar_url=metadata.reflection_actor_avatar_url,
                )
            else:
                sent = await send_fn(
                    content=text,
                    username=actor_name,
                    wait=True,
                )
        except recoverable_errors as exc:
            # Leave the intent pending on send failure: whether the create
            # actually landed server-side before this exception is unknown,
            # so neither resolving nor omitting it here would be honest.
            # Startup reconciliation settles it once, deliberately.
            logger.warning(_REFLECTION_WEBHOOK_SEND_FAILED_EVENT, error=str(exc))
            raise AdapterError("Discord reflection webhook send failed") from exc

        message_id = getattr(sent, "id", None)
        if message_id is None:
            raise AdapterError("Discord reflection webhook returned message without id")
        if intent is not None:
            await db.resolve_discord_send_intent(intent_id=intent.intent_id, platform_message_id=str(message_id))
        return str(message_id)

    async def _get_or_create_reflection_webhook(self, channel: object, channel_id: int) -> object | None:
        cached = self._reflection_webhook_cache.get(channel_id)
        if cached is not None:
            return cached

        recoverable_errors = recoverable_operation_errors(self._discord)
        webhooks_fn = getattr(channel, "webhooks", None)
        if callable(webhooks_fn):
            try:
                list_webhooks = cast_async_callable(
                    self._require_async_callable,
                    webhooks_fn,
                    label="Discord channel webhooks",
                )
                webhooks = await list_webhooks()
                if isinstance(webhooks, list):
                    for webhook in webhooks:
                        if getattr(webhook, "name", None) == "TeleClaude Reflections":
                            wh: object = webhook
                            self._reflection_webhook_cache[channel_id] = wh
                            return wh
            except recoverable_errors as exc:
                logger.debug(_WEBHOOK_LIST_FAILED_EVENT, channel_id=channel_id, error=str(exc))

        create_fn = getattr(channel, "create_webhook", None)
        if not callable(create_fn):
            return None
        try:
            create_webhook = cast_async_callable(
                self._require_async_callable,
                create_fn,
                label="Discord channel create_webhook",
            )
            webhook = await create_webhook(name="TeleClaude Reflections")
            self._reflection_webhook_cache[channel_id] = webhook
            return webhook
        except recoverable_errors as exc:
            logger.warning(_REFLECTION_WEBHOOK_CREATE_FAILED_EVENT, channel_id=channel_id, error=str(exc))
            return None

    @staticmethod
    def _discord_actor_name(author: object, user_id: str) -> str:
        display_name = getattr(author, "display_name", None)
        global_name = getattr(author, "global_name", None)
        username = getattr(author, "name", None)
        for candidate in (display_name, global_name, username):
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return f"discord:{user_id}"

    @staticmethod
    def _discord_actor_avatar_url(author: object) -> str | None:
        avatar = getattr(author, "display_avatar", None)
        avatar_url = getattr(avatar, "url", None) if avatar is not None else None
        if isinstance(avatar_url, str) and avatar_url.strip():
            return avatar_url
        return None

    @staticmethod
    def _is_unknown_discord_message_error(exc: Exception) -> bool:
        status = getattr(exc, "status", None)
        code = getattr(exc, "code", None)
        return isinstance(status, int) and isinstance(code, int) and status == 404 and code == 10008

    async def edit_message(
        self,
        destination: Destination,
        message_id: str,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
    ) -> bool:
        """Edit an existing Discord message if it can still be resolved.

        Dispatches to the same authoring surface the message was created
        through (Task 19): the bot's own ``message.edit`` cannot resolve or
        edit a webhook-authored message at all, so a streaming generation
        rendered under a reflected identity (``metadata`` carrying reflection
        fields — the same signal ``_is_reflection_intended`` already uses to
        route the initial send) must keep editing through the webhook,
        preserving its platform message id, alias, and avatar across edits.
        """
        text = self._fit_message_text(text, context="edit_message")
        logger.debug(
            _EDIT_EVENT,
            message_id=message_id,
            session_id=destination.session_id,
            text_len=len(text),
            via_webhook=self._is_reflection_intended(metadata),
        )
        if self._is_reflection_intended(metadata):
            return await self._edit_via_webhook(destination, message_id, text)

        recoverable_errors = recoverable_operation_errors(self._discord)
        try:
            message = await self._fetch_destination_message(destination, message_id)
        except AdapterError:
            return False
        except recoverable_errors as exc:
            if self._is_unknown_discord_message_error(exc):
                return False
            raise
        edit_fn = cast_async_callable(
            self._require_async_callable,
            getattr(message, "edit", None),
            label="Discord message edit",
        )
        try:
            await edit_fn(content=text)
            logger.debug(
                _EDITED_EVENT,
                message_id=message_id,
                session_id=destination.session_id,
                text_len=len(text),
            )
            return True
        except recoverable_errors as exc:
            logger.warning(
                _EDIT_FAILED_EVENT,
                message_id=message_id,
                session_id=destination.session_id,
                error=str(exc),
            )
            return False

    async def _edit_via_webhook(self, destination: Destination, message_id: str, text: str) -> bool:
        """Edit a webhook-authored message through the same reflection webhook that sent it."""
        recoverable_errors = recoverable_operation_errors(self._discord)
        try:
            channel = await self._resolve_destination_channel(destination)
        except AdapterError as exc:
            logger.warning(_WEBHOOK_EDIT_DESTINATION_FAILED_EVENT, message_id=message_id, error=str(exc))
            return False

        thread = channel if self._is_thread_channel(channel) else None
        webhook_channel = getattr(channel, "parent", None) if thread is not None else channel
        channel_id = self._parse_optional_int(getattr(webhook_channel, "id", None))
        if channel_id is None:
            logger.warning(_WEBHOOK_EDIT_NO_CHANNEL_EVENT, message_id=message_id)
            return False

        webhook = await self._get_or_create_reflection_webhook(webhook_channel, channel_id)
        if webhook is None:
            logger.warning(_WEBHOOK_EDIT_UNAVAILABLE_EVENT, message_id=message_id)
            return False

        edit_fn = cast_async_callable(
            self._require_async_callable,
            getattr(webhook, "edit_message", None),
            label="Discord webhook edit_message",
        )
        try:
            if thread is not None:
                await edit_fn(int(message_id), content=text, thread=thread)
            else:
                await edit_fn(int(message_id), content=text)
            logger.debug(
                _WEBHOOK_EDITED_EVENT,
                message_id=message_id,
                session_id=destination.session_id,
                text_len=len(text),
            )
            return True
        except recoverable_errors as exc:
            if self._is_unknown_discord_message_error(exc):
                return False
            logger.warning(
                _WEBHOOK_EDIT_FAILED_EVENT,
                message_id=message_id,
                session_id=destination.session_id,
                error=str(exc),
            )
            return False

    async def delete_message(self, destination: Destination, message_id: str) -> bool:
        """Delete a Discord message if it can still be resolved."""
        recoverable_errors = recoverable_operation_errors(self._discord)
        try:
            message = await self._fetch_destination_message(destination, message_id)
        except AdapterError as exc:
            logger.warning(_DELETE_DESTINATION_FAILED_EVENT, message_id=message_id, error=str(exc))
            return False
        except recoverable_errors as exc:
            if self._is_unknown_discord_message_error(exc):
                return True
            raise
        delete_fn = cast_async_callable(
            self._require_async_callable,
            getattr(message, "delete", None),
            label="Discord message delete",
        )
        try:
            await delete_fn()
            return True
        except recoverable_errors as exc:
            logger.warning(_DELETE_FAILED_EVENT, message_id=message_id, error=str(exc))
            return False

    async def send_file(
        self,
        destination: Destination,
        file_path: str,
        *,
        caption: str | None = None,
        metadata: MessageMetadata | None = None,
    ) -> str:
        """Upload a file to the resolved Discord destination channel."""
        _ = metadata
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        channel = await self._resolve_destination_channel(destination)
        send_fn = cast_async_callable(
            self._require_async_callable,
            getattr(channel, "send", None),
            label="Discord channel send",
        )
        discord_file = self._discord.File(file_path)
        safe_caption = self._fit_message_text(caption, context="send_file_caption") if caption else None
        sent = await send_fn(content=safe_caption, file=discord_file)
        message_id = getattr(sent, "id", None)
        if message_id is None:
            raise AdapterError("Discord send_file returned message without id")
        return str(message_id)

    # =========================================================================
    # Fit / Truncation Helpers
    # =========================================================================

    def _fit_message_text(self, text: str, *, context: str) -> str:
        """Clamp message text to Discord's hard message-size limit."""
        if len(text) <= self.max_message_size:
            return text

        suffix = self._TRUNCATION_SUFFIX
        reserve = max(self.max_message_size - len(suffix), 0)
        if reserve == 0:
            clipped = text[: self.max_message_size]
        else:
            clipped = f"{text[:reserve]}{suffix}"

        logger.debug(
            _MESSAGE_TRUNCATED_EVENT,
            context=context,
            original_len=len(text),
            truncated_len=len(clipped),
        )
        return clipped

    def _build_metadata_for_thread(self) -> MessageMetadata:
        """Build default metadata for Discord-originated thread messages."""
        return MessageMetadata(parse_mode=None)

    def _fit_output_to_limit(self, tmux_output: str) -> str:
        """Build output message within Discord's 2000-char limit.

        The base class truncates raw output to max_message_size, but format_output()
        wraps it in triple backticks (adding 8 chars). Account for that overhead.
        """
        formatted = self.format_output(tmux_output)
        if len(formatted) <= self.max_message_size:
            return formatted
        overhead = len("```\n\n```")
        max_body = self.max_message_size - overhead
        return self.format_output(tmux_output[-max_body:]) if max_body > 0 else ""

    def get_max_message_length(self) -> int:
        """Return Discord's effective maximum message length."""
        return self.max_message_size

    def get_ai_session_poll_interval(self) -> float:
        """Return the Discord adapter poll cadence used for AI session updates."""
        return 0.5

    @staticmethod
    def _parse_optional_int(value: object) -> int | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if text.isdigit():
            return int(text)
        return None

    # =========================================================================
    # Peer Discovery / Stream
    # =========================================================================

    async def discover_peers(self) -> list[PeerInfo]:
        """Return known Discord peers for adapters that support discovery."""
        return []

    async def poll_output_stream(
        self,
        session: Session,
        timeout: float = 300.0,
    ) -> AsyncIterator[str]:
        """Discord does not expose a pull-based output stream iterator."""
        _ = (session, timeout)
        if TYPE_CHECKING:
            yield ""
        raise NotImplementedError("Discord adapter does not support poll_output_stream")


async def reconcile_pending_discord_send_intents() -> int:
    """Close every Discord webhook send intent still pending at startup.

    A pending intent crossing a restart means the daemon cannot know whether
    its webhook create actually landed server-side before the crash — per
    the Task 4 contract, restart must never blind-resend it. With no live
    Discord lookup available to disambiguate, every survivor is closed
    'omitted': recorded as an inconclusive, not-delivered generation rather
    than resent, and the lane is released so the following generation
    delivers on it instead of wedging behind an unresolved intent forever.
    Returns the number of intents omitted.
    """
    omitted = 0
    for intent in await db.get_pending_discord_send_intents():
        if await db.omit_discord_send_intent(intent_id=intent.intent_id):
            omitted += 1
            logger.info(
                _SEND_INTENT_RECONCILED_EVENT,
                intent_id=intent.intent_id,
                session_id=intent.session_id,
                generation_id=intent.generation_id,
            )
    return omitted
