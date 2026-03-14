"""Message operations mixin for Discord adapter.

Handles sending, editing, deleting messages, chunking, webhook reflections,
QoS scheduling, output limits, and peer discovery.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import AdapterError

if TYPE_CHECKING:
    from types import ModuleType

    from teleclaude.adapters.qos.output_scheduler import OutputQoSScheduler
    from teleclaude.core.models import MessageMetadata, PeerInfo, Session

logger = get_logger(__name__)


class MessageOperationsMixin:
    """Mixin providing message send/edit/delete and output operations for DiscordAdapter.

    Required host attributes:
    - max_message_size: int
    - _TRUNCATION_SUFFIX: str
    - _qos_scheduler: OutputQoSScheduler
    - _discord: ModuleType
    - ADAPTER_KEY: str
    - _reflection_webhook_cache: dict[int, object]
    - _resolve_destination_channel(session, metadata=None) -> object (async)
    - _is_thread_channel(channel) -> bool
    - _require_async_callable(fn, *, label) -> Callable
    - _fetch_destination_message(session, message_id, metadata=None) -> object (async)
    - format_output(tmux_output) -> str
    - _parse_optional_int(value) -> int | None
    """

    max_message_size: int
    _TRUNCATION_SUFFIX: str
    ADAPTER_KEY: str
    _reflection_webhook_cache: dict[int, object]

    if TYPE_CHECKING:
        _qos_scheduler: OutputQoSScheduler
        _discord: ModuleType

        def _is_thread_channel(self, channel: object) -> bool: ...

        @staticmethod
        def _require_async_callable(fn: object, *, label: str) -> Callable[..., Awaitable[object]]: ...

        def format_output(self, tmux_output: str) -> str: ...

        async def _resolve_destination_channel(
            self,
            session: Session,
            *,
            metadata: MessageMetadata | None = None,
        ) -> object: ...

        async def _fetch_destination_message(
            self,
            session: Session,
            message_id: str,
            *,
            metadata: MessageMetadata | None = None,
        ) -> object: ...

    # =========================================================================
    # Message Chunking
    # =========================================================================

    def _split_message_chunks(self, text: str) -> list[str]:
        """Split text into chunks that fit within Discord's message size limit.

        Splits on newline boundaries when possible, falling back to hard
        splits at max_message_size.
        """
        limit = self.max_message_size
        if len(text) <= limit:
            return [text]

        chunks: list[str] = []
        while text:
            if len(text) <= limit:
                chunks.append(text)
                break
            # Try to split at a newline within the limit
            split_at = text.rfind("\n", 0, limit)
            if split_at <= 0:
                split_at = limit
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip("\n")
        return chunks

    def drop_pending_output(self, session_id: str) -> int:
        """Drop pending QoS payloads for a session to prevent stale output after turn break."""
        return self._qos_scheduler.drop_pending(session_id)

    # =========================================================================
    # Send / Edit / Delete
    # =========================================================================

    async def send_message(
        self,
        session: Session,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
        multi_message: bool = False,
    ) -> str:
        # Reflection suppression: drop own-user reflections silently.
        if metadata is not None and metadata.reflection_origin == self.ADAPTER_KEY:
            logger.debug("send_message: suppressing own-user reflection for session %s", session.session_id)
            return "0"

        destination = await self._resolve_destination_channel(session, metadata=metadata)

        if multi_message and len(text) > self.max_message_size:
            chunks = self._split_message_chunks(text)
            logger.debug("[DISCORD SEND] multi_message: splitting %d chars into %d chunks", len(text), len(chunks))
            last_id = ""
            for chunk in chunks:
                last_id = await self._send_single_message(destination, chunk, metadata=metadata)
            return last_id

        text = self._fit_message_text(text, context="send_message")
        logger.debug("[DISCORD SEND] text=%r", text[:100])
        return await self._send_single_message(destination, text, metadata=metadata)

    async def _send_single_message(
        self,
        destination: object,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
    ) -> str:
        if metadata and metadata.reflection_actor_name:
            webhook_message_id = await self._send_reflection_via_webhook(destination, text, metadata)
            if webhook_message_id:
                return webhook_message_id

        send_fn = self._require_async_callable(getattr(destination, "send", None), label="Discord channel send")
        sent = await send_fn(text)
        message_id = getattr(sent, "id", None)
        if message_id is None:
            raise AdapterError("Discord send_message returned message without id")
        return str(message_id)

    async def _send_reflection_via_webhook(
        self,
        destination: object,
        text: str,
        metadata: MessageMetadata,
    ) -> str | None:
        actor_name = (metadata.reflection_actor_name or "").strip()
        if not actor_name:
            return None

        thread = destination if self._is_thread_channel(destination) else None
        webhook_channel = getattr(destination, "parent", None) if thread is not None else destination

        channel_id = self._parse_optional_int(getattr(webhook_channel, "id", None))
        if channel_id is None:
            return None

        webhook = await self._get_or_create_reflection_webhook(webhook_channel, channel_id)
        if webhook is None:
            return None

        send_fn = self._require_async_callable(getattr(webhook, "send", None), label="Discord webhook send")
        text = self._fit_message_text(text, context="reflection_webhook")
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
        except Exception as exc:
            logger.warning("Discord reflection webhook send failed: %s", exc)
            return None

        message_id = getattr(sent, "id", None)
        return str(message_id) if message_id is not None else None

    async def _get_or_create_reflection_webhook(self, channel: object, channel_id: int) -> object | None:
        cached = self._reflection_webhook_cache.get(channel_id)
        if cached is not None:
            return cached

        webhooks_fn = getattr(channel, "webhooks", None)
        if callable(webhooks_fn):
            try:
                webhooks = await self._require_async_callable(webhooks_fn, label="Discord channel webhooks")()
                if isinstance(webhooks, list):
                    for webhook in webhooks:
                        if getattr(webhook, "name", None) == "TeleClaude Reflections":
                            self._reflection_webhook_cache[channel_id] = webhook
                            return webhook  # type: ignore[no-any-return]
            except Exception as exc:
                logger.debug("Failed to list Discord webhooks for channel %s: %s", channel_id, exc)

        create_fn = getattr(channel, "create_webhook", None)
        if not callable(create_fn):
            return None
        try:
            webhook = await self._require_async_callable(create_fn, label="Discord channel create_webhook")(
                name="TeleClaude Reflections"
            )
            self._reflection_webhook_cache[channel_id] = webhook
            return webhook
        except Exception as exc:
            logger.warning("Failed to create Discord reflection webhook for channel %s: %s", channel_id, exc)
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

    async def edit_message(
        self,
        session: Session,
        message_id: str,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
    ) -> bool:
        text = self._fit_message_text(text, context="edit_message")
        logger.debug("[DISCORD EDIT] text=%r", text[:100])
        try:
            message = await self._fetch_destination_message(session, message_id, metadata=metadata)
        except AdapterError:
            return False
        edit_fn = self._require_async_callable(getattr(message, "edit", None), label="Discord message edit")
        try:
            await edit_fn(content=text)
            return True
        except Exception as exc:
            logger.warning("Failed to edit Discord message %s: %s", message_id, exc)
            return False

    async def delete_message(self, session: Session, message_id: str) -> bool:
        try:
            message = await self._fetch_destination_message(session, message_id)
        except AdapterError:
            return False
        delete_fn = self._require_async_callable(getattr(message, "delete", None), label="Discord message delete")
        try:
            await delete_fn()
            return True
        except Exception as exc:
            logger.warning("Failed to delete Discord message %s: %s", message_id, exc)
            return False

    async def send_file(
        self,
        session: Session,
        file_path: str,
        *,
        caption: str | None = None,
        metadata: MessageMetadata | None = None,
    ) -> str:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        destination = await self._resolve_destination_channel(session, metadata=metadata)
        send_fn = self._require_async_callable(getattr(destination, "send", None), label="Discord channel send")
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
            "Truncated Discord %s content from %d to %d characters",
            context,
            len(text),
            len(clipped),
        )
        return clipped

    def _build_metadata_for_thread(self) -> MessageMetadata:
        from teleclaude.core.models import MessageMetadata

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
        return self.max_message_size

    def get_ai_session_poll_interval(self) -> float:
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
        return []

    async def poll_output_stream(
        self,
        session: Session,
        timeout: float = 300.0,
    ) -> AsyncIterator[str]:
        _ = (session, timeout)
        raise NotImplementedError("Discord adapter does not support poll_output_stream")
        yield ""  # pragma: no cover
