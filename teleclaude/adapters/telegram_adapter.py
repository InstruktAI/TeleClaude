"""Telegram adapter for TeleClaude."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Awaitable
from datetime import datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.task_registry import TaskRegistry

from telegram.constants import ChatAction

from teleclaude.adapters.qos.output_scheduler import OutputQoSScheduler
from teleclaude.adapters.qos.policy import telegram_policy
from teleclaude.config import config
from teleclaude.constants import TELEGRAM_MAX_MESSAGE_BYTES
from teleclaude.core.models import MessageMetadata, PeerInfo, Session, TelegramAdapterMetadata
from teleclaude.utils.markdown import (
    MARKDOWN_V2_INITIAL_STATE,
    MarkdownV2State,
    continuation_prefix_for_markdown_v2_state,
    escape_markdown_v2_preformatted,
    leading_balanced_markdown_v2_entity_span,
    scan_markdown_v2_state,
    telegramify_markdown,
    truncate_markdown_v2,
    truncate_markdown_v2_with_consumed,
)

from .editable_ui_adapter import EditableUiAdapter
from .telegram.input_handlers import InputHandlersMixin
from .telegram.lifecycle import LifecycleMixin, TelegramApp
from .telegram.message_ops import EditContext, MessageOperationsMixin
from .telegram.private_handlers import PrivateHandlersMixin
from .ui.threaded_output import OverflowContext
from .ui_adapter import UiAdapter

logger = get_logger(__name__)


class TelegramAdapter(
    PrivateHandlersMixin,
    LifecycleMixin,
    InputHandlersMixin,
    MessageOperationsMixin,
    EditableUiAdapter,
):
    """Telegram bot adapter using python-telegram-bot."""

    ADAPTER_KEY = "telegram"
    OUTPUT_MESSAGE_ID_FIELD = "message_id"
    supports_message_deletion = True

    # -------------------------------------------------------------------------
    # Markdown strategy — MarkdownV2
    # -------------------------------------------------------------------------

    def _markdown_initial_state(self) -> MarkdownV2State:
        return MARKDOWN_V2_INITIAL_STATE

    def _continuation_prefix_for_state(self, state: MarkdownV2State) -> str:
        return continuation_prefix_for_markdown_v2_state(state)

    def _truncate_for_overflow(self, body_text: str, max_chars: int) -> tuple[str, int]:
        return truncate_markdown_v2_with_consumed(body_text, max_chars=max_chars, suffix="")

    def _scan_markdown_state(self, consumed: str, state: MarkdownV2State) -> MarkdownV2State:
        return scan_markdown_v2_state(consumed, initial_state=state)

    def _finalize_overflow_split(
        self,
        active_text: str,
        overflow_context: OverflowContext,
        split_idx: int,
        chunk: str,
    ) -> tuple[int, str]:
        entity_scan_limit = min(self.THREADED_MARKDOWN_ATOMIC_ENTITY_MAX_CHARS, len(active_text))
        atomic_entity_threshold = min(
            self.THREADED_MARKDOWN_ATOMIC_ENTITY_MAX_CHARS,
            max(32, overflow_context.available_for_content // 2),
        )
        leading_entity_span = leading_balanced_markdown_v2_entity_span(
            active_text,
            max_scan_chars=entity_scan_limit,
        )
        if not 0 < leading_entity_span <= atomic_entity_threshold or split_idx >= leading_entity_span:
            return split_idx, chunk

        atomic_chunk, atomic_consumed_display = truncate_markdown_v2_with_consumed(
            f"{overflow_context.continuation_prefix}{active_text[:leading_entity_span]}",
            max_chars=overflow_context.available_for_content,
            suffix="",
        )
        atomic_consumed_prefix = min(atomic_consumed_display, len(overflow_context.continuation_prefix))
        atomic_split_idx = atomic_consumed_display - atomic_consumed_prefix
        if atomic_split_idx == leading_entity_span:
            return atomic_split_idx, atomic_chunk
        return split_idx, chunk

    def _balance_intermediate_chunk(self, text: str) -> str:
        balanced, _ = truncate_markdown_v2_with_consumed(text, max_chars=len(text), suffix="")
        return balanced

    # -------------------------------------------------------------------------

    def __init__(self, client: AdapterClient, *, task_registry: TaskRegistry | None = None) -> None:
        """Initialize Telegram adapter.

        Args:
            client: AdapterClient instance for event emission
        """
        super().__init__(client)

        # Store client for event emission (already set by parent, but keep for clarity)
        self.client = client
        self.task_registry = task_registry

        bot_token = config.telegram.bot_token
        if not bot_token:
            raise ValueError("telegram.bot_token is required in config.yml")
        self.bot_token: str = bot_token

        self.computer_name = config.computer.name
        if not self.computer_name:
            raise ValueError("computer.name is required in config.yml")
        self.is_master = config.computer.is_master
        self.app: TelegramApp | None = None
        self._processed_voice_messages: set[str] = set()  # Track processed voice message IDs with edit state
        self._pending_edits: dict[str, EditContext] = {}  # Track pending edits (message_id -> mutable context)
        self._last_edit_hash: dict[str, str] = {}  # message_id -> content hash (skip no-op edits)
        self._startup_housekeeping_task: asyncio.Task[None] | None = None

        # Output QoS scheduler: coalesces stale payloads and enforces pacing budget.
        qos_policy = telegram_policy(config.telegram.qos)
        self._qos_scheduler: OutputQoSScheduler = OutputQoSScheduler(qos_policy)

    # --- Per-adapter output message tracking ---
    # Telegram stores output tracking in origin_metadata to prevent cross-adapter races.

    @staticmethod
    def _tg(session: Session) -> TelegramAdapterMetadata:
        """Read Telegram section from origin_metadata."""
        return TelegramAdapterMetadata.from_dict(session.get_origin_section("telegram"))

    async def discover_peers(self) -> list[PeerInfo]:
        """Declare that Telegram has no remote peer-discovery surface."""
        return []

    async def poll_output_stream(
        self,
        session: Session,
        timeout: float = 300.0,
    ) -> AsyncIterator[str]:
        """Declare Telegram's unsupported remote output-stream operation."""
        _ = session, timeout
        raise NotImplementedError("Telegram adapter does not support poll_output_stream")
        yield ""

    async def send_typing_indicator(self, session: Session) -> None:
        """Send typing indicator to Telegram private chat."""
        user_id = session.origin_metadata.get("user_id") or session.origin_metadata.get("telegram_user_id")
        if not user_id:
            return
        await self.bot.send_chat_action(
            chat_id=int(str(user_id)),
            action=ChatAction.TYPING,
        )

    def format_output(self, tmux_output: str) -> str:
        """Format tmux output with Telegram MarkdownV2 escaping and line shortening."""
        if not tmux_output:
            return ""

        sanitized = escape_markdown_v2_preformatted(tmux_output)
        result = f"```\n{sanitized}\n```"

        # Shorten long separator lines (118 repeating chars → 47)
        lines = []
        for line in result.split("\n"):
            modified_line = re.sub(r"(.)\1{117}", lambda m: m.group(1) * 47, line)  # type: ignore[misc]
            lines.append(modified_line)
        return "\n".join(lines)

    def _convert_markdown_for_platform(self, text: str) -> str:
        """Convert markdown to Telegram MarkdownV2 format."""
        return telegramify_markdown(text)

    def _build_metadata_for_thread(self) -> MessageMetadata:
        """Build metadata for threaded content with MarkdownV2 parse mode."""
        return MessageMetadata(parse_mode="MarkdownV2")

    def _fit_output_to_limit(self, tmux_output: str) -> str:
        """Fit output within Telegram's 4096 byte limit with MarkdownV2 escaping."""
        display_output = self.format_output(tmux_output)
        if self._fits_budget(display_output, TELEGRAM_MAX_MESSAGE_BYTES):
            return display_output

        trimmed_output = tmux_output
        while trimmed_output and not self._fits_budget(display_output, TELEGRAM_MAX_MESSAGE_BYTES):
            overflow = len(display_output) - self.max_message_size
            drop = max(overflow, 32)
            trimmed_output = trimmed_output[drop:] if drop < len(trimmed_output) else ""
            display_output = self.format_output(trimmed_output)

        if not self._fits_budget(display_output, TELEGRAM_MAX_MESSAGE_BYTES):
            display_output = truncate_markdown_v2(display_output, self.max_message_size, "")
        return display_output

    # ==================== Output QoS Integration ====================

    async def send_threaded_output(  # type: ignore[override]
        self,
        session: Session,
        text: str,
        multi_message: bool = False,
        *,
        delivery_ts: datetime | None = None,
        generation_id: str | None = None,
        metadata: MessageMetadata | None = None,
    ) -> str | None:
        """Route Telegram threaded output through the QoS scheduler.

        Threaded output payloads are coalesced (latest-only) so that only the
        most recent accumulated text is dispatched per scheduler tick.
        """
        if self._qos_scheduler._policy.mode == "off":
            return await EditableUiAdapter.send_threaded_output(
                self,
                session,
                text,
                multi_message,
                delivery_ts=delivery_ts,
                generation_id=generation_id,
                metadata=metadata,
            )

        _self = self
        _session = session
        _text = text
        _multi = multi_message
        _delivery_ts = delivery_ts
        _generation_id = generation_id
        _metadata = metadata

        def _task_factory(_adapter: UiAdapter, lane_session: Session) -> Awaitable[object]:
            return EditableUiAdapter.send_threaded_output(
                _self,
                lane_session,
                _text,
                _multi,
                delivery_ts=_delivery_ts,
                generation_id=_generation_id,
                metadata=_metadata,
            )

        async def _dispatch() -> str | None:
            result = await _self.client._run_deferred_ui_lane(
                _session,
                _self.ADAPTER_KEY,
                _task_factory,
            )
            return str(result) if result is not None else None

        # Threaded output chunks are non-final (the coordinator handles completion separately).
        self._qos_scheduler.enqueue(session.session_id, _dispatch, is_final=False)
        return None  # Delivery is deferred.

    # ==================== Platform-Specific Parameters ====================

    def get_max_message_length(self) -> int:
        """Telegram's max message length is 4096 chars."""
        return 4096

    def get_ai_session_poll_interval(self) -> float:
        """Telegram AI sessions poll faster than human sessions.

        Returns:
            0.5 seconds for real-time AI communication.
        """
        return 0.5

    # ==================== Helper Methods ====================
