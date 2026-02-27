"""Agent Coordinator - orchestrates agent events and cross-computer communication.

Handles agent lifecycle events (start, stop, notification) and routes them to:
1. Local listeners (via tmux injection)
2. Remote initiators (via Redis transport)
3. Human UI (via AdapterClient feedback)
"""

import asyncio
import base64
import inspect
import random
import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import TYPE_CHECKING, Coroutine, cast

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.constants import (
    CHECKPOINT_MESSAGE,
    CHECKPOINT_PREFIX,
    LOCAL_COMPUTER,
)
from teleclaude.core.activity_contract import serialize_activity_event
from teleclaude.core.agents import AgentName
from teleclaude.core.checkpoint_dispatch import inject_checkpoint_if_needed
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    AgentActivityEvent,
    AgentEventContext,
    AgentHookEvents,
    AgentNotificationPayload,
    AgentOutputPayload,
    AgentSessionEndPayload,
    AgentSessionStartPayload,
    AgentStopPayload,
    SessionStatusContext,
    TeleClaudeEvents,
    UserPromptSubmitPayload,
)
from teleclaude.core.feature_flags import is_threaded_output_enabled
from teleclaude.core.identity import get_identity_resolver
from teleclaude.core.models import MessageMetadata
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_listeners import (
    get_active_links_for_session,
    get_peer_members,
    notify_input_request,
    notify_stop,
)
from teleclaude.core.status_contract import (
    AWAITING_OUTPUT_THRESHOLD_SECONDS,
    STALL_THRESHOLD_SECONDS,
    serialize_status_event,
)
from teleclaude.core.summarizer import summarize_agent_output, summarize_user_input_title
from teleclaude.core.tool_activity import build_tool_preview, extract_tool_name
from teleclaude.services.headless_snapshot_service import HeadlessSnapshotService
from teleclaude.tts.manager import TTSManager
from teleclaude.types.commands import ProcessMessageCommand
from teleclaude.utils import strip_ansi_codes
from teleclaude.utils.transcript import (
    count_renderable_assistant_blocks,
    extract_last_agent_message,
    extract_last_user_message_with_timestamp,
    get_assistant_messages_since,
    render_agent_output,
    render_clean_agent_output,
)

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

logger = get_logger(__name__)

_PASTED_CONTENT_PLACEHOLDER_RE = re.compile(r"^\[Pasted Content \d+ chars\]$")
_NOOP_LOG_INTERVAL_SECONDS = 30.0
_MAX_FORWARDED_LINK_OUTPUT_CHARS = 12000

SESSION_START_MESSAGES = [
    "Standing by with grep patterns locked and loaded. What can I find?",
    "Warmed up and ready to hunt down that bug!",
    "Cache cleared, mind fresh. What's the task?",
    "All systems nominal, ready to ship some code!",
    "Initialized and ready to make those tests pass. What needs fixing?",
    "Compiled with optimism and ready to refactor!",
    "Ready to turn coffee into code. Where do we start?",
    "Standing by like a well-indexed database!",
    "Alert and ready to parse whatever you need. What's up?",
    "Primed to help you ship that feature!",
    "Spun up and ready to debug. What's broken?",
    "Loaded and eager to make things work!",
    "Ready to dig into the details. What should I investigate?",
    "All systems go for some serious coding!",
    "Prepared to tackle whatever you throw at me. What's the challenge?",
    "Standing by to help ship something awesome!",
    "Ready to make the build green. What needs attention?",
    "Warmed up and waiting to assist!",
    "Initialized and ready to solve problems. What's the issue?",
    "All set to help you build something great!",
]


@dataclass
class _SuppressionState:
    """Tracks repeated no-op events so logs can be sampled."""

    signature: str
    started_at: datetime
    last_log_at: datetime
    suppressed: int = 0


def _is_checkpoint_prompt(
    prompt: str,
    *,
    raw_payload: object = None,
) -> bool:
    """Return True when prompt text is our system checkpoint message.

    Matches both the generic Phase 1 message and context-aware Phase 2
    messages by checking known prefixes.  Codex synthetic input detection
    truncates captured prompt text, so we also accept 40-char prefixes of
    the generic constant for synthetic events.
    """
    prompt_clean = (prompt or "").strip()
    if not prompt_clean:
        return False

    # Canonical prefix match covers all checkpoint variants.
    if prompt_clean.startswith(CHECKPOINT_PREFIX):
        return True

    # Exact match for the generic constant (backward compat).
    checkpoint_clean = CHECKPOINT_MESSAGE.strip()
    if prompt_clean == checkpoint_clean:
        return True

    # Truncated Codex synthetic prompt (from output polling / fast-poll)
    is_codex_synthetic = False
    if isinstance(raw_payload, dict):
        source = raw_payload.get("source")
        is_codex_synthetic = (
            bool(raw_payload.get("synthetic")) and isinstance(source, str) and source.startswith("codex_")
        )

    if is_codex_synthetic and len(prompt_clean) >= 40 and checkpoint_clean.startswith(prompt_clean):
        return True

    return False


def _is_codex_synthetic_prompt_event(raw_payload: object) -> bool:
    """Return True for Codex synthetic prompt events derived from output polling."""
    if not isinstance(raw_payload, Mapping):
        return False
    source = raw_payload.get("source")
    return bool(raw_payload.get("synthetic")) and isinstance(source, str) and source.startswith("codex_")


def _has_active_output_message(session: "Session") -> bool:
    """Check if any adapter has an active output message in metadata."""
    meta = session.get_metadata().get_ui()
    return bool(
        meta.get_telegram().output_message_id
        or meta.get_discord().output_message_id
        or meta.get_whatsapp().output_message_id
    )


def _is_pasted_content_placeholder(prompt: str) -> bool:
    """Return True when prompt is a synthetic pasted-content placeholder."""
    return bool(_PASTED_CONTENT_PLACEHOLDER_RE.fullmatch((prompt or "").strip()))


def _coerce_nonempty_str(value: object) -> str | None:
    """Normalize value to a non-empty string when possible."""
    if value is None:
        return None
    text = value.strip() if isinstance(value, str) else str(value).strip()
    return text or None


