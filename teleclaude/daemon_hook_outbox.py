"""Hook outbox processing mixin for TeleClaudeDaemon."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Coroutine, Mapping, MutableMapping
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal, cast

from instrukt_ai_logging import get_logger
from pydantic import JsonValue

from teleclaude.caller_identity import is_operator_principal, local_caller_principal
from teleclaude.config.machine import config
from teleclaude.constants import HUMAN_ROLE_CUSTOMER, HeadlessBootstrapField
from teleclaude.core import polling_coordinator
from teleclaude.core.agent_status import AgentStatusIntegrityError
from teleclaude.core.agents import AgentName
from teleclaude.core.codex_transcript import is_codex_subagent_transcript
from teleclaude.core.command_handlers import SessionCreationRefused
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import HookOutboxRow, db
from teleclaude.core.events import (
    ALL_AGENT_HOOK_EVENTS,
    AgentEventContext,
    AgentHookEvents,
    build_agent_payload,
)
from teleclaude.core.hook_outbox_handlers import (
    handle_checkpoint_relay,
    handle_checkpoint_seen,
    handle_native_metadata_update,
    handle_native_session_refresh,
    optional_payload_str_value,
)
from teleclaude.core.hook_outbox_queue import HookOutboxQueueItem, HookOutboxSessionQueue
from teleclaude.core.identity import get_identity_resolver
from teleclaude.core.models import AgentDispatchMode, Session, SessionEntryPoint, SessionLaunchIntent, SessionLaunchKind
from teleclaude.core.models._adapter import TerminalOriginMetadata
from teleclaude.core.origins import InputOrigin
from teleclaude.core.runtime_events import publish_runtime_error, publish_session_source_change
from teleclaude.core.session_compaction import is_current_compaction_launch, session_compaction_owner
from teleclaude.core.session_utils import split_project_path_and_subdir
from teleclaude.core.shutdown_drain import ShutdownRefusal
from teleclaude.events.envelope import occurrence_id
from teleclaude.events.schemas.system import RuntimeSessionChange
from teleclaude.project_manifest_runtime import load_registered_entries
from teleclaude.runtime.environment import (
    runtime_run_mismatch,
    take_normalized_launch_context,
)
from teleclaude.types.commands import CreateSessionCommand

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.cache import DaemonCache

logger = get_logger(__name__)
_HOOK_OUTBOX_BATCH_FAILED_MESSAGE = "Hook outbox batch failed; retrying after the poll interval"
_HOOK_OUTBOX_ROW_FAILED_MESSAGE = "Hook outbox row processing failed; continuing with the next row"
_HEADLESS_BOOTSTRAP_AUTHORITY_ABSENT = "Ignoring headless session bootstrap without receiver authorization"
_RUNTIME_HOOK_RUN_MISMATCH_EVENT = "Ignoring hook event from a superseded launch"
# Headless hook events carry no mode; the launch intent requires one, and "med"
# is the platform's standard mode.
_HEADLESS_DEFAULT_THINKING_MODE = "med"

HOOK_OUTBOX_POLL_INTERVAL_S = config.hook_outbox.poll_interval_s
HOOK_OUTBOX_BATCH_SIZE = config.hook_outbox.batch_size
HOOK_OUTBOX_LOCK_TTL_S = config.hook_outbox.lock_ttl_s
HOOK_OUTBOX_BASE_BACKOFF_S = config.hook_outbox.base_backoff_s
HOOK_OUTBOX_MAX_BACKOFF_S = config.hook_outbox.max_backoff_s
HOOK_OUTBOX_SESSION_IDLE_TIMEOUT_S = config.hook_outbox.session_idle_timeout_s
HOOK_OUTBOX_SESSION_MAX_PENDING = config.hook_outbox.session_max_pending
HOOK_OUTBOX_SESSION_CRITICAL_RESERVE = config.hook_outbox.session_critical_reserve
HOOK_OUTBOX_SESSION_CLAIM_HIGH_WATERMARK = config.hook_outbox.session_claim_high_watermark
HOOK_OUTBOX_SESSION_CLAIM_LOW_WATERMARK = config.hook_outbox.session_claim_low_watermark
HOOK_OUTBOX_SUMMARY_INTERVAL_S = config.hook_outbox.summary_interval_s
HOOK_OUTBOX_BACKLOG_WARN_THRESHOLD = config.hook_outbox.backlog_warn_threshold
HOOK_OUTBOX_LAG_WARN_THRESHOLD_S = config.hook_outbox.lag_warn_threshold_s
HOOK_OUTBOX_WARN_LOG_INTERVAL_S = config.hook_outbox.warn_log_interval_s
HOOK_OUTBOX_MAX_LAG_SAMPLES = config.hook_outbox.max_lag_samples
HOOK_OUTBOX_STALENESS_TTL_S = config.hook_outbox.staleness_ttl_s

HOOK_EVENT_STALENESS_EXEMPT: frozenset[str] = frozenset(
    {
        AgentHookEvents.AGENT_SESSION_START,
        AgentHookEvents.USER_PROMPT_SUBMIT,
        AgentHookEvents.PRE_TOOL_USE,
        AgentHookEvents.POST_TOOL_USE,
        AgentHookEvents.AGENT_STOP,
        AgentHookEvents.AGENT_BLOCKED,
        AgentHookEvents.AGENT_IDLE,
        AgentHookEvents.AGENT_TURN_FAILED,
        AgentHookEvents.AGENT_ERROR,
        AgentHookEvents.CHECKPOINT_RELAY,
    }
)

HOOK_EVENT_CLASS_CRITICAL: frozenset[str] = frozenset(
    {
        AgentHookEvents.AGENT_SESSION_START,
        AgentHookEvents.USER_PROMPT_SUBMIT,
        AgentHookEvents.PRE_TOOL_USE,
        AgentHookEvents.POST_TOOL_USE,
        AgentHookEvents.AGENT_STOP,
        AgentHookEvents.AGENT_BLOCKED,
        AgentHookEvents.AGENT_IDLE,
        AgentHookEvents.AGENT_TURN_FAILED,
        AgentHookEvents.AGENT_ERROR,
        AgentHookEvents.CHECKPOINT_RELAY,
        AgentHookEvents.CHECKPOINT_SEEN,
        AgentHookEvents.NATIVE_METADATA_UPDATE,
        AgentHookEvents.NATIVE_SESSION_REFRESH,
    }
)
HOOK_EVENT_CLASS_BURSTY: frozenset[str] = frozenset()


class _DaemonHookOutboxMixin:  # pyright: ignore[reportUnusedClass]
    """Hook outbox processing methods extracted from TeleClaudeDaemon."""

    if TYPE_CHECKING:
        shutdown_event: asyncio.Event
        _background_tasks: set[asyncio.Task[object]]
        _session_outbox_queues: dict[str, HookOutboxSessionQueue]
        _session_outbox_workers: dict[str, asyncio.Task[None]]
        _hook_outbox_processed_count: int
        _hook_outbox_coalesced_count: int
        _hook_outbox_lag_samples_s: list[float]
        _hook_outbox_last_summary_at: float
        _hook_outbox_last_backlog_warn_at: dict[str, float]
        _hook_outbox_last_lag_warn_at: dict[str, float]
        _hook_outbox_claim_paused_sessions: set[str]
        _hook_outbox_stale_dropped_count: int
        cache: DaemonCache
        client: AdapterClient

        def _queue_background_task(self, coro: Coroutine[object, object, object], label: str) -> None: ...
        async def _handle_agent_event_direct(self, context: AgentEventContext) -> None: ...
        async def _ensure_output_polling(self, session: Session) -> None: ...

    async def _schedule_projection_from_signal(self, session_id: str, session: Session) -> None:
        """Schedule transcript projection from a hook-side activity signal."""
        if session.lifecycle_status == "closed":
            return
        if session.lifecycle_status == "headless":
            await polling_coordinator.schedule_session_projection(session_id, self.client, headless_only=True)
        else:
            await polling_coordinator.schedule_session_projection(session_id, self.client)

    def _log_background_task_exception(self, task_name: str) -> Callable[[asyncio.Task[object]], None]:
        """Return a done-callback that logs unexpected background task failures."""

        def _on_done(task: asyncio.Task[object]) -> None:
            try:
                task.result()
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error("Background task '%s' crashed: %s", task_name, e, exc_info=True)

        return _on_done

    def _track_background_task(self, task: asyncio.Task[object], label: str) -> None:
        """Track background tasks so failures are logged and tasks aren't lost."""
        self._background_tasks.add(task)

        def _on_done(done: asyncio.Task[object]) -> None:
            self._background_tasks.discard(done)
            try:
                done.result()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.error("Background task failed (%s): %s", label, exc, exc_info=True)

        task.add_done_callback(_on_done)

    @staticmethod
    def _is_stale_outbox_row(row: HookOutboxRow) -> bool:
        """Return True when a non-lifecycle row exceeds the staleness TTL."""
        event_type = str(row.get("event_type") or "")
        if event_type in HOOK_EVENT_STALENESS_EXEMPT:
            return False
        created_at_raw = row.get("created_at")
        if not isinstance(created_at_raw, str) or not created_at_raw:
            return False
        try:
            created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
        except ValueError:
            return False
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        age_s = (datetime.now(UTC) - created_at).total_seconds()
        return age_s > HOOK_OUTBOX_STALENESS_TTL_S

    @staticmethod
    def _classify_hook_event(event_type: str) -> Literal["critical", "bursty"]:
        """Classify hook events for queueing policy."""
        if event_type in HOOK_EVENT_CLASS_CRITICAL:
            return "critical"
        if event_type in HOOK_EVENT_CLASS_BURSTY:
            return "bursty"
        # Default non-critical events to bursty until promoted explicitly.
        return "bursty"

    @staticmethod
    def _percentile(samples: list[float], pct: float) -> float | None:
        if not samples:
            return None
        ordered = sorted(samples)
        index = round((len(ordered) - 1) * pct)
        index = max(0, min(index, len(ordered) - 1))
        return ordered[index]

    @staticmethod
    def _find_bursty_coalesce_index(pending: list[HookOutboxQueueItem], event_type: str) -> int | None:
        """Find a same-type bursty item after the latest critical boundary."""
        last_critical = -1
        for idx in range(len(pending) - 1, -1, -1):
            if pending[idx].classification == "critical":
                last_critical = idx
                break

        for idx in range(len(pending) - 1, last_critical, -1):
            item = pending[idx]
            if item.classification == "bursty" and item.event_type == event_type:
                return idx
        return None

    @staticmethod
    def _find_oldest_bursty_index(pending: list[HookOutboxQueueItem]) -> int | None:
        for idx, item in enumerate(pending):
            if item.classification == "bursty":
                return idx
        return None

    @staticmethod
    def _bursty_item_count(pending: list[HookOutboxQueueItem]) -> int:
        return sum(1 for item in pending if item.classification == "bursty")

    @staticmethod
    def _bursty_capacity_limit() -> int:
        return max(0, HOOK_OUTBOX_SESSION_MAX_PENDING - HOOK_OUTBOX_SESSION_CRITICAL_RESERVE)

    async def _session_outbox_depth(self, session_id: str) -> int:
        """Return outstanding per-session depth including in-flight items."""
        queue_state = self._session_outbox_queues.get(session_id)
        if queue_state is None:
            return 0
        async with queue_state.lock:
            return max(len(queue_state.pending), len(queue_state.claimed_row_ids))

    async def _should_pause_hook_outbox_claims(self, session_id: str) -> bool:
        """Decide whether claims should be paused for a session via watermark hysteresis."""
        depth = await self._session_outbox_depth(session_id)
        paused_sessions = self._hook_outbox_claim_paused_sessions
        is_paused = session_id in paused_sessions

        if is_paused:
            if depth <= HOOK_OUTBOX_SESSION_CLAIM_LOW_WATERMARK:
                paused_sessions.discard(session_id)
                return False
            return True

        if depth >= HOOK_OUTBOX_SESSION_CLAIM_HIGH_WATERMARK:
            paused_sessions.add(session_id)
            return True

        return False

    def _maybe_warn_hook_backlog(self, session_id: str, depth: int) -> None:
        if depth < HOOK_OUTBOX_BACKLOG_WARN_THRESHOLD:
            return
        now = time.monotonic()
        last_warn = self._hook_outbox_last_backlog_warn_at.get(session_id, 0.0)
        if (now - last_warn) < HOOK_OUTBOX_WARN_LOG_INTERVAL_S:
            return
        self._hook_outbox_last_backlog_warn_at[session_id] = now
        logger.warning(
            "Hook outbox backlog threshold exceeded",
            session_id=session_id,
            queue_depth=depth,
            threshold=HOOK_OUTBOX_BACKLOG_WARN_THRESHOLD,
        )

    def _record_hook_lag_sample(self, row: HookOutboxRow) -> None:
        created_at_raw = row.get("created_at")
        if not isinstance(created_at_raw, str) or not created_at_raw:
            return
        try:
            created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
        except ValueError:
            return
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        else:
            created_at = created_at.astimezone(UTC)

        lag_s = max(0.0, (datetime.now(UTC) - created_at).total_seconds())
        self._hook_outbox_lag_samples_s.append(lag_s)
        overflow = len(self._hook_outbox_lag_samples_s) - HOOK_OUTBOX_MAX_LAG_SAMPLES
        if overflow > 0:
            del self._hook_outbox_lag_samples_s[:overflow]

        session_id = str(row.get("session_id") or "")
        if not session_id or lag_s < HOOK_OUTBOX_LAG_WARN_THRESHOLD_S:
            return
        now = time.monotonic()
        last_warn = self._hook_outbox_last_lag_warn_at.get(session_id, 0.0)
        if (now - last_warn) < HOOK_OUTBOX_WARN_LOG_INTERVAL_S:
            return
        self._hook_outbox_last_lag_warn_at[session_id] = now
        logger.warning(
            "Hook outbox lag threshold exceeded",
            session_id=session_id,
            lag_s=round(lag_s, 3),
            threshold_s=HOOK_OUTBOX_LAG_WARN_THRESHOLD_S,
            event_type=str(row.get("event_type") or ""),
        )

    def _maybe_log_hook_outbox_summary(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - self._hook_outbox_last_summary_at) < HOOK_OUTBOX_SUMMARY_INTERVAL_S:
            return

        queue_depth = 0
        for state in self._session_outbox_queues.values():
            queue_depth += len(state.pending)

        stale_dropped = self._hook_outbox_stale_dropped_count

        if (
            not force
            and self._hook_outbox_processed_count == 0
            and self._hook_outbox_coalesced_count == 0
            and stale_dropped == 0
            and queue_depth == 0
        ):
            self._hook_outbox_last_summary_at = now
            return

        p95_lag = self._percentile(self._hook_outbox_lag_samples_s, 0.95)
        p99_lag = self._percentile(self._hook_outbox_lag_samples_s, 0.99)
        logger.info(
            "Hook outbox summary",
            processed=self._hook_outbox_processed_count,
            coalesced=self._hook_outbox_coalesced_count,
            stale_dropped=stale_dropped,
            queue_depth=queue_depth,
            lag_sample_count=len(self._hook_outbox_lag_samples_s),
            p95_lag_s=round(p95_lag, 3) if p95_lag is not None else None,
            p99_lag_s=round(p99_lag, 3) if p99_lag is not None else None,
        )
        self._hook_outbox_last_summary_at = now

    def _hook_outbox_backoff(self, attempt: int) -> float:
        """Compute exponential backoff for hook outbox retries."""
        safe_attempt = max(1, attempt)
        delay: float = float(HOOK_OUTBOX_BASE_BACKOFF_S) * (2.0 ** (safe_attempt - 1))
        return min(delay, float(HOOK_OUTBOX_MAX_BACKOFF_S))

    def _is_retryable_hook_error(self, exc: Exception) -> bool:
        """Return True if hook dispatch errors should be retried."""
        if isinstance(exc, (AgentStatusIntegrityError, SessionCreationRefused)):
            return False
        if isinstance(exc, ValueError) and "not found" in str(exc):
            return False
        if isinstance(exc, json.JSONDecodeError) and "Extra data" in str(exc):
            return False
        return True

    async def _ensure_headless_session(
        self,
        session_id: str,
        data: dict[str, object],  # guard: loose-dict - Hook payload is dynamic JSON
        caller_email: str | None,
    ) -> Session:
        """Create a headless session row for standalone hook events."""
        native_log_file = optional_payload_str_value(data, "native_log_file") or optional_payload_str_value(
            data, "transcript_path"
        )
        native_session_id = optional_payload_str_value(data, "native_session_id") or optional_payload_str_value(
            data, "session_id"
        )
        agent_str = optional_payload_str_value(data, "agent_name")
        workdir = optional_payload_str_value(data, "cwd")
        project_path, subdir = self._resolve_headless_project_context(workdir)
        logger.info(
            "Creating headless session",
            session_id=session_id,
            agent=agent_str,
            project_path=project_path or "",
        )
        origin_metadata = TerminalOriginMetadata(email=caller_email) if caller_email else None
        identity = (
            get_identity_resolver().resolve(InputOrigin.TERMINAL.value, origin_metadata) if origin_metadata else None
        )
        operator = is_operator_principal(local_caller_principal(caller_email))
        if operator:
            logger.info(
                "headless_session_bootstrapped_under_operator",
                session_id=session_id,
                native_session_id=native_session_id or "",
                project_path=project_path or "",
            )
        cmd = CreateSessionCommand(
            session_id=session_id,
            headless=True,
            native_session_id=str(native_session_id) if native_session_id else None,
            native_log_file=str(native_log_file) if native_log_file else None,
            project_path=project_path or "",
            subdir=subdir,
            origin=InputOrigin.TERMINAL.value,
            origin_metadata=origin_metadata,
            human_role=None if operator or (identity and identity.person_role) else HUMAN_ROLE_CUSTOMER,
            operator=operator,
            launch_intent=SessionLaunchIntent(
                kind=SessionLaunchKind.AGENT,
                agent=agent_str,
                native_session_id=str(native_session_id) if native_session_id else None,
                dispatch_mode=AgentDispatchMode.FIXED,
                thinking_mode=optional_payload_str_value(data, "thinking_mode") or _HEADLESS_DEFAULT_THINKING_MODE,
            ),
            entry_point=SessionEntryPoint.GENERATED_TOOL_CALL,
        )
        result = await get_command_service().create_session(cmd)
        created_session_id = str(result.get("session_id") or session_id)
        session = await db.get_session(created_session_id)
        if not session:
            raise ValueError(f"Headless session creation returned missing session: {created_session_id}")
        await publish_session_source_change(created_session_id, RuntimeSessionChange.CREATED)
        return session

    def _resolve_headless_project_context(self, workdir: str | None) -> tuple[str | None, str | None]:
        """Map a hook workdir onto registry-folder and subdir metadata."""
        if not workdir:
            return None, None
        registry_roots = [str(entry.path) for entry in load_registered_entries() if entry.is_present]
        return split_project_path_and_subdir(workdir, registry_roots)

    async def _handle_session_state_mutation_event(
        self,
        session_id: str,
        event_type: str,
        data: dict[str, object],  # guard: loose-dict - Hook payload is dynamic JSON
        session: Session,
    ) -> bool:
        """Handle outbox events whose only effect is session-row mutation."""
        if event_type == AgentHookEvents.CHECKPOINT_SEEN:
            await handle_checkpoint_seen(db, session_id=session_id, payload=data)
            return True
        if event_type == AgentHookEvents.NATIVE_METADATA_UPDATE:
            await handle_native_metadata_update(db, session_id=session_id, payload=data)
            await self._schedule_projection_from_signal(session_id, session)
            return True
        if event_type == AgentHookEvents.NATIVE_SESSION_REFRESH:
            await handle_native_session_refresh(db, session_id=session_id, payload=data)
            await self._schedule_projection_from_signal(session_id, session)
            return True
        return False

    async def _dispatch_hook_event(
        self,
        session_id: str,
        event_type: str,
        data: dict[str, object],  # guard: loose-dict - Hook payload is dynamic JSON
        *,
        outbox_row_id: int,
    ) -> None:
        """Dispatch a hook event directly global Event Bus."""
        raw_caller_email = data.pop(HeadlessBootstrapField.CALLER_EMAIL, None)
        caller_email = raw_caller_email if isinstance(raw_caller_email, str) else None
        launch_context, runtime_run_id = take_normalized_launch_context(cast(MutableMapping[str, JsonValue], data))
        session = await db.get_session(session_id)
        if not session:
            if launch_context is not None:
                return
            if event_type != AgentHookEvents.AGENT_SESSION_START:
                logger.debug(
                    "Ignoring hook event for unknown session (not session_start)",
                    session_id=session_id,
                    event_type=event_type,
                )
                return
            if data.get(HeadlessBootstrapField.AUTHORIZATION) is not True:
                logger.debug(
                    _HEADLESS_BOOTSTRAP_AUTHORITY_ABSENT,
                    session_id=session_id,
                    event_type=event_type,
                )
                return
            session = await self._ensure_headless_session(session_id, data, caller_email)
        if launch_context is not None and not is_current_compaction_launch(session, launch_context):
            return
        if runtime_run_mismatch(
            launch_context,
            runtime_run_id,
            session.runtime_run_id,
            native_identity_event=event_type
            in {AgentHookEvents.NATIVE_METADATA_UPDATE, AgentHookEvents.NATIVE_SESSION_REFRESH},
        ):
            logger.info(_RUNTIME_HOOK_RUN_MISMATCH_EVENT, session_id=session_id)
            return
        if launch_context is not None and event_type == AgentHookEvents.AGENT_ERROR:
            await session_compaction_owner.restore_ordinary(session.session_id, launch_context.attempt_id)
            return
        # Native metadata arrives through the outbox and can legitimately lag
        # behind session close. Persist those row mutations before the generic
        # closed-session guard so revive retains the last known native binding.
        if launch_context is None and await self._handle_session_state_mutation_event(
            session_id, event_type, data, session
        ):
            return

        if session.lifecycle_status == "closed":
            logger.debug(
                "Ignoring hook event for closed session",
                session_id=session_id,
                event_type=event_type,
            )
            return

        if event_type == AgentHookEvents.CHECKPOINT_RELAY:
            # Settles only once control delivery has accepted the handoff; a refused handoff retries.
            await handle_checkpoint_relay(session_id=session_id, payload=data)
            return

        transcript_path = data.get("transcript_path")
        native_session_id = data.get("native_session_id")
        native_log_file = data.get("native_log_file")
        raw_agent_name = data.get("agent_name")
        normalized_agent_name = raw_agent_name.strip().lower() if isinstance(raw_agent_name, str) else ""

        has_transcript_path = isinstance(transcript_path, str) and bool(transcript_path)
        has_native_log = isinstance(native_log_file, str) and bool(native_log_file)
        is_subagent = None
        if not has_transcript_path and has_native_log and isinstance(native_log_file, str):
            transcript_path = native_log_file
            data["transcript_path"] = native_log_file
            has_transcript_path = True
        # Subagent detection reads the transcript and is Codex-specific; probing
        # other runtimes (e.g. DSH's zstd-compressed artifacts) would decode
        # binary as text and fail dispatch.
        if normalized_agent_name == AgentName.CODEX.value:
            if has_transcript_path:
                is_subagent = is_codex_subagent_transcript(str(transcript_path))
            elif has_native_log:
                is_subagent = is_codex_subagent_transcript(str(native_log_file))

        if normalized_agent_name == AgentName.CODEX.value and event_type == AgentHookEvents.AGENT_STOP and is_subagent:
            logger.trace(
                "Dropping Codex subagent agent_stop notification",
                session_id=session_id,
                native_session_id=(native_session_id or ""),
                event_type=event_type,
                transcript_path=(str(transcript_path) if isinstance(transcript_path, str) else None),
            )
            return

        # Headless sessions have no tmux — skip output polling to avoid spawning one.
        if launch_context is None and session.tmux_session_name:
            await self._ensure_output_polling(session)

        if event_type not in ALL_AGENT_HOOK_EVENTS:
            logger.debug("Transcript capture event handled", event=event_type, session=session_id)
            return

        if event_type == AgentHookEvents.AGENT_ERROR:
            severity = data.get("severity")
            retryable = data.get("retryable")
            code = data.get("code")
            details = data.get("details")
            await publish_runtime_error(
                session_id=session_id,
                message=str(data.get("message", "")),
                event_id=occurrence_id(AgentHookEvents.AGENT_ERROR, session_id, str(outbox_row_id)),
                source=str(data.get("source")) if isinstance(data.get("source"), str) else None,
                details=cast(Mapping[str, object] | None, details if isinstance(details, dict) else None),
                severity=severity if isinstance(severity, str) else "error",
                retryable=retryable if isinstance(retryable, bool) else False,
                code=code if isinstance(code, str) else None,
            )
        else:
            # Outbox rows store the event as text; consumers compare by enum identity.
            hook_event = AgentHookEvents(event_type)
            payload = build_agent_payload(hook_event, data)
            context = AgentEventContext(
                session_id=session_id,
                event_type=hook_event,
                data=payload,
                runtime_run_id=runtime_run_id,
                compaction_launch_context=launch_context,
            )
            # Settle the outbox item only after the coordinator finishes handling this owner event.
            await self._handle_agent_event_direct(context)

    async def _wal_checkpoint_loop(self) -> None:
        """Periodically checkpoint the SQLite WAL to prevent unbounded growth."""
        while not self.shutdown_event.is_set():
            await asyncio.sleep(300)  # 5 minutes
            if self.shutdown_event.is_set():
                break
            try:
                await db.wal_checkpoint()
            except Exception as exc:
                logger.warning("WAL checkpoint failed: %s", exc)

    async def _hook_outbox_worker(self) -> None:
        """Drain hook outbox for durable, restart-safe delivery.

        Dispatch model:
        - One logical serial worker per session (strict ordering inside session).
        - Different sessions are handled in parallel.
        - Paused sessions are excluded at the DB level to prevent head-of-line blocking.
        - Stale non-lifecycle rows are dropped before claiming.
        """
        try:
            while not self.shutdown_event.is_set():
                now = datetime.now(UTC)
                now_iso = now.isoformat()
                lock_cutoff = (now - timedelta(seconds=HOOK_OUTBOX_LOCK_TTL_S)).isoformat()

                # Re-evaluate paused sessions before excluding them from the fetch.
                for session_id in frozenset(self._hook_outbox_claim_paused_sessions):
                    await self._should_pause_hook_outbox_claims(session_id)

                # Snapshot paused sessions and exclude them at the DB level so their
                # rows don't consume batch slots (prevents head-of-line blocking).
                paused_snapshot = frozenset(self._hook_outbox_claim_paused_sessions)
                try:
                    rows = await db.fetch_hook_outbox_batch(
                        now_iso, HOOK_OUTBOX_BATCH_SIZE, lock_cutoff, exclude_session_ids=paused_snapshot
                    )

                    if not rows:
                        self._maybe_log_hook_outbox_summary()
                        await asyncio.sleep(HOOK_OUTBOX_POLL_INTERVAL_S)
                        continue

                    # Drop stale non-lifecycle rows before claiming.
                    stale_row_ids: list[int] = []
                    fresh_rows: list[HookOutboxRow] = []
                    for row in rows:
                        if self._is_stale_outbox_row(row):
                            stale_row_ids.append(int(row["id"]))
                        else:
                            fresh_rows.append(row)

                    if stale_row_ids:
                        for stale_id in stale_row_ids:
                            stale_row = next(r for r in rows if int(r["id"]) == stale_id)
                            event_type = str(stale_row.get("event_type") or "")
                            logger.info(
                                "Dropping stale outbox row",
                                row_id=stale_id,
                                event_type=event_type,
                                session_id=str(stale_row.get("session_id") or ""),
                            )
                            await db.delete_hook_outbox_row(stale_id)
                        self._hook_outbox_stale_dropped_count += len(stale_row_ids)

                    # Defense-in-depth: re-check pause state for rows that passed the DB
                    # filter (catches snapshot-to-fetch races).
                    claimable_rows: list[HookOutboxRow] = []
                    for row in fresh_rows:
                        session_id = str(row["session_id"])
                        if await self._should_pause_hook_outbox_claims(session_id):
                            continue
                        claimable_rows.append(row)

                    if not claimable_rows:
                        self._maybe_log_hook_outbox_summary()
                        await asyncio.sleep(HOOK_OUTBOX_POLL_INTERVAL_S)
                        continue

                    row_ids = [int(row["id"]) for row in claimable_rows]
                    claimed_ids = await db.claim_hook_outbox_batch(row_ids, now_iso, lock_cutoff)

                    for row in claimable_rows:
                        if self.shutdown_event.is_set():
                            break
                        if int(row["id"]) not in claimed_ids:
                            continue

                        session_id = str(row["session_id"])
                        await self._enqueue_session_outbox_item(session_id, row)

                    self._maybe_log_hook_outbox_summary()
                except Exception:
                    logger.exception(_HOOK_OUTBOX_BATCH_FAILED_MESSAGE)
                    await asyncio.sleep(HOOK_OUTBOX_POLL_INTERVAL_S)
        finally:
            self._maybe_log_hook_outbox_summary(force=True)

    def _get_or_create_session_outbox_queue(self, session_id: str) -> HookOutboxSessionQueue:
        """Return the in-memory queue state for a session."""
        queue_state = self._session_outbox_queues.get(session_id)
        if queue_state is None:
            queue_state = HookOutboxSessionQueue()
            self._session_outbox_queues[session_id] = queue_state
        return queue_state

    @staticmethod
    def _discard_claimed_row(
        pending: list[HookOutboxQueueItem],
        claimed_row_ids: set[int],
        drop_idx: int,
        dropped_rows: list[HookOutboxRow],
    ) -> None:
        """Remove a queued item and clear its claimed-row marker."""
        dropped_row = pending.pop(drop_idx).row
        dropped_row_id = int(dropped_row.get("id") or 0)
        dropped_rows.append(dropped_row)
        if dropped_row_id:
            claimed_row_ids.discard(dropped_row_id)

    @staticmethod
    def _append_queue_item(
        pending: list[HookOutboxQueueItem],
        claimed_row_ids: set[int],
        queue_item: HookOutboxQueueItem,
        row_id: int,
    ) -> None:
        """Append a queue item and track its claimed row ID."""
        pending.append(queue_item)
        if row_id:
            claimed_row_ids.add(row_id)

    def _enqueue_bursty_item(
        self,
        pending: list[HookOutboxQueueItem],
        claimed_row_ids: set[int],
        queue_item: HookOutboxQueueItem,
        row: HookOutboxRow,
        row_id: int,
        event_type: str,
        dropped_rows: list[HookOutboxRow],
    ) -> bool:
        """Apply bursty queue coalescing and capacity rules."""
        replace_idx = self._find_bursty_coalesce_index(pending, event_type)
        if replace_idx is not None:
            replaced_row = pending[replace_idx].row
            replaced_row_id = int(replaced_row.get("id") or 0)
            dropped_rows.append(replaced_row)
            if replaced_row_id:
                claimed_row_ids.discard(replaced_row_id)
            pending[replace_idx] = queue_item
            if row_id:
                claimed_row_ids.add(row_id)
            return True

        bursty_limit = self._bursty_capacity_limit()
        if bursty_limit == 0:
            dropped_rows.append(row)
            return False

        while self._bursty_item_count(pending) >= bursty_limit:
            drop_idx = self._find_oldest_bursty_index(pending)
            if drop_idx is None:
                break
            self._discard_claimed_row(pending, claimed_row_ids, drop_idx, dropped_rows)

        if len(pending) >= HOOK_OUTBOX_SESSION_MAX_PENDING:
            drop_idx = self._find_oldest_bursty_index(pending)
            if drop_idx is None:
                dropped_rows.append(row)
                return False
            self._discard_claimed_row(pending, claimed_row_ids, drop_idx, dropped_rows)

        self._append_queue_item(pending, claimed_row_ids, queue_item, row_id)
        return True

    def _enqueue_critical_item(
        self,
        pending: list[HookOutboxQueueItem],
        claimed_row_ids: set[int],
        queue_item: HookOutboxQueueItem,
        row_id: int,
        dropped_rows: list[HookOutboxRow],
    ) -> tuple[bool, bool]:
        """Apply critical-item queue admission rules."""
        while len(pending) >= HOOK_OUTBOX_SESSION_MAX_PENDING:
            drop_idx = self._find_oldest_bursty_index(pending)
            if drop_idx is None:
                return False, True
            self._discard_claimed_row(pending, claimed_row_ids, drop_idx, dropped_rows)

        self._append_queue_item(pending, claimed_row_ids, queue_item, row_id)
        return True, False

    async def _mark_dropped_outbox_rows(
        self,
        dropped_rows: list[HookOutboxRow],
    ) -> None:
        """Delete coalesced rows from durable storage."""
        if not dropped_rows:
            return
        self._hook_outbox_coalesced_count += len(dropped_rows)
        for dropped in dropped_rows:
            await db.delete_hook_outbox_row(dropped["id"])

    async def _requeue_critical_outbox_row(
        self,
        session_id: str,
        row: HookOutboxRow,
        row_id: int,
        queue_depth: int,
    ) -> None:
        """Retry a claimed critical row later when the session queue is full."""
        logger.debug(
            "Hook outbox session queue at capacity; deferring claimed critical row",
            session_id=session_id,
            row_id=row_id or row["id"],
            queue_depth=queue_depth,
            max_pending=HOOK_OUTBOX_SESSION_MAX_PENDING,
        )
        attempt = int(row.get("attempt_count", 0)) + 1
        delay = self._hook_outbox_backoff(attempt)
        retry_at = (datetime.now(UTC) + timedelta(seconds=delay)).isoformat()
        await db.mark_hook_outbox_failed(
            row_id=row_id or row["id"],
            attempt_count=attempt,
            next_attempt_at=retry_at,
            error="backpressure:session_queue_full",
        )

    def _ensure_session_outbox_worker(self, session_id: str) -> None:
        """Start the per-session worker if it is not already running."""
        worker = self._session_outbox_workers.get(session_id)
        if worker and not worker.done():
            return
        task = asyncio.create_task(self._run_session_outbox_worker(session_id), name=f"outbox-worker-{session_id}")
        self._session_outbox_workers[session_id] = task
        self._track_background_task(task, f"outbox-worker:{session_id}")

    async def _enqueue_session_outbox_item(
        self,
        session_id: str,
        row: HookOutboxRow,
    ) -> None:
        """Enqueue a claimed outbox row with bounded burst coalescing."""
        event_type = str(row.get("event_type") or "")
        row_id = int(row.get("id") or 0)
        classification = self._classify_hook_event(event_type)
        queue_state = self._get_or_create_session_outbox_queue(session_id)
        dropped_rows: list[HookOutboxRow] = []
        enqueued = False
        requeue_claimed_critical = False
        duplicate_claimed_row = False
        queue_item = HookOutboxQueueItem(
            row=row,
            event_type=event_type,
            classification=classification,
        )

        async with queue_state.lock:
            pending = queue_state.pending
            claimed_row_ids = queue_state.claimed_row_ids

            # Ignore duplicate claims for rows already queued or currently in-flight.
            if row_id and row_id in claimed_row_ids:
                duplicate_claimed_row = True
            elif classification == "bursty":
                enqueued = self._enqueue_bursty_item(
                    pending,
                    claimed_row_ids,
                    queue_item,
                    row,
                    row_id,
                    event_type,
                    dropped_rows,
                )
            else:
                enqueued, requeue_claimed_critical = self._enqueue_critical_item(
                    pending,
                    claimed_row_ids,
                    queue_item,
                    row_id,
                    dropped_rows,
                )

            queue_depth = len(pending)
            if enqueued:
                queue_state.notify.set()

        await self._mark_dropped_outbox_rows(dropped_rows)

        if requeue_claimed_critical and not duplicate_claimed_row:
            await self._requeue_critical_outbox_row(session_id, row, row_id, queue_depth)

        self._maybe_warn_hook_backlog(session_id, queue_depth)
        self._ensure_session_outbox_worker(session_id)

    async def _run_session_outbox_worker(self, session_id: str) -> None:
        """Process claimed outbox rows serially for a single session."""
        queue_state = self._session_outbox_queues.get(session_id)
        if queue_state is None:
            return

        try:
            while not self.shutdown_event.is_set():
                row: HookOutboxRow | None = None
                queue_depth = 0

                async with queue_state.lock:
                    if queue_state.pending:
                        row = queue_state.pending.pop(0).row
                    queue_depth = len(queue_state.pending)
                    if not queue_state.pending:
                        queue_state.notify.clear()

                if row is None:
                    try:
                        await asyncio.wait_for(queue_state.notify.wait(), timeout=HOOK_OUTBOX_SESSION_IDLE_TIMEOUT_S)
                    except TimeoutError:
                        async with queue_state.lock:
                            if not queue_state.pending:
                                break
                    continue

                self._maybe_warn_hook_backlog(session_id, queue_depth)
                in_flight_row_id = int(row.get("id") or 0)
                try:
                    await self._process_outbox_item(row)
                except Exception:
                    logger.exception(_HOOK_OUTBOX_ROW_FAILED_MESSAGE, row_id=in_flight_row_id, session_id=session_id)
                finally:
                    if in_flight_row_id:
                        async with queue_state.lock:
                            queue_state.claimed_row_ids.discard(in_flight_row_id)
        finally:
            current = asyncio.current_task()
            if self._session_outbox_workers.get(session_id) is current:
                self._session_outbox_workers.pop(session_id, None)
            active_queue = self._session_outbox_queues.get(session_id)
            if active_queue is queue_state:
                async with queue_state.lock:
                    if not queue_state.pending and not queue_state.claimed_row_ids:
                        self._session_outbox_queues.pop(session_id, None)

    async def _process_outbox_item(
        self,
        row: HookOutboxRow,
    ) -> None:
        """Process a single outbox item. Handles its own success/failure lifecycle."""
        row_id = row["id"]
        try:
            payload = cast(
                dict[str, object],  # guard: loose-dict - Hook payload JSON
                json.loads(str(row["payload"])),
            )
        except json.JSONDecodeError as exc:
            logger.error("Hook outbox payload invalid", row_id=row_id, error=str(exc))
            await db.delete_hook_outbox_row(row_id)
            self._hook_outbox_processed_count += 1
            self._record_hook_lag_sample(row)
            return

        try:
            await self._dispatch_hook_event(
                str(row["session_id"]),
                str(row["event_type"]),
                payload,
                outbox_row_id=row_id,
            )
            await db.delete_hook_outbox_row(row_id)
            self._hook_outbox_processed_count += 1
            self._record_hook_lag_sample(row)
        except ShutdownRefusal as refusal:
            # The runtime refused new work while draining: the event was not consumed, so it stays pending.
            retry_at = datetime.now(UTC) + timedelta(seconds=refusal.retry_after_seconds)
            await db.defer_hook_outbox_row(row_id, retry_at.isoformat())
        except Exception as exc:
            attempt = int(row.get("attempt_count", 0)) + 1
            error_str = str(exc)
            if not self._is_retryable_hook_error(exc):
                logger.error(
                    "Hook outbox event dropped (non-retryable)",
                    row_id=row_id,
                    attempt=attempt,
                    error=error_str,
                )
                await db.delete_hook_outbox_row(row_id)
                self._hook_outbox_processed_count += 1
                self._record_hook_lag_sample(row)
                return

            delay = self._hook_outbox_backoff(attempt)
            next_attempt = (datetime.now(UTC) + timedelta(seconds=delay)).isoformat()
            logger.error(
                "Hook outbox dispatch failed (retrying)",
                row_id=row_id,
                attempt=attempt,
                next_attempt_in_s=round(delay, 2),
                error=error_str,
            )
            await db.mark_hook_outbox_failed(row_id, attempt, next_attempt, error_str)
