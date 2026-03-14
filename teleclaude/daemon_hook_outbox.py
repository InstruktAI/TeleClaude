"""Hook outbox processing mixin for TeleClaudeDaemon."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal, cast

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core.agents import AgentName
from teleclaude.core.codex_transcript import discover_codex_transcript_path
from teleclaude.core.db import HookOutboxRow, db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    AgentEventContext,
    AgentHookEvents,
    ErrorEventContext,
    SessionLifecycleContext,
    TeleClaudeEvents,
    build_agent_payload,
)
from teleclaude.core.models import Session
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_utils import (
    get_short_project_name,
    split_project_path_and_subdir,
)
from teleclaude.transport.redis_transport import RedisTransport

if TYPE_CHECKING:
    from teleclaude.core.cache import DaemonCache

logger = get_logger(__name__)


# Hook outbox worker
HOOK_OUTBOX_POLL_INTERVAL_S: float = float(os.getenv("HOOK_OUTBOX_POLL_INTERVAL_S", "1"))
HOOK_OUTBOX_BATCH_SIZE: int = int(os.getenv("HOOK_OUTBOX_BATCH_SIZE", "25"))
HOOK_OUTBOX_LOCK_TTL_S: float = float(os.getenv("HOOK_OUTBOX_LOCK_TTL_S", "30"))
HOOK_OUTBOX_BASE_BACKOFF_S: float = float(os.getenv("HOOK_OUTBOX_BASE_BACKOFF_S", "1"))
HOOK_OUTBOX_MAX_BACKOFF_S: float = float(os.getenv("HOOK_OUTBOX_MAX_BACKOFF_S", "60"))
HOOK_OUTBOX_SESSION_IDLE_TIMEOUT_S: float = float(os.getenv("HOOK_OUTBOX_SESSION_IDLE_TIMEOUT_S", "5"))
HOOK_OUTBOX_SESSION_MAX_PENDING: int = int(os.getenv("HOOK_OUTBOX_SESSION_MAX_PENDING", "32"))
HOOK_OUTBOX_SESSION_CRITICAL_RESERVE: int = int(os.getenv("HOOK_OUTBOX_SESSION_CRITICAL_RESERVE", "8"))
HOOK_OUTBOX_SESSION_CLAIM_HIGH_WATERMARK: int = int(
    os.getenv(
        "HOOK_OUTBOX_SESSION_CLAIM_HIGH_WATERMARK",
        str(max(1, HOOK_OUTBOX_SESSION_MAX_PENDING - 8)),
    )
)
HOOK_OUTBOX_SESSION_CLAIM_LOW_WATERMARK: int = int(
    os.getenv(
        "HOOK_OUTBOX_SESSION_CLAIM_LOW_WATERMARK",
        str(max(0, HOOK_OUTBOX_SESSION_CLAIM_HIGH_WATERMARK // 3)),
    )
)
HOOK_OUTBOX_SUMMARY_INTERVAL_S: float = float(os.getenv("HOOK_OUTBOX_SUMMARY_INTERVAL_S", "15"))
HOOK_OUTBOX_BACKLOG_WARN_THRESHOLD: int = int(os.getenv("HOOK_OUTBOX_BACKLOG_WARN_THRESHOLD", "20"))
HOOK_OUTBOX_LAG_WARN_THRESHOLD_S: float = float(os.getenv("HOOK_OUTBOX_LAG_WARN_THRESHOLD_S", "3"))
HOOK_OUTBOX_WARN_LOG_INTERVAL_S: float = float(os.getenv("HOOK_OUTBOX_WARN_LOG_INTERVAL_S", "15"))
HOOK_OUTBOX_MAX_LAG_SAMPLES: int = int(os.getenv("HOOK_OUTBOX_MAX_LAG_SAMPLES", "2048"))

if HOOK_OUTBOX_SESSION_CLAIM_HIGH_WATERMARK > HOOK_OUTBOX_SESSION_MAX_PENDING:
    HOOK_OUTBOX_SESSION_CLAIM_HIGH_WATERMARK = HOOK_OUTBOX_SESSION_MAX_PENDING  # pyright: ignore[reportConstantRedefinition]
if HOOK_OUTBOX_SESSION_CLAIM_LOW_WATERMARK >= HOOK_OUTBOX_SESSION_CLAIM_HIGH_WATERMARK:
    HOOK_OUTBOX_SESSION_CLAIM_LOW_WATERMARK = max(0, HOOK_OUTBOX_SESSION_CLAIM_HIGH_WATERMARK - 1)  # pyright: ignore[reportConstantRedefinition]
if HOOK_OUTBOX_SESSION_CRITICAL_RESERVE < 0:
    HOOK_OUTBOX_SESSION_CRITICAL_RESERVE = 0  # pyright: ignore[reportConstantRedefinition]
if HOOK_OUTBOX_SESSION_CRITICAL_RESERVE > HOOK_OUTBOX_SESSION_MAX_PENDING:
    HOOK_OUTBOX_SESSION_CRITICAL_RESERVE = HOOK_OUTBOX_SESSION_MAX_PENDING  # pyright: ignore[reportConstantRedefinition]

HOOK_EVENT_CLASS_CRITICAL: frozenset[str] = frozenset(
    {
        AgentHookEvents.AGENT_SESSION_START,
        AgentHookEvents.USER_PROMPT_SUBMIT,
        AgentHookEvents.AGENT_STOP,
        AgentHookEvents.AGENT_SESSION_END,
        AgentHookEvents.AGENT_ERROR,
    }
)
HOOK_EVENT_CLASS_BURSTY: frozenset[str] = frozenset(
    {
        AgentHookEvents.TOOL_USE,
        AgentHookEvents.TOOL_DONE,
    }
)


@dataclass
class _HookOutboxQueueItem:
    """In-memory queue payload for per-session hook outbox processing."""

    row: HookOutboxRow
    event_type: str
    classification: Literal["critical", "bursty"]


@dataclass
class _HookOutboxSessionQueue:
    """Per-session hook queue state."""

    pending: list[_HookOutboxQueueItem] = field(default_factory=list)
    claimed_row_ids: set[int] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    notify: asyncio.Event = field(default_factory=asyncio.Event)


class _DaemonHookOutboxMixin:  # pyright: ignore[reportUnusedClass]
    """Hook outbox processing methods extracted from TeleClaudeDaemon."""

    if TYPE_CHECKING:
        shutdown_event: asyncio.Event
        _background_tasks: set[asyncio.Task[object]]
        _session_outbox_queues: dict[str, _HookOutboxSessionQueue]
        _session_outbox_workers: dict[str, asyncio.Task[None]]
        _hook_outbox_processed_count: int
        _hook_outbox_coalesced_count: int
        _hook_outbox_lag_samples_s: list[float]
        _hook_outbox_last_summary_at: float
        _hook_outbox_last_backlog_warn_at: dict[str, float]
        _hook_outbox_last_lag_warn_at: dict[str, float]
        _hook_outbox_claim_paused_sessions: set[str]
        cache: DaemonCache

        def _queue_background_task(self, coro: Coroutine[object, object, object], label: str) -> None: ...
        async def _handle_agent_event(self, _event: str, context: AgentEventContext) -> None: ...
        async def _ensure_output_polling(self, session: Session) -> None: ...

    @staticmethod
    def _make_stale_read_callback(
        local_computer_name: str,
        get_adapter: Callable[[], object],
    ) -> Callable[[str, str], None]:
        """Return the on_stale_read callback for DaemonCache.

        Args:
            local_computer_name: Name of the local computer (from config).
            get_adapter: Callable that returns the "redis" adapter (or None).
        """

        def _on_stale_read(resource_type: str, computer: str) -> None:
            # Local computers manage freshness via startup warming and TodoWatcher
            if computer in ("local", local_computer_name, ""):
                return
            adapter = get_adapter()
            if isinstance(adapter, RedisTransport):
                adapter.request_refresh(computer, resource_type, reason="ttl")

        return _on_stale_read

    def _log_background_task_exception(self, task_name: str) -> Callable[[asyncio.Task[object]], None]:
        """Return a done-callback that logs unexpected background task failures."""

        def _on_done(task: asyncio.Task[object]) -> None:
            try:
                task.result()
            except asyncio.CancelledError:
                return
            except Exception as e:  # pylint: disable=broad-exception-caught
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
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error("Background task failed (%s): %s", label, exc, exc_info=True)

        task.add_done_callback(_on_done)

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
    def _find_bursty_coalesce_index(pending: list[_HookOutboxQueueItem], event_type: str) -> int | None:
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
    def _find_oldest_bursty_index(pending: list[_HookOutboxQueueItem]) -> int | None:
        for idx, item in enumerate(pending):
            if item.classification == "bursty":
                return idx
        return None

    @staticmethod
    def _bursty_item_count(pending: list[_HookOutboxQueueItem]) -> int:
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

        if (
            not force
            and self._hook_outbox_processed_count == 0
            and self._hook_outbox_coalesced_count == 0
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
        if isinstance(exc, ValueError) and "not found" in str(exc):
            return False
        if isinstance(exc, json.JSONDecodeError) and "Extra data" in str(exc):
            return False
        return True

    async def _ensure_headless_session(
        self,
        session_id: str,
        data: dict[str, object],  # guard: loose-dict - Hook payload is dynamic JSON
    ) -> Session:
        """Create a headless session row for standalone hook events."""
        native_log_file = data.get("native_log_file") or data.get("transcript_path")
        native_session_id = data.get("native_session_id") or data.get("session_id")
        agent_name = data.get("agent_name")
        agent_str = str(agent_name) if isinstance(agent_name, str) and agent_name else None

        workdir = None
        raw_cwd = data.get("cwd")
        if isinstance(raw_cwd, str) and raw_cwd:
            workdir = raw_cwd

        project_path = None
        subdir = None
        if workdir:
            trusted_dirs = [d.path for d in config.computer.get_all_trusted_dirs()]
            project_path, subdir = split_project_path_and_subdir(workdir, trusted_dirs)

        title = "Standalone"
        if project_path:
            title = get_short_project_name(project_path, subdir)

        logger.info(
            "Creating headless session",
            session_id=session_id,
            agent=agent_str,
            project_path=project_path or "",
        )
        from teleclaude.constants import HUMAN_ROLE_CUSTOMER  # pylint: disable=import-outside-toplevel

        session = await db.create_headless_session(
            session_id=session_id,
            computer_name=config.computer.name,
            last_input_origin=InputOrigin.TERMINAL.value,
            title=title,
            active_agent=agent_str,
            native_session_id=str(native_session_id) if native_session_id else None,
            native_log_file=str(native_log_file) if native_log_file else None,
            project_path=project_path,
            subdir=subdir,
            human_role=HUMAN_ROLE_CUSTOMER,
        )

        event_bus.emit(
            TeleClaudeEvents.SESSION_STARTED,
            SessionLifecycleContext(session_id=session_id),
        )

        return session

    def _is_codex_headless_bootstrap_event(
        self,
        event_type: str,
        data: dict[str, object],  # guard: loose-dict - Hook payload is dynamic JSON
    ) -> bool:
        """Return True when a missing session should still be materialized for Codex headless hooks.

        TODO(codex-headless): remove this special-case path once Codex emits a stable
        session_start-equivalent event that can be used to create the headless session.
        """
        if event_type != AgentHookEvents.AGENT_STOP:
            return False

        raw_agent_name = data.get("agent_name")
        if not isinstance(raw_agent_name, str) or raw_agent_name.strip().lower() != AgentName.CODEX.value:
            return False

        raw_native_session_id = data.get("native_session_id")
        return isinstance(raw_native_session_id, str) and bool(raw_native_session_id.strip())

    async def _dispatch_hook_event(
        self,
        session_id: str,
        event_type: str,
        data: dict[str, object],  # guard: loose-dict - Hook payload is dynamic JSON
    ) -> None:
        """Dispatch a hook event directly global Event Bus."""
        session = await db.get_session(session_id)
        if not session:
            if event_type != AgentHookEvents.AGENT_SESSION_START and not self._is_codex_headless_bootstrap_event(
                event_type, data
            ):
                logger.debug(
                    "Ignoring hook event for unknown session (not session_start)",
                    session_id=session_id,
                    event_type=event_type,
                )
                return
            session = await self._ensure_headless_session(session_id, data)
        elif session.lifecycle_status == "closed":
            logger.debug(
                "Ignoring hook event for closed session",
                session_id=session_id,
                event_type=event_type,
            )
            return
        elif session.lifecycle_status == "headless" and session.last_input_origin != InputOrigin.TERMINAL.value:
            await db.update_session(session_id, last_input_origin=InputOrigin.TERMINAL.value)
            session = await db.get_session(session_id) or session

        transcript_path = data.get("transcript_path")
        native_session_id = data.get("native_session_id")
        native_log_file = data.get("native_log_file")
        raw_agent_name = data.get("agent_name")
        normalized_agent_name = raw_agent_name.strip().lower() if isinstance(raw_agent_name, str) else ""

        has_transcript_path = isinstance(transcript_path, str) and bool(transcript_path)
        has_native_log = isinstance(native_log_file, str) and bool(native_log_file)
        if (
            not has_transcript_path
            and not has_native_log
            and normalized_agent_name == AgentName.CODEX.value
            and isinstance(native_session_id, str)
            and native_session_id
        ):
            discovered_path = discover_codex_transcript_path(native_session_id)
            if discovered_path:
                native_log_file = discovered_path
                data["native_log_file"] = discovered_path
                data["transcript_path"] = discovered_path
                transcript_path = discovered_path
                has_transcript_path = True
                logger.debug(
                    "Resolved Codex transcript in hook worker",
                    session_id=session_id,
                    native_session_id=native_session_id,
                    path=discovered_path,
                )
        elif not has_transcript_path and has_native_log and isinstance(native_log_file, str):
            transcript_path = native_log_file
            data["transcript_path"] = native_log_file
            has_transcript_path = True

        update_kwargs = {}
        if normalized_agent_name in AgentName.choices() and session.active_agent != normalized_agent_name:
            update_kwargs["active_agent"] = normalized_agent_name
        if isinstance(transcript_path, str) and transcript_path:
            update_kwargs["native_log_file"] = transcript_path
        if isinstance(native_log_file, str) and native_log_file:
            update_kwargs["native_log_file"] = native_log_file
        if isinstance(native_session_id, str) and native_session_id:
            update_kwargs["native_session_id"] = native_session_id

        if update_kwargs:
            await db.update_session(session_id, **update_kwargs)

        # Headless sessions have no tmux — skip output polling to avoid spawning one.
        if session.tmux_session_name:
            await self._ensure_output_polling(session)

        if event_type not in AgentHookEvents.ALL:
            logger.debug("Transcript capture event handled", event=event_type, session=session_id)
            return

        if event_type == AgentHookEvents.AGENT_ERROR:
            severity = data.get("severity")
            retryable = data.get("retryable")
            code = data.get("code")
            context = ErrorEventContext(
                session_id=session_id,
                message=str(data.get("message", "")),
                source=str(data.get("source")) if "source" in data else None,
                details=data.get("details") if isinstance(data.get("details"), dict) else None,
                severity=severity if isinstance(severity, str) else "error",
                retryable=retryable if isinstance(retryable, bool) else False,
                code=code if isinstance(code, str) else None,
            )
            event_bus.emit(TeleClaudeEvents.ERROR, context)
        else:
            context = AgentEventContext(
                session_id=session_id,
                event_type=cast(AgentHookEvents, event_type),
                data=build_agent_payload(cast(AgentHookEvents, event_type), data),
            )
            # Directly await coordinator — outbox serialization depends on this completing
            # before the item is marked delivered. event_bus.emit would fire-and-forget.
            await self._handle_agent_event(TeleClaudeEvents.AGENT_EVENT, context)

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
        """
        try:
            while not self.shutdown_event.is_set():
                now = datetime.now(UTC)
                now_iso = now.isoformat()
                lock_cutoff = (now - timedelta(seconds=HOOK_OUTBOX_LOCK_TTL_S)).isoformat()
                rows = await db.fetch_hook_outbox_batch(now_iso, HOOK_OUTBOX_BATCH_SIZE, lock_cutoff)

                if not rows:
                    self._maybe_log_hook_outbox_summary()
                    await asyncio.sleep(HOOK_OUTBOX_POLL_INTERVAL_S)
                    continue

                claimable_rows: list[HookOutboxRow] = []
                for row in rows:
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
        finally:
            self._maybe_log_hook_outbox_summary(force=True)

    def _get_or_create_session_outbox_queue(self, session_id: str) -> _HookOutboxSessionQueue:
        """Return the in-memory queue state for a session."""
        queue_state = self._session_outbox_queues.get(session_id)
        if queue_state is None:
            queue_state = _HookOutboxSessionQueue()
            self._session_outbox_queues[session_id] = queue_state
        return queue_state

    @staticmethod
    def _discard_claimed_row(
        pending: list[_HookOutboxQueueItem],
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
        pending: list[_HookOutboxQueueItem],
        claimed_row_ids: set[int],
        queue_item: _HookOutboxQueueItem,
        row_id: int,
    ) -> None:
        """Append a queue item and track its claimed row ID."""
        pending.append(queue_item)
        if row_id:
            claimed_row_ids.add(row_id)

    def _enqueue_bursty_item(
        self,
        pending: list[_HookOutboxQueueItem],
        claimed_row_ids: set[int],
        queue_item: _HookOutboxQueueItem,
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
        pending: list[_HookOutboxQueueItem],
        claimed_row_ids: set[int],
        queue_item: _HookOutboxQueueItem,
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
        event_type: str,
    ) -> None:
        """Mark coalesced rows as delivered in durable storage."""
        if not dropped_rows:
            return
        self._hook_outbox_coalesced_count += len(dropped_rows)
        for dropped in dropped_rows:
            await db.mark_hook_outbox_delivered(
                dropped["id"],
                error=f"coalesced:{event_type or 'unknown'}",
            )

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
        task = asyncio.create_task(self._run_session_outbox_worker(session_id))
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
        queue_item = _HookOutboxQueueItem(
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

        await self._mark_dropped_outbox_rows(dropped_rows, event_type)

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
            await db.mark_hook_outbox_delivered(row_id, error=str(exc))
            self._hook_outbox_processed_count += 1
            self._record_hook_lag_sample(row)
            return

        try:
            await self._dispatch_hook_event(str(row["session_id"]), str(row["event_type"]), payload)
            await db.mark_hook_outbox_delivered(row_id)
            self._hook_outbox_processed_count += 1
            self._record_hook_lag_sample(row)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            attempt = int(row.get("attempt_count", 0)) + 1
            error_str = str(exc)
            if not self._is_retryable_hook_error(exc):
                logger.error(
                    "Hook outbox event dropped (non-retryable)",
                    row_id=row_id,
                    attempt=attempt,
                    error=error_str,
                )
                await db.mark_hook_outbox_delivered(row_id, error=error_str)
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