def _resolve_hook_actor_name(session: "Session") -> str:
    """Resolve actor label for hook-reflected user input."""
    metadata = session.session_metadata if isinstance(session.session_metadata, Mapping) else {}
    for key in ("actor_name", "user_name", "display_name", "username", "name"):
        resolved = _coerce_nonempty_str(metadata.get(key))
        if resolved:
            return resolved

    ui_meta = session.get_metadata().get_ui()
    telegram_user_id = ui_meta.get_telegram().user_id
    discord_user_id = ui_meta.get_discord().user_id
    whatsapp_phone = _coerce_nonempty_str(ui_meta.get_whatsapp().phone_number)

    origin_hint = (session.last_input_origin or "").strip().lower()
    resolver = get_identity_resolver()

    def _resolve_identity_name(origin: str, channel_meta: Mapping[str, object]) -> str | None:
        identity = resolver.resolve(origin, channel_meta)
        if not identity:
            return None
        return _coerce_nonempty_str(identity.person_name)

    if origin_hint == InputOrigin.TELEGRAM.value and telegram_user_id is not None:
        telegram_meta: Mapping[str, object] = {
            "user_id": str(telegram_user_id),
            "telegram_user_id": str(telegram_user_id),
        }
        resolved = _resolve_identity_name(InputOrigin.TELEGRAM.value, telegram_meta)
        if resolved:
            return resolved

    if origin_hint == InputOrigin.DISCORD.value and discord_user_id:
        discord_meta: Mapping[str, object] = {
            "user_id": str(discord_user_id),
            "discord_user_id": str(discord_user_id),
        }
        resolved = _resolve_identity_name(InputOrigin.DISCORD.value, discord_meta)
        if resolved:
            return resolved

    if origin_hint == InputOrigin.WHATSAPP.value and whatsapp_phone:
        whatsapp_meta: dict[str, object] = {  # guard: loose-dict - Identity resolver channel metadata is dynamic.
            "phone_number": whatsapp_phone
        }
        resolved = _resolve_identity_name(InputOrigin.WHATSAPP.value, whatsapp_meta)
        if resolved:
            return resolved

    if telegram_user_id is not None:
        telegram_meta = {
            "user_id": str(telegram_user_id),
            "telegram_user_id": str(telegram_user_id),
        }
        resolved = _resolve_identity_name(InputOrigin.TELEGRAM.value, telegram_meta)
        if resolved:
            return resolved

    if discord_user_id:
        discord_meta = {
            "user_id": str(discord_user_id),
            "discord_user_id": str(discord_user_id),
        }
        resolved = _resolve_identity_name(InputOrigin.DISCORD.value, discord_meta)
        if resolved:
            return resolved

    if whatsapp_phone:
        whatsapp_meta = {"phone_number": whatsapp_phone}
        resolved = _resolve_identity_name(InputOrigin.WHATSAPP.value, whatsapp_meta)
        if resolved:
            return resolved

    human_email = _coerce_nonempty_str(session.human_email)
    if human_email:
        return human_email

    for key in ("actor_id", "user_id"):
        resolved = _coerce_nonempty_str(metadata.get(key))
        if resolved:
            return resolved

    if origin_hint == InputOrigin.TELEGRAM.value and telegram_user_id is not None:
        return f"telegram:{telegram_user_id}"
    if origin_hint == InputOrigin.DISCORD.value and discord_user_id:
        return f"discord:{discord_user_id}"
    if origin_hint == InputOrigin.WHATSAPP.value and whatsapp_phone:
        return f"whatsapp:{whatsapp_phone}"
    if telegram_user_id is not None:
        return f"telegram:{telegram_user_id}"
    if discord_user_id:
        return f"discord:{discord_user_id}"
    if whatsapp_phone:
        return f"whatsapp:{whatsapp_phone}"

    return "operator"


def _to_utc(ts: datetime) -> datetime:
    """Normalize naive datetimes to UTC for stable comparisons."""
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _is_codex_input_already_recorded(
    session: "Session | None",
    prompt_text: str,
) -> bool:
    """Return True when session state already reflects this Codex prompt turn."""
    if not session:
        return False

    existing_prompt = (session.last_message_sent or "").strip()
    candidate_prompt = (prompt_text or "").strip()
    if not existing_prompt or not candidate_prompt:
        return False
    prompts_match = (
        existing_prompt == candidate_prompt
        or existing_prompt.startswith(candidate_prompt)
        or candidate_prompt.startswith(existing_prompt)
    )
    if not prompts_match:
        return False
    if not isinstance(session.last_message_sent_at, datetime):
        return False

    message_at = _to_utc(session.last_message_sent_at)
    if not isinstance(session.last_output_at, datetime):
        return True
    feedback_at = _to_utc(session.last_output_at)
    return message_at > feedback_at


class AgentCoordinator:
    """Coordinator for agent events and inter-agent communication."""

    def __init__(
        self,
        client: "AdapterClient",
        tts_manager: TTSManager,
        headless_snapshot_service: HeadlessSnapshotService,
    ) -> None:
        self.client = client
        self.tts_manager = tts_manager
        self.headless_snapshot_service = headless_snapshot_service
        self._background_tasks: set[asyncio.Task[object]] = set()
        self._incremental_noop_state: dict[str, _SuppressionState] = {}
        self._tool_use_skip_state: dict[str, _SuppressionState] = {}
        self._incremental_eval_state: dict[str, tuple[str, bool]] = {}
        # Upstream render bookkeeping for incremental threaded output.
        # Stores digest of the full rendered message (not adapter chunk digests).
        self._incremental_render_digests: dict[str, str] = {}
        # Serialize incremental rendering/sending per session to avoid
        # concurrent poll/hook races emitting the same payload twice.
        self._incremental_output_locks: dict[str, asyncio.Lock] = {}
        # Stall detection: one pending task per session, cancelled on output arrival (R4)
        self._stall_tasks: dict[str, asyncio.Task[object]] = {}

    def _queue_background_task(
        self,
        coro: Coroutine[object, object, object],
        label: str,
    ) -> None:
        """Run non-critical work without blocking hook event handling."""
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)

        def _on_done(done: asyncio.Task[object]) -> None:
            self._background_tasks.discard(done)
            try:
                done.result()
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001 - background task errors are logged and dropped
                logger.error("Background task '%s' failed: %s", label, exc, exc_info=True)

                # Emit error event for user-visible failures (title updates, TTS)
                # Other background failures are logged but don't require user notification
                if "title" in label.lower():
                    try:
                        event_bus.emit(
                            TeleClaudeEvents.ERROR,
                            {"message": f"Failed to update session title: {exc}", "severity": "warning"},
                        )
                    except Exception:  # noqa: BLE001 - don't cascade error event failures
                        pass

        task.add_done_callback(_on_done)

    def _suppression_signature(self, *parts: object) -> str:
        """Build a stable signature for no-op suppression contexts."""
        raw = "|".join("" if part is None else str(part) for part in parts)
        return sha256(raw.encode("utf-8")).hexdigest()

    def _mark_incremental_noop(self, session_id: str, *, reason: str, signature: str) -> None:
        """Record repeated incremental no-op events with sampled debug logging."""
        now = datetime.now(timezone.utc)
        state = self._incremental_noop_state.get(session_id)

        if state and state.signature == signature:
            state.suppressed += 1
            elapsed_s = int((now - state.started_at).total_seconds())
            if (now - state.last_log_at).total_seconds() >= _NOOP_LOG_INTERVAL_SECONDS:
                logger.debug(
                    "Incremental no-op persists for session %s (reason=%s, suppressed=%d, elapsed_s=%d)",
                    session_id[:8],
                    reason,
                    state.suppressed,
                    elapsed_s,
                )
                state.last_log_at = now
                state.suppressed = 0
            return

        self._incremental_noop_state[session_id] = _SuppressionState(
            signature=signature,
            started_at=now,
            last_log_at=now,
        )
        logger.debug("Incremental no-op entered for session %s (reason=%s)", session_id[:8], reason)

    def _clear_incremental_noop(self, session_id: str, *, outcome: str) -> None:
        """Emit a one-time resume log when exiting a no-op suppression window."""
        now = datetime.now(timezone.utc)
        state = self._incremental_noop_state.pop(session_id, None)
        if not state:
            return
        elapsed_s = int((now - state.started_at).total_seconds())
        logger.debug(
            "Incremental no-op cleared for session %s (outcome=%s, suppressed=%d, elapsed_s=%d)",
            session_id[:8],
            outcome,
            state.suppressed,
            elapsed_s,
        )

    def _mark_tool_use_skip(self, session_id: str) -> None:
        """Collapse repeated tool_use skip logs for the same session."""
        now = datetime.now(timezone.utc)
        state = self._tool_use_skip_state.get(session_id)
        signature = "tool_use_already_set"

        if state and state.signature == signature:
            state.suppressed += 1
            elapsed_s = int((now - state.started_at).total_seconds())
            if (now - state.last_log_at).total_seconds() >= _NOOP_LOG_INTERVAL_SECONDS:
                logger.debug(
                    "tool_use DB write still skipped for session %s (suppressed=%d, elapsed_s=%d)",
                    session_id[:8],
                    state.suppressed,
                    elapsed_s,
                )
                state.last_log_at = now
                state.suppressed = 0
            return

        self._tool_use_skip_state[session_id] = _SuppressionState(
            signature=signature,
            started_at=now,
            last_log_at=now,
        )
        logger.debug("tool_use DB write skipped (already set) for session %s", session_id[:8])

    def _clear_tool_use_skip(self, session_id: str) -> None:
        """Clear tool_use skip suppression when a new turn starts recording again."""
        now = datetime.now(timezone.utc)
        state = self._tool_use_skip_state.pop(session_id, None)
        if not state or state.suppressed <= 0:
            return
        elapsed_s = int((now - state.started_at).total_seconds())
        logger.debug(
            "tool_use skip suppression cleared for session %s (suppressed=%d, elapsed_s=%d)",
            session_id[:8],
            state.suppressed,
            elapsed_s,
        )

    def _emit_activity_event(
        self,
        session_id: str,
        event_type: str,
        tool_name: str | None = None,
        tool_preview: str | None = None,
        summary: str | None = None,
        message: str | None = None,
    ) -> None:
        """Emit agent activity event with error handling.

        Routes through the canonical contract (activity_contract.py) to produce
        canonical_type and routing metadata alongside the hook-level event_type.
        The hook event_type is always preserved for consumer compatibility.

        Args:
            session_id: Session identifier
            event_type: AgentHookEventType value
            tool_name: Optional tool name for tool_use events
            tool_preview: Optional UI preview text for tool_use events
            summary: Optional output summary (agent_stop only)
            message: Optional notification message (notification only)
        """
        try:
            timestamp = datetime.now(timezone.utc).isoformat()
            canonical = serialize_activity_event(
                session_id=session_id,
                hook_event_type=event_type,
                timestamp=timestamp,
                tool_name=tool_name,
                tool_preview=tool_preview,
                summary=summary,
                message=message,
            )
            event_bus.emit(
                TeleClaudeEvents.AGENT_ACTIVITY,
                AgentActivityEvent(
                    session_id=session_id,
                    event_type=event_type,
                    tool_name=tool_name,
                    tool_preview=tool_preview,
                    summary=summary,
                    message=message,
                    timestamp=timestamp,
                    canonical_type=canonical.canonical_type if canonical else None,
                    message_intent=canonical.message_intent if canonical else None,
                    delivery_scope=canonical.delivery_scope if canonical else None,
                ),
            )
        except Exception as exc:
            logger.error(
                "Failed to emit activity event: %s",
                exc,
                exc_info=True,
                extra={"session_id": session_id[:8], "event_type": event_type},
            )

    def _emit_status_event(
        self,
        session_id: str,
        status: str,
        reason: str,
        *,
        last_activity_at: str | None = None,
    ) -> None:
        """Emit a canonical lifecycle status transition event.

        Routes through status_contract.serialize_status_event() for validation.
        Failures are logged but never crash the event flow (parallel to _emit_activity_event).

        Args:
            session_id: Session identifier.
            status: Target lifecycle status (must be a valid LifecycleStatus value).
            reason: Reason code for this transition.
            last_activity_at: ISO 8601 UTC timestamp of last known activity (optional).
        """
        try:
            timestamp = datetime.now(timezone.utc).isoformat()
            canonical = serialize_status_event(
                session_id=session_id,
                status=status,
                reason=reason,
                timestamp=timestamp,
                last_activity_at=last_activity_at,
            )
            if canonical is None:
                return
            event_bus.emit(
                TeleClaudeEvents.SESSION_STATUS,
                SessionStatusContext(
                    session_id=session_id,
                    status=status,
                    reason=reason,
                    timestamp=timestamp,
                    last_activity_at=last_activity_at,
                    message_intent=canonical.message_intent,
                    delivery_scope=canonical.delivery_scope,
                ),
            )
            logger.debug(
                "status transition: session=%s %s (reason=%s)",
                session_id[:8],
                status,
                reason,
            )
        except Exception as exc:
            logger.error(
                "Failed to emit status event: %s",
                exc,
                exc_info=True,
                extra={"session_id": session_id[:8], "status": status},
            )

    def _cancel_stall_task(self, session_id: str) -> None:
        """Cancel any pending stall detection task for a session."""
        task = self._stall_tasks.pop(session_id, None)
        if task and not task.done():
            task.cancel()

    def _schedule_stall_detection(self, session_id: str, last_activity_at: str) -> None:
        """Schedule background stall detection after user_prompt_submit (R4).

        Sequence:
          t=0                    → accepted emitted (caller)
          t=AWAITING_THRESHOLD   → awaiting_output
          t=STALL_THRESHOLD      → stalled
        Cancelled automatically when output arrives (tool_use or agent_stop).
        """
        self._cancel_stall_task(session_id)

        async def _stall_watcher() -> None:
            try:
                await asyncio.sleep(AWAITING_OUTPUT_THRESHOLD_SECONDS)
                self._emit_status_event(
                    session_id,
                    "awaiting_output",
                    "awaiting_output_timeout",
                    last_activity_at=last_activity_at,
                )
                await asyncio.sleep(STALL_THRESHOLD_SECONDS - AWAITING_OUTPUT_THRESHOLD_SECONDS)
                self._emit_status_event(
                    session_id,
                    "stalled",
                    "stall_timeout",
                    last_activity_at=last_activity_at,
                )
            except asyncio.CancelledError:
                pass  # Cancelled by output arrival — normal flow
            except Exception as exc:
                logger.error(
                    "Stall watcher failed for session %s: %s",
                    session_id[:8],
                    exc,
                    exc_info=True,
                )

        task = asyncio.create_task(_stall_watcher())
        self._stall_tasks[session_id] = task

    async def handle_event(self, context: AgentEventContext) -> None:
        """Handle any agent lifecycle event."""
        if context.event_type == AgentHookEvents.AGENT_SESSION_START:
            await self.handle_session_start(context)
        elif context.event_type == AgentHookEvents.AGENT_STOP:
            await self.handle_agent_stop(context)
        elif context.event_type == AgentHookEvents.TOOL_DONE:
            await self.handle_tool_done(context)
        elif context.event_type == AgentHookEvents.TOOL_USE:
            await self.handle_tool_use(context)
        elif context.event_type == AgentHookEvents.USER_PROMPT_SUBMIT:
            await self.handle_user_prompt_submit(context)
        elif context.event_type == AgentHookEvents.AGENT_NOTIFICATION:
            await self.handle_notification(context)
        elif context.event_type == AgentHookEvents.AGENT_SESSION_END:
            await self.handle_session_end(context)

    async def handle_session_start(self, context: AgentEventContext) -> None:
        """Handle session_start event - store native session details and update title if needed."""
        payload = cast(AgentSessionStartPayload, context.data)
        native_session_id = payload.session_id
        native_log_file = payload.transcript_path
        raw_cwd = payload.raw.get("cwd")

        update_kwargs: dict[str, object] = {}  # guard: loose-dict - Dynamic session updates
        if native_session_id:
            update_kwargs["native_session_id"] = str(native_session_id)
        if native_log_file:
            update_kwargs["native_log_file"] = str(native_log_file)

        if isinstance(raw_cwd, str) and raw_cwd:
            session = await db.get_session(context.session_id)
            if session and not session.project_path:
                update_kwargs["project_path"] = raw_cwd
                update_kwargs["subdir"] = None
        if update_kwargs:
            await db.update_session(context.session_id, **update_kwargs)

        voice = await db.get_voice(context.session_id)
        if voice:
            await db.assign_voice(context.session_id, voice)
            logger.debug(
                "Reaffirmed voice from service '%s' for teleclaude_session_id %s",
                voice.service_name,
                context.session_id[:8],
            )

        logger.info(
            "Stored Agent session data: teleclaude=%s, native=%s",
            context.session_id[:8],
            str(native_session_id)[:8],
        )

        await self._maybe_send_headless_snapshot(context.session_id)
        await self._speak_session_start()

    async def handle_user_prompt_submit(self, context: AgentEventContext) -> None:
        """Handle user prompt submission.

        For ALL sessions: write last_message_sent to DB (captures direct terminal input).
        If title is "Untitled", summarize user input and update title.
        For headless sessions: also route through process_message for tmux adoption.
        """
        session_id = context.session_id
        payload = cast(UserPromptSubmitPayload, context.data)

        session = await db.get_session(session_id)
        if not session:
            logger.warning("Session %s not found for user_prompt_submit", session_id[:8])
            return

        prompt_text = payload.prompt or ""
        if not prompt_text.strip():
            logger.debug("Empty prompt detected, skipping user input persistence for session %s", session_id[:8])
            return

        is_codex_synthetic = _is_codex_synthetic_prompt_event(payload.raw)
        # Guard against occasional single-character Codex polling artifacts (e.g. "r")
        # that would overwrite the real last input and cause misleading TUI state.
        if is_codex_synthetic and len(prompt_text.strip()) <= 1:
            logger.debug(
                "Ignoring tiny synthetic Codex prompt for session %s: %r",
                session_id[:8],
                prompt_text,
            )
            return

        # System-injected checkpoint — not real user input, skip entirely
        if _is_checkpoint_prompt(prompt_text, raw_payload=payload.raw):
            logger.debug("Checkpoint prompt detected, skipping user input persistence for session %s", session_id[:8])
            return

        # Clear notification flag when new prompt starts (all sessions)
        await db.set_notification_flag(session_id, False)

        # Clear checkpoint state on real user input
        await db.update_session(session_id, last_checkpoint_at=None, last_tool_use_at=None)
        self._incremental_render_digests.pop(session_id, None)

        # Prepare batched update
        now = datetime.now(timezone.utc)
        should_update_last_message = True
        if is_codex_synthetic:
            existing_input = (session.last_message_sent or "").strip()
            incoming_input = prompt_text.strip()
            existing_at = session.last_message_sent_at
            recent_existing = isinstance(existing_at, datetime) and (now - existing_at).total_seconds() <= 300
            if (
                recent_existing
                and existing_input
                and incoming_input
                and len(existing_input) > len(incoming_input)
                and existing_input.startswith(incoming_input)
            ):
                should_update_last_message = False
                logger.debug(
                    "Skipping synthetic Codex prompt overwrite for session %s (existing=%r incoming=%r)",
                    session_id[:8],
                    existing_input[:50],
                    incoming_input[:50],
                )

        incoming_input = prompt_text.strip()
        existing_input = (session.last_message_sent or "").strip()
        existing_origin = (session.last_input_origin or "").strip().lower()
        existing_at = session.last_message_sent_at
        is_recent_routed_echo = (
            session.lifecycle_status != "headless"
            and not is_codex_synthetic
            and existing_origin
            and existing_origin != InputOrigin.TERMINAL.value
            and isinstance(existing_at, datetime)
            and (now - existing_at).total_seconds() <= 20
            and existing_input
            and incoming_input
            and existing_input == incoming_input
        )
        if is_recent_routed_echo:
            should_update_last_message = False
            logger.debug(
                "Skipping duplicate hook prompt persistence for session %s (origin=%s)",
                session_id[:8],
                existing_origin,
            )

        update_kwargs: dict[str, object] = {}  # guard: loose-dict - Dynamic session updates
        if should_update_last_message:
            update_kwargs.update(
                {
                    "last_message_sent": prompt_text[:200],
                    "last_message_sent_at": now.isoformat(),
                    "last_input_origin": InputOrigin.TERMINAL.value,
                }
            )

        # Title update is non-critical and must not block hook ordering.
        if session.title == "Untitled" and not (is_codex_synthetic and _is_pasted_content_placeholder(prompt_text)):
            self._queue_background_task(
                self._update_session_title_async(session_id, prompt_text),
                f"title-summary:{session_id[:8]}",
            )

        # Single DB update for all fields
        await db.update_session(session_id, **update_kwargs)
        logger.debug(
            "Recorded user input via hook for session %s: %s...",
            session_id[:8],
            prompt_text[:50],
        )

        # Reset threaded output state on user input.
        # This seals the previous agent output block, ensuring the next response
        # starts a fresh message (append-only flow).
        if is_threaded_output_enabled(session.active_agent):
            await self.client.break_threaded_turn(session)

        # Emit activity event for UI updates.
        # Synthetic Codex prompts are still real input events.
        self._emit_activity_event(session_id, AgentHookEvents.USER_PROMPT_SUBMIT)

        # Emit canonical lifecycle status: accepted → schedule stall detection (R2, R4)
        now_ts = datetime.now(timezone.utc).isoformat()
        self._emit_status_event(session_id, "accepted", "user_prompt_accepted", last_activity_at=now_ts)
        self._schedule_stall_detection(session_id, last_activity_at=now_ts)

        hook_actor_name = _resolve_hook_actor_name(session)

        # Non-headless: DB write done above, no further routing needed
        # (the agent already received the input directly)
        if session.lifecycle_status != "headless":
            if is_recent_routed_echo:
                logger.debug(
                    "Skipping duplicate non-headless hook reflection for session %s",
                    session_id[:8],
                )
                return
            broadcast_result = self.client.broadcast_user_input(
                session,
                prompt_text,
                InputOrigin.TERMINAL.value,
                actor_id=f"terminal:{config.computer.name}:{session_id}",
                actor_name=hook_actor_name,
            )
            if inspect.isawaitable(broadcast_result):
                await broadcast_result
            return

        # Headless: route through unified process_message path
        # This handles tmux adoption and polling start
        from teleclaude.core.command_registry import get_command_service

        cmd = ProcessMessageCommand(
            session_id=session_id,
            text=prompt_text,
            origin=InputOrigin.TERMINAL.value,
            actor_id=f"terminal:{config.computer.name}:{session_id}",
            actor_name=hook_actor_name,
        )

        logger.debug(
            "Routing headless session %s through process_message for tmux adoption",
            session_id[:8],
        )

        await get_command_service().process_message(cmd)

    async def _update_session_title_async(self, session_id: str, prompt: str) -> None:
        """Best-effort asynchronous title update for untitled sessions."""
        if not prompt:
            return

        current = await db.get_session(session_id)
        if not current or current.title != "Untitled":
            return

        try:
            new_title = await summarize_user_input_title(prompt)
        except Exception as exc:  # noqa: BLE001 - title update should not break flow
            logger.warning("Title summarization failed: %s", exc)
            return

        if not new_title:
            return

        latest = await db.get_session(session_id)
        if not latest or latest.title != "Untitled":
            return

        await db.update_session(session_id, title=new_title)
        logger.info("Updated session title from user input: %s", new_title)

    async def handle_agent_stop(self, context: AgentEventContext) -> None:
        """Handle stop event - Agent session stopped."""
        session_id = context.session_id
        payload = cast(AgentStopPayload, context.data)
        source_computer = payload.source_computer

        # Fetch session early for logic checks
        session = await db.get_session(session_id)

        logger.debug(
            "Agent stop event for session %s (title: %s)",
            session_id[:8],
            "db",
        )

        # 1. Extract turn artifacts and persist with a single ordered activity update.
        input_update_kwargs: dict[str, object] = {}  # guard: loose-dict - Dynamic session updates
        feedback_update_kwargs: dict[str, object] = {}  # guard: loose-dict - Dynamic session updates
        emit_codex_submit_backfill = False
        recovered_input_text: str | None = None

        # For Codex: recover last user input from transcript (no native prompt hook).
        input_text = ""
        codex_input = await self._extract_user_input_for_codex(session_id, payload)
        if isinstance(codex_input, tuple) and len(codex_input) == 2:
            input_text, input_timestamp = codex_input
            input_update_kwargs.update(
                {
                    "last_message_sent": input_text[:200],
                }
            )
            if input_timestamp:
                input_update_kwargs["last_message_sent_at"] = input_timestamp.isoformat()
            if input_text.strip() and not _is_codex_input_already_recorded(session, input_text):
                emit_codex_submit_backfill = True
                recovered_input_text = input_text
        elif codex_input:
            logger.debug(
                "Ignoring malformed codex input tuple for session %s",
                session_id[:8],
            )

        if input_update_kwargs:
            await db.update_session(session_id, **input_update_kwargs)
        if emit_codex_submit_backfill:
            logger.info(
                "Backfilling missing user_prompt_submit from codex agent_stop for session %s",
                session_id[:8],
            )
            self._emit_activity_event(session_id, AgentHookEvents.USER_PROMPT_SUBMIT)
            # Safety net: when Codex prompt polling misses a live submit marker,
            # mirror the recovered user input to adapters so Discord/Telegram
            # still show the user turn.
            if session and session.lifecycle_status != "headless" and recovered_input_text:
                hook_actor_name = _resolve_hook_actor_name(session)
                await self.client.broadcast_user_input(
                    session,
                    recovered_input_text,
                    InputOrigin.TERMINAL.value,
                    actor_id=f"terminal:{config.computer.name}:{session_id}",
                    actor_name=hook_actor_name,
                )

        raw_output = await self._extract_agent_output(session_id, payload)
        forwarded_output_raw = payload.raw.get("linked_output")
        forwarded_output = forwarded_output_raw if isinstance(forwarded_output_raw, str) else None
        link_output = raw_output or forwarded_output
        if raw_output:
            if config.terminal.strip_ansi:
                raw_output = strip_ansi_codes(raw_output)
            if not raw_output.strip():
                logger.debug("Skip stop summary/TTS (agent output empty after normalization)", session=session_id[:8])
                raw_output = None
                link_output = None
            else:
                link_output = raw_output
        if payload.prompt and _is_checkpoint_prompt(payload.prompt, raw_payload=payload.raw):
            link_output = None

        summary: str | None = None
        if raw_output:
            summary = await self._summarize_output(session_id, raw_output)
            feedback_update_kwargs.update(
                {
                    "last_output_raw": raw_output,
                    "last_output_summary": summary,
                    "last_output_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            logger.debug(
                "Stored agent output: session=%s raw_len=%d summary_len=%d",
                session_id[:8],
                len(raw_output),
                len(summary) if summary else 0,
            )
            if summary:
                try:
                    await self.tts_manager.speak(summary)
                except Exception as exc:  # noqa: BLE001 - TTS should never crash event handling
                    logger.warning("TTS agent_stop failed: %s", exc, extra={"session_id": session_id[:8]})

        # Persist feedback and status to DB (activity events are emitted separately).
        if feedback_update_kwargs:
            await db.update_session(session_id, **feedback_update_kwargs)

        # Cancel stall detection — turn complete (R4)
        self._cancel_stall_task(session_id)

        # Emit activity event for UI updates (summary flows to TUI via event, not DB)
        self._emit_activity_event(session_id, AgentHookEvents.AGENT_STOP, summary=summary)

        # Emit canonical lifecycle status: completed (R2)
        now_ts = datetime.now(timezone.utc).isoformat()
        self._emit_status_event(session_id, "completed", "agent_turn_complete", last_activity_at=now_ts)

        # 2. Incremental threaded output (final turn portion)
        await self._maybe_send_incremental_output(session_id, payload)

        # Clear threaded output state for this turn (only for threaded sessions).
        # Non-threaded sessions rely on the poller's output_message_id for in-place edits.
        session = await db.get_session(session_id)  # Refresh to get latest metadata
        if session and is_threaded_output_enabled(session.active_agent):
            await self.client.break_threaded_turn(session)
            self._incremental_render_digests.pop(session_id, None)

        # Clear turn-specific cursor at turn completion
        await db.update_session(session_id, last_tool_done_at=None)

        # 3. Fan out distilled stop output across active direct/gathering links
        if link_output and link_output.strip():
            await self._fanout_linked_stop_output(session_id, link_output, source_computer=source_computer)

        # 4. Notify local listeners (worker orchestration mode)
        title_raw = payload.raw.get("title")
        title = title_raw if isinstance(title_raw, str) and title_raw else None
        await self._notify_session_listener(session_id, source_computer=source_computer, title_override=title)

        # 5. Forward to remote initiator (AI-to-AI across computers)
        if not (source_computer and source_computer != config.computer.name):
            await self._forward_stop_to_initiator(session_id, link_output)

        # 6. Inject checkpoint into the stopped agent's tmux pane
        await self._maybe_inject_checkpoint(session_id, session)

    async def handle_tool_use(self, context: AgentEventContext) -> None:
        """Handle tool_use event — agent started a tool call.

        Only records the FIRST tool_use per turn (when last_tool_use_at is NULL).
        This gives _maybe_inject_checkpoint the true turn start time, not the last tool call.
        Cleared by handle_user_prompt_submit when a new turn begins.
        """
        session_id = context.session_id
        payload = cast(AgentOutputPayload, context.data)

        tool_name = extract_tool_name(payload.raw)
        tool_preview = build_tool_preview(tool_name=tool_name, raw_payload=payload.raw)

        # Always emit activity event for UI updates (every tool call)
        self._emit_activity_event(
            session_id,
            AgentHookEvents.TOOL_USE,
            tool_name,
            tool_preview=tool_preview,
        )

        # Output evidence observed → active_output; cancel any pending stall (R4)
        self._cancel_stall_task(session_id)
        now_ts = datetime.now(timezone.utc).isoformat()
        self._emit_status_event(session_id, "active_output", "output_observed", last_activity_at=now_ts)

        # DB write is deduped: only record the FIRST tool_use per turn for checkpoint timing
        session = await db.get_session(session_id)
        if session and session.last_tool_use_at:
            self._mark_tool_use_skip(session_id)
        elif session:
            self._clear_tool_use_skip(session_id)
            now = datetime.now(timezone.utc)
            await db.update_session(session_id, last_tool_use_at=now.isoformat())
            logger.debug("tool_use recorded for session %s", session_id[:8])

        # Output fanout is transcript-driven from polling; hooks stay control-plane only.
        # tool_use still emits activity + checkpoint timing metadata.

    async def handle_tool_done(self, context: AgentEventContext) -> None:
        """Handle tool_done event — tool execution completed, output available."""
        session_id = context.session_id

        # Emit activity event for UI updates
        self._emit_activity_event(session_id, AgentHookEvents.TOOL_DONE)

    async def _maybe_send_incremental_output(
        self, session_id: str, payload: AgentStopPayload | AgentOutputPayload
    ) -> bool:
        """Evaluate and potentially send incremental threaded output summary.

        Returns:
            True if threaded message was sent, False otherwise.
        """
        lock = self._incremental_output_locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._incremental_output_locks[session_id] = lock

        async with lock:
            return await self._maybe_send_incremental_output_unlocked(session_id, payload)

    async def _maybe_send_incremental_output_unlocked(
        self, session_id: str, payload: AgentStopPayload | AgentOutputPayload
    ) -> bool:
        """Core incremental output path. Caller must hold session incremental lock."""
        session = await db.get_session(session_id)
        if not session:
            return False

        raw_agent_name = payload.raw.get("agent_name")
        payload_agent = raw_agent_name.strip().lower() if isinstance(raw_agent_name, str) else ""
        agent_key = payload_agent or session.active_agent
        if not agent_key:
            return False

        # Check if threaded output is enabled for this agent (any adapter).
        is_enabled = is_threaded_output_enabled(agent_key)
        eval_state = (agent_key, is_enabled)
        if self._incremental_eval_state.get(session_id) != eval_state:
            logger.debug(
                "Evaluating incremental output",
                session=session_id[:8],
                agent=agent_key,
                is_enabled=is_enabled,
            )
            self._incremental_eval_state[session_id] = eval_state

        if not is_enabled:
            self._mark_incremental_noop(
                session_id,
                reason="threaded_output_disabled",
                signature=self._suppression_signature("disabled", agent_key),
            )
            return False

        transcript_path = payload.transcript_path or session.native_log_file
        if not transcript_path:
            self._mark_incremental_noop(
                session_id,
                reason="missing_transcript_path",
                signature=self._suppression_signature("missing_transcript", agent_key, session.native_log_file),
            )
            return False

        try:
            agent_name = AgentName.from_str(agent_key)
        except ValueError:
            return False

        # Tools are always included in threaded mode
        include_tools = is_threaded_output_enabled(agent_key)

        turn_cursor = session.last_tool_done_at

        # Force a turn break if a new user message is detected in the transcript.
        # This handles races where the agent starts outputting before the
        # user_prompt_submit hook has been processed.
        if _has_active_output_message(session):
            user_msg = extract_last_user_message_with_timestamp(transcript_path, agent_name)
            if user_msg:
                _, user_ts = user_msg
                # If user message is newer than our last rendered assistant block, break the block.
                if user_ts and (turn_cursor is None or user_ts > turn_cursor):
                    logger.info("New turn detected in transcript; forcing fresh message block for %s", session_id[:8])
                    await self.client.break_threaded_turn(session)
                    self._incremental_render_digests.pop(session_id, None)
                    # Anchor this turn to the user message timestamp so repeated
                    # poll ticks don't keep re-breaking and replaying chunks.
                    await db.update_session(session_id, last_tool_done_at=user_ts.isoformat())
                    turn_cursor = user_ts
                    # Refresh session to reflect cleared state
                    session = await db.get_session(session_id)
                    if not session:
                        return False

        # 1. Retrieve all assistant messages since the current turn cursor
        assistant_messages = get_assistant_messages_since(transcript_path, agent_name, since_timestamp=turn_cursor)

        # Decide between clean (single-block) and standard (multi-block) rendering
        # using the number of renderable blocks, not message objects. Gemini often
        # emits multiple events (thinking/tool/text) inside a single assistant message.
        renderable_block_count = count_renderable_assistant_blocks(
            transcript_path,
            agent_name,
            since_timestamp=turn_cursor,
            include_tools=include_tools,
            include_tool_results=False,
        )

        analysis_signature = self._suppression_signature(
            "analysis",
            agent_key,
            transcript_path,
            len(assistant_messages),
            renderable_block_count,
            turn_cursor.isoformat() if turn_cursor else None,
        )

        if not assistant_messages:
            self._mark_incremental_noop(
                session_id,
                reason="no_assistant_messages",
                signature=analysis_signature,
            )
            return False

        self._clear_incremental_noop(session_id, outcome="assistant_messages_detected")
        logger.debug(
            "Incremental output analysis: session=%s msg_count=%d block_count=%d",
            session_id[:8],
            len(assistant_messages),
            renderable_block_count,
        )

        # 2. Decide which renderer to use based on renderable block count
        is_multi = renderable_block_count > 1

        if is_multi:
            # Multi-message: use standard renderer (with headers) for bulk update.
            # Suppression of tool results is handled inside the renderer for UI.
            # No truncation; adapter handles pagination/splitting.
            message, last_ts = render_agent_output(
                transcript_path,
                agent_name,
                include_tools=include_tools,
                include_tool_results=False,
                since_timestamp=turn_cursor,
                include_timestamps=False,
            )
        else:
            # Single message: use clean, metadata-free renderer (italics/bold-monospace).
            message, last_ts = render_clean_agent_output(transcript_path, agent_name, since_timestamp=turn_cursor)

        if not message:
            # Activity detected but no renderable text (e.g. empty thinking blocks or hidden tool output).
            self._mark_incremental_noop(
                session_id,
                reason="no_renderable_message",
                signature=self._suppression_signature("no_render", analysis_signature),
            )
            return False

        try:
            # Pass raw Markdown to adapter. The adapter handles platform-specific
            # conversion (e.g. Telegram MarkdownV2 escaping) internally.
            formatted_message = message

            # Skip if content unchanged since last send.
            display_digest = sha256(formatted_message.encode("utf-8")).hexdigest()
            if self._incremental_render_digests.get(session_id) == display_digest:
                self._mark_incremental_noop(
                    session_id,
                    reason="unchanged_render_digest",
                    signature=self._suppression_signature("digest", display_digest, is_multi),
                )
                return False

            self._clear_incremental_noop(session_id, outcome="output_changed")
            logger.info(
                "Sending incremental output: tc_session=%s len=%d multi_message=%s",
                session_id[:8],
                len(message),
                is_multi,
            )
            await self.client.send_threaded_output(session, formatted_message, multi_message=is_multi)
            self._incremental_render_digests[session_id] = display_digest

            # CRITICAL: Update cursor ONLY if we are NOT tracking this message for future updates.
            # If we are tracking (is_threaded_active), we want to re-render from the start of the turn
            # each time (accumulating content), so we do NOT update the cursor.
            # NOTE: We fetch fresh session/metadata to check adapter output_message_id
            fresh_session = await db.get_session(session_id)
            is_threaded_active = fresh_session is not None and _has_active_output_message(fresh_session)
            should_update_cursor = not is_threaded_active

            # Always update session to refresh last_activity (heartbeat),
            # but conditionally update the cursor.
            update_kwargs = {}
            if should_update_cursor and last_ts:
                from teleclaude.core.models import SessionField

                update_kwargs[SessionField.LAST_TOOL_DONE_AT.value] = last_ts.isoformat()
                logger.debug("Updating cursor for session %s to %s", session_id[:8], last_ts.isoformat())

            # Persist cursor timestamp (activity events are emitted separately).
            if update_kwargs:
                await db.update_session(session_id, **update_kwargs)

            return True
        except Exception as exc:  # noqa: BLE001 - Message send should never crash event handling
            logger.warning("Failed to send incremental output: %s", exc, extra={"session_id": session_id[:8]})

        return False

    async def trigger_incremental_output(self, session_id: str) -> bool:
        """Trigger incremental threaded output refresh for a session."""
        session = await db.get_session(session_id)
        if not session:
            return False

        if not is_threaded_output_enabled(session.active_agent):
            return False

        payload = AgentOutputPayload(session_id=session_id, transcript_path=session.native_log_file)
        return await self._maybe_send_incremental_output(session_id, payload)

    async def handle_notification(self, context: AgentEventContext) -> None:
        """Handle notification event - input request."""
        session_id = context.session_id
        payload = cast(AgentNotificationPayload, context.data)
        message = payload.message
        source_computer = payload.source_computer

        # 1. Notify local listeners
        computer = source_computer or LOCAL_COMPUTER
        await notify_input_request(session_id, computer, str(message))

        # 2. Forward to remote initiator (skip if already forwarded from remote)
        if not source_computer:
            await self._forward_notification_to_initiator(session_id, str(message))

        # Update notification flag
        await db.set_notification_flag(session_id, True)

        # 3. Emit canonical activity event so Web/TUI consumers receive agent_notification
        self._emit_activity_event(session_id, AgentHookEvents.AGENT_NOTIFICATION, message=str(message))

    async def handle_session_end(self, context: AgentEventContext) -> None:
        """Handle session_end event - agent session ended."""
        _payload = cast(AgentSessionEndPayload, context.data)
        logger.info("Agent %s for session %s", AgentHookEvents.AGENT_SESSION_END, context.session_id[:8])

    async def _maybe_send_headless_snapshot(self, session_id: str) -> None:
        session = await db.get_session(session_id)
        if not session or session.lifecycle_status != "headless":
            return
        if not session.active_agent or not session.native_log_file:
            logger.debug("Headless snapshot skipped (missing agent or transcript)", session=session_id[:8])
            return
        await self.headless_snapshot_service.send_snapshot(session, reason="agent_session_start", client=self.client)

    async def _speak_session_start(self) -> None:
        if not SESSION_START_MESSAGES:
            return
        message = random.choice(SESSION_START_MESSAGES)
        try:
            await self.tts_manager.speak(message)
        except Exception as exc:  # noqa: BLE001 - TTS should never crash event handling
            logger.warning("TTS session_start failed: %s", exc)

    async def _extract_agent_output(self, session_id: str, payload: AgentStopPayload) -> str | None:
        """Extract last agent output from transcript.

        Returns:
            Raw output text, or None if extraction fails or no output found.
        """
        session = await db.get_session(session_id)
        transcript_path = payload.transcript_path or (session.native_log_file if session else None)
        if not transcript_path:
            logger.debug("Extract skipped (missing transcript path)", session=session_id[:8])
            return None

        raw_agent_name = payload.raw.get("agent_name")
        agent_name_value = raw_agent_name if isinstance(raw_agent_name, str) and raw_agent_name else None
        if not agent_name_value and session and session.active_agent:
            agent_name_value = session.active_agent
        if not agent_name_value:
            logger.debug("Extract skipped (missing agent name)", session=session_id[:8])
            return None

        try:
            agent_name = AgentName.from_str(agent_name_value)
        except ValueError:
            logger.warning("Extract skipped (unknown agent '%s')", agent_name_value)
            return None

        last_message = extract_last_agent_message(transcript_path, agent_name, 1)
        if not last_message or not last_message.strip():
            logger.debug("Extract skipped (no agent output)", session=session_id[:8])
            return None

        return last_message

    async def _summarize_output(self, session_id: str, raw_output: str) -> str | None:
        """Summarize raw agent output via LLM.

        Returns:
            Summary text, or None if summarization fails.
        """
        if not raw_output.strip():
            logger.debug("Summarization skipped (empty normalized output)", session=session_id[:8])
            return None
        try:
            _title, summary = await summarize_agent_output(raw_output)
            return summary
        except Exception as exc:  # noqa: BLE001 - summarizer failures should not break stop handling
            logger.warning("Summarization failed: %s", exc, extra={"session_id": session_id[:8]})
            return None

    async def _extract_user_input_for_codex(
        self, session_id: str, payload: AgentStopPayload
    ) -> tuple[str, datetime | None] | None:
        """Extract last user input from transcript for Codex sessions.

        Codex doesn't have user_prompt_submit hook, so we extract user input
        from the transcript on agent stop as a fallback.
        """
        session = await db.get_session(session_id)
        if not session:
            return None

        # Only for Codex sessions
        agent_name_value = session.active_agent
        if agent_name_value != AgentName.CODEX.value:
            return None

        transcript_path = payload.transcript_path or session.native_log_file
        if not transcript_path:
            logger.debug("Codex user input extraction skipped (no transcript)", session=session_id[:8])
            return None

        try:
            agent_name = AgentName.from_str(agent_name_value)
        except ValueError:
            return None

        extracted = extract_last_user_message_with_timestamp(transcript_path, agent_name)
        if not extracted:
            logger.debug("Codex user input extraction skipped (no user message)", session=session_id[:8])
            return None
        last_user_input, input_timestamp = extracted

        # Don't persist our own checkpoint message as user input
        if _is_checkpoint_prompt(last_user_input):
            logger.debug("Codex user input skipped (checkpoint message) for session %s", session_id[:8])
            return None

        logger.debug(
            "Extracted Codex user input: session=%s input=%s...",
            session_id[:8],
            last_user_input[:50],
        )
        return last_user_input, input_timestamp

    async def _notify_session_listener(
        self,
        target_session_id: str,
        *,
        source_computer: str | None = None,
        title_override: str | None = None,
    ) -> None:
        """Notify local listeners via tmux injection."""
        target_session = await db.get_session(target_session_id)
        display_title = title_override or (target_session.title if target_session else "Unknown")
        computer = source_computer or LOCAL_COMPUTER
        await notify_stop(target_session_id, computer, title=display_title)

    async def _forward_stop_to_initiator(self, session_id: str, linked_output: str | None = None) -> None:
        """Forward stop event to remote initiator via Redis.

        Uses session.title from DB (stable, canonical) rather than
        freshly generated title from summarizer.
        """
        session = await db.get_session(session_id)
        if not session:
            return

        redis_meta = session.get_metadata().get_transport().get_redis()
        if not redis_meta.target_computer:
            return

        initiator_computer = redis_meta.target_computer
        if initiator_computer == config.computer.name:
            return

        # Use stable title from session record
        title_b64 = "-"
        if session.title:
            title_b64 = base64.b64encode(session.title.encode()).decode()
        output_arg = ""
        if linked_output and linked_output.strip():
            distilled = linked_output.strip()
            if len(distilled) > _MAX_FORWARDED_LINK_OUTPUT_CHARS:
                distilled = distilled[:_MAX_FORWARDED_LINK_OUTPUT_CHARS]
            output_b64 = base64.b64encode(distilled.encode()).decode()
            output_arg = f" {output_b64}"

        try:
            await self.client.send_request(
                computer_name=initiator_computer,
                command=f"/stop_notification {session_id} {config.computer.name} {title_b64}{output_arg}",
                metadata=MessageMetadata(),
            )
            logger.info("Forwarded stop to %s", initiator_computer)
        except Exception as e:
            logger.warning("Failed to forward stop to %s: %s", initiator_computer, e)

    async def _fanout_linked_stop_output(
        self,
        sender_session_id: str,
        distilled_output: str,
        *,
        source_computer: str | None = None,
    ) -> int:
        """Fan out distilled stop output to peers in active links, excluding sender."""
        links = await get_active_links_for_session(sender_session_id)
        if not links:
            return 0

        sender = await db.get_session(sender_session_id)
        sender_label = sender.title if sender and sender.title else sender_session_id
        sender_computer = source_computer or (sender.computer_name if sender else config.computer.name)
        framed_message = (
            f"[Linked output from {sender_label} ({sender_session_id}) on {sender_computer}]\n\n"
            f"{distilled_output.strip()}"
        )

        delivered = 0
        for link in links:
            peers = await get_peer_members(link_id=link.link_id, sender_session_id=sender_session_id)
            for peer in peers:
                target_computer = (
                    peer.computer_name
                    if peer.computer_name and peer.computer_name not in {LOCAL_COMPUTER, "local"}
                    else config.computer.name
                )
                actor_id = f"system:{sender_computer}:{sender_session_id}"
                actor_name = f"system@{sender_computer}"

                try:
                    if target_computer == config.computer.name:
                        cmd = ProcessMessageCommand(
                            session_id=peer.session_id,
                            text=framed_message,
                            origin=InputOrigin.REDIS.value,
                            actor_id=actor_id,
                            actor_name=actor_name,
                        )
                        await get_command_service().process_message(cmd)
                    else:
                        await self.client.send_request(
                            computer_name=target_computer,
                            command=f"message {shlex.quote(framed_message)}",
                            session_id=peer.session_id,
                            metadata=MessageMetadata(
                                origin=InputOrigin.REDIS.value,
                                channel_metadata={
                                    "actor_id": actor_id,
                                    "actor_name": actor_name,
                                    "actor_role": "system",
                                    "actor_agent": "system",
                                    "actor_computer": sender_computer,
                                },
                            ),
                        )
                    delivered += 1
                except Exception as exc:  # noqa: BLE001 - peer delivery failures must not abort stop lifecycle
                    logger.warning(
                        "Linked stop output delivery failed: sender=%s peer=%s target=%s error=%s",
                        sender_session_id[:8],
                        peer.session_id[:8],
                        target_computer,
                        exc,
                    )

        if delivered:
            logger.info(
                "Linked stop output fan-out: sender=%s delivered=%d",
                sender_session_id[:8],
                delivered,
            )
        return delivered

    async def _forward_notification_to_initiator(self, session_id: str, message: str) -> None:
        """Forward notification to remote initiator."""
        session = await db.get_session(session_id)
        if not session:
            return

        redis_meta = session.get_metadata().get_transport().get_redis()
        if not redis_meta.target_computer:
            return

        initiator_computer = redis_meta.target_computer
        if initiator_computer == config.computer.name:
            return

        message_b64 = base64.b64encode(message.encode()).decode()
        try:
            await self.client.send_request(
                computer_name=initiator_computer,
                command=f"/input_notification {session_id} {config.computer.name} {message_b64}",
                metadata=MessageMetadata(),
            )
        except Exception as e:
            logger.warning("Failed to forward notification to %s: %s", initiator_computer, e)

    async def _maybe_inject_checkpoint(self, session_id: str, session: "Session | None") -> None:
        """Conditionally inject a checkpoint message into the agent's tmux pane.

        Claude/Gemini: handled by hook output in receiver.py (invisible checkpoint).
        Codex: falls through to tmux injection below.
        """
        if not session:
            return

        try:
            await inject_checkpoint_if_needed(
                session_id,
                route="codex_tmux",
                include_elapsed_since_turn_start=True,
                default_agent=AgentName.CLAUDE,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Checkpoint injection failed for session %s: %s", session_id[:8], exc)
