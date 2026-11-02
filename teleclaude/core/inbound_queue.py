"""Durable inbound message queue for guaranteed delivery.

Adapters enqueue messages and return immediately.
Per-session workers drain the queue with FIFO ordering, CAS claim, and exponential backoff retry.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from instrukt_ai_logging import get_logger

from teleclaude.core.dates import parse_iso_datetime
from teleclaude.core.db import InboundQueueRow, db
from teleclaude.core.inbound_errors import InboundMessageHeldError, SessionMessageRejectedError
from teleclaude.core.inbound_types import InboundMessageType
from teleclaude.core.injected_text import (
    InjectedInputAuthority,
    InjectedTextSourceFeature,
    TranscriptEntryKind,
    authority_for_source_feature,
)
from teleclaude.core.models import MessageAuthor
from teleclaude.core.origins import InputOrigin
from teleclaude.core.shutdown_drain import get_shutdown_drain

logger = get_logger(__name__)

_INBOUND_DEDUP_EVENT = "inbound_dedup_skipped"
_INBOUND_ENQUEUE_WORK = "inbound-enqueue"
_INBOUND_DELIVERY_WORK = "inbound-delivery"
_NO_WAIT_S = 0.0
_CLAIM_LOST_PAUSE_S = 0.1
_INBOUND_ACCEPTED_EVENT = "inbound_text_accepted"
_INBOUND_DELIVERY_COMMITTED_EVENT = "inbound_text_delivery_committed"
_SESSION_TEXT_DELIVERY_REQUESTED_EVENT = "session_text_delivery_requested"
_TYPING_CALLBACK_FAILED_EVENT = "inbound_typing_callback_failed"
_WORKER_CRASHED_EVENT = "inbound_worker_crashed"
_WORKER_STARTING_EVENT = "inbound_worker_starting"
_WORKER_DONE_EVENT = "inbound_worker_done"
_ROW_CLAIM_FAILED_EVENT = "inbound_row_claim_failed"
_WORKER_CLAIM_ERRORED_EVENT = "inbound_worker_claim_errored"
_WORKER_DELIVERY_ERRORED_EVENT = "inbound_worker_delivery_errored"
_ROW_DELIVERED_EVENT = "inbound_row_delivered"
_ROW_EXPIRED_EVENT = "inbound_row_expired"
_ROW_HOLD_NOTICE_FAILED_EVENT = "inbound_hold_expiry_notice_failed"
_ROW_HOLD_NOTICE_UNADDRESSABLE_EVENT = "inbound_hold_expiry_notice_unaddressable"
_ROW_DELIVERY_FAILED_EVENT = "inbound_row_delivery_failed"
_ROW_DELIVERY_HELD_EVENT = "inbound_row_delivery_held"
_SESSION_EXPIRED_EVENT = "inbound_session_expired"
_WORKERS_RESUMED_EVENT = "inbound_workers_resumed"
_WORKERS_SHUTDOWN_EVENT = "inbound_workers_shutdown"

# Backoff schedule in seconds: attempt N uses index min(N, last) from this list
_BACKOFF_SCHEDULE = [5, 10, 20, 40, 80, 160, 300]
_MAX_DELIVERY_ATTEMPTS = len(_BACKOFF_SCHEDULE) + 1
_HELD_MESSAGE_TIMEOUT_S = float(sum(_BACKOFF_SCHEDULE))
_HELD_MESSAGE_EXPIRED_REASON = "hold_expired"
_INVALID_HELD_MESSAGE_CREATED_AT_ERROR = "Invalid inbound message created_at timestamp: {created_at}"
_INVALID_HOLD_NOTICE_RETRY_TIME_ERROR = "Invalid persisted hold-notice retry timestamp"
_HOLD_NOTICE_CALLBACK_UNAVAILABLE_ERROR = "Hold-expiry notice callback is unavailable"
_HOLD_NOTICE_FAILED_ERROR = "hold_expiry_notice_failed"
_DELIVERY_EXHAUSTED_CALLBACK_FAILED_EVENT = "inbound_delivery_exhausted_callback_failed"
_CONVERSATION_UI_ORIGINS = frozenset({InputOrigin.DISCORD, InputOrigin.TELEGRAM, InputOrigin.WHATSAPP})
# Lock timeout: rows locked longer than this are considered stale and reclaimable
_LOCK_TIMEOUT_S = 300  # 5 minutes
# Fetch page size per worker drain tick
_FETCH_LIMIT = 1  # Process one at a time to preserve FIFO ordering

TypingCallback = Callable[[str, str], Awaitable[None]]
DeliverCallback = Callable[[InboundQueueRow], Awaitable[None]]


class DeliveryTerminalCause(StrEnum):
    """Closed causes for terminal inbound delivery notifications."""

    RETRY_EXHAUSTED = "retry_exhausted"
    HOLD_EXPIRED = _HELD_MESSAGE_EXPIRED_REASON
    REJECTED = "rejected"


class HoldNoticeTerminalDisposition(StrEnum):
    """Closed terminal outcomes for a held-message channel notice."""

    RECIPIENT_UNAVAILABLE = "recipient_unavailable"


class HoldNoticeRecipientUnavailableError(Exception):
    """The accepted conversation no longer has an addressable UI recipient."""


DeliveryExhaustedCallback = Callable[[InboundQueueRow, DeliveryTerminalCause], Awaitable[None]]
PostInsertCallback = Callable[[int], Awaitable[None]]

_manager: InboundQueueManager | None = None


def init_inbound_queue_manager(
    deliver_fn: DeliverCallback,
    *,
    typing_callback: TypingCallback | None = None,
    delivery_exhausted_callback: DeliveryExhaustedCallback | None = None,
    force: bool = False,
) -> InboundQueueManager:
    """Initialize the global InboundQueueManager singleton."""
    global _manager
    if _manager is not None and not force:
        raise RuntimeError("InboundQueueManager already initialized")
    _manager = InboundQueueManager(
        deliver_fn=deliver_fn,
        typing_callback=typing_callback,
        delivery_exhausted_callback=delivery_exhausted_callback,
    )
    return _manager


def get_inbound_queue_manager() -> InboundQueueManager:
    """Return the global InboundQueueManager singleton."""
    if _manager is None:
        raise RuntimeError("InboundQueueManager not initialized")
    return _manager


def reset_inbound_queue_manager() -> None:
    """Reset the singleton (tests only)."""
    global _manager
    _manager = None


def _backoff_for_attempt(attempt: int) -> float:
    idx = min(attempt, len(_BACKOFF_SCHEDULE) - 1)
    return float(_BACKOFF_SCHEDULE[idx])


def _held_message_seconds_remaining(created_at: str, now: datetime) -> float:
    """Return the non-negative time before an accepted held message expires."""
    accepted_at = parse_iso_datetime(created_at)
    if accepted_at is None:
        raise ValueError(_INVALID_HELD_MESSAGE_CREATED_AT_ERROR.format(created_at=created_at))
    deadline = accepted_at + timedelta(seconds=_HELD_MESSAGE_TIMEOUT_S)
    return max(0.0, (deadline - now).total_seconds())


def _hold_notice_seconds_until_retry(row: InboundQueueRow, now: datetime, lock_cutoff: datetime) -> float:
    """Return when a persisted hold notice can be claimed again."""
    retry_at_text = row["hold_notice_next_retry_at"]
    retry_at = parse_iso_datetime(retry_at_text) if retry_at_text is not None else now
    if retry_at is None:
        raise ValueError(_INVALID_HOLD_NOTICE_RETRY_TIME_ERROR)
    locked_at_text = row["locked_at"]
    if locked_at_text is not None:
        locked_at = parse_iso_datetime(locked_at_text)
        if locked_at is None:
            raise ValueError(_INVALID_HOLD_NOTICE_RETRY_TIME_ERROR)
        if locked_at > lock_cutoff:
            retry_at = max(retry_at, locked_at + timedelta(seconds=_LOCK_TIMEOUT_S))
    return max(0.0, (retry_at - now).total_seconds())


def _row_authority(row: InboundQueueRow) -> InjectedInputAuthority:
    """Return the input authority recorded by the row's producer."""
    return authority_for_source_feature(InjectedTextSourceFeature(row["source_feature"]))


def _hold_notice_is_required(row: InboundQueueRow) -> bool:
    """Return whether this expired occurrence has a conversation UI recipient."""
    origin = InputOrigin(row["origin"])
    return _row_authority(row) is InjectedInputAuthority.CONVERSATION and origin in _CONVERSATION_UI_ORIGINS


@dataclass(frozen=True)
class _ClaimStep:
    """What one claim attempt yielded: a claimed row, a pause before the next attempt, or the end of the queue."""

    row: InboundQueueRow | None = None
    pause_s: float = 0.0
    finished: bool = False


class InboundQueueManager:
    """Manages per-session worker tasks that drain the inbound queue."""

    def __init__(
        self,
        *,
        deliver_fn: DeliverCallback,
        typing_callback: TypingCallback | None = None,
        delivery_exhausted_callback: DeliveryExhaustedCallback | None = None,
    ) -> None:
        self._deliver_fn = deliver_fn
        self._typing_callback = typing_callback
        self._delivery_exhausted_callback = delivery_exhausted_callback
        self._workers: dict[str, asyncio.Task[None]] = {}

    async def enqueue(
        self,
        session_id: str,
        origin: str,
        content: str,
        *,
        message_type: str = InboundMessageType.TEXT.value,
        text_kind: TranscriptEntryKind,
        source_feature: InjectedTextSourceFeature,
        occurrence_key: str | None,
        payload_json: str | None = None,
        actor_id: str | None = None,
        actor_name: str | None = None,
        actor_avatar_url: str | None = None,
        source_message_id: str | None = None,
        source_channel_id: str | None = None,
        caller_session_id: str | None = None,
        caller_author: MessageAuthor | None = None,
        caller_job_role: str | None = None,
        caller_origin_prefix_len: int | None = None,
        caller_origin_suffix_len: int | None = None,
        notify_typing: bool = True,
        post_insert_callback: PostInsertCallback | None = None,
    ) -> int | None:
        """Enqueue a message, fire typing callback, and ensure worker is running.

        Returns the row ID or None if the message was a duplicate.

        ``caller_session_id``/``caller_author``/``caller_job_role`` carry the
        resolved originating-session identity when the sender is itself
        another session (e.g. a plain ``telec sessions send``), so it is
        durable on the accepted row before any transcript binding exists.

        Raises ``ShutdownRefusal`` while the daemon drains, before any accepted
        state is recorded.
        """
        get_shutdown_drain().check_admission(_INBOUND_ENQUEUE_WORK)
        logger.info(
            _SESSION_TEXT_DELIVERY_REQUESTED_EVENT,
            source_feature=source_feature.value,
            target_session_id=session_id,
            occurrence_key=occurrence_key,
            text_kind=text_kind.value,
        )
        row_id = await db.enqueue_inbound(
            session_id=session_id,
            origin=origin,
            content=content,
            message_type=message_type,
            text_kind=text_kind,
            source_feature=source_feature,
            occurrence_key=occurrence_key,
            payload_json=payload_json,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_avatar_url=actor_avatar_url,
            source_message_id=source_message_id or occurrence_key,
            source_channel_id=source_channel_id,
            caller_session_id=caller_session_id,
            caller_author=caller_author,
            caller_job_role=caller_job_role,
            caller_origin_prefix_len=caller_origin_prefix_len,
            caller_origin_suffix_len=caller_origin_suffix_len,
        )
        if row_id is None:
            logger.debug(
                _INBOUND_DEDUP_EVENT,
                session_id=session_id,
                origin=origin,
                source_message_id=source_message_id,
            )
            return None

        logger.info(
            _INBOUND_ACCEPTED_EVENT,
            inbound_row_id=row_id,
            session_id=session_id,
            origin=origin,
            source_feature=source_feature.value,
            occurrence_key=occurrence_key,
            text_kind=text_kind.value,
        )

        if post_insert_callback is not None:
            await post_insert_callback(row_id)

        if notify_typing and self._typing_callback is not None:
            try:
                await self._typing_callback(session_id, origin)
            except Exception as exc:
                logger.debug(
                    _TYPING_CALLBACK_FAILED_EVENT,
                    session_id=session_id,
                    error=str(exc),
                    exc_info=True,
                )

        self._ensure_worker(session_id)
        return row_id

    def _ensure_worker(self, session_id: str) -> None:
        """Spawn a drain worker for session_id if one is not already running."""
        existing = self._workers.get(session_id)
        if existing is not None and not existing.done():
            return
        task = asyncio.create_task(
            self._worker_loop(session_id),
            name=f"inbound-worker-{session_id}",
        )
        self._workers[session_id] = task
        task.add_done_callback(lambda t: self._on_worker_done(session_id, t))

    def _on_worker_done(self, session_id: str, task: asyncio.Task[None]) -> None:
        self._workers.pop(session_id, None)
        if not task.cancelled() and task.exception() is not None:
            logger.warning(
                _WORKER_CRASHED_EVENT,
                session_id=session_id,
                error=str(task.exception()),
                exc_info=task.exception(),
            )

    async def _process_pending_hold_notice(
        self,
        session_id: str,
        now: datetime,
        lock_cutoff: datetime,
    ) -> tuple[bool, float | None]:
        """Deliver one due terminal notice or return its next retry delay."""
        notices = await db.fetch_inbound_hold_notices(session_id)
        if not notices:
            return False, None
        retry_delays = [_hold_notice_seconds_until_retry(notice, now, lock_cutoff) for notice in notices]
        due_index = next((index for index, delay in enumerate(retry_delays) if delay <= 0), None)
        if due_index is None:
            return False, min(retry_delays)
        notice = notices[due_index]

        claimed = await db.claim_inbound_hold_notice(
            notice["id"],
            now_iso=now.isoformat(),
            lock_cutoff_iso=lock_cutoff.isoformat(),
        )
        if not claimed:
            return False, 0.1
        try:
            if self._delivery_exhausted_callback is None:
                raise RuntimeError(_HOLD_NOTICE_CALLBACK_UNAVAILABLE_ERROR)
            await self._delivery_exhausted_callback(notice, DeliveryTerminalCause.HOLD_EXPIRED)
        except HoldNoticeRecipientUnavailableError:
            await db.mark_inbound_hold_notice_unaddressable(
                notice["id"],
                HoldNoticeTerminalDisposition.RECIPIENT_UNAVAILABLE,
            )
            logger.warning(
                _ROW_HOLD_NOTICE_UNADDRESSABLE_EVENT,
                session_id=session_id,
                inbound_row_id=notice["id"],
                disposition=HoldNoticeTerminalDisposition.RECIPIENT_UNAVAILABLE,
            )
        except Exception as notice_exc:
            backoff = _backoff_for_attempt(notice["hold_notice_attempt_count"])
            failed_at = datetime.now(UTC)
            await db.mark_inbound_hold_notice_failed(
                notice["id"],
                error=_HOLD_NOTICE_FAILED_ERROR,
                now_iso=failed_at.isoformat(),
                backoff_seconds=backoff,
            )
            logger.warning(
                _ROW_HOLD_NOTICE_FAILED_EVENT,
                session_id=session_id,
                inbound_row_id=notice["id"],
                attempt=notice["hold_notice_attempt_count"] + 1,
                backoff_seconds=backoff,
                error_type=type(notice_exc).__name__,
            )
        else:
            await db.mark_inbound_hold_notice_delivered(notice["id"])
        return True, None

    async def _worker_loop(self, session_id: str) -> None:
        """FIFO drain loop for a single session. Self-terminates when queue is empty."""
        logger.debug(_WORKER_STARTING_EVENT, session_id=session_id)
        drain = get_shutdown_drain()
        while True:
            if not drain.is_open:
                # Unclaimed rows stay pending for the next process.
                logger.debug(_WORKER_DONE_EVENT, session_id=session_id)
                return
            # Registered with no await after the open check, so settlement cannot observe
            # zero units between deciding to claim and owning the claim.
            unit = drain.register(_INBOUND_DELIVERY_WORK)
            try:
                try:
                    step = await self._claim_next_row(session_id)
                except BaseException:
                    unit.release()
                    raise
            except Exception:
                logger.exception(_WORKER_CLAIM_ERRORED_EVENT, session_id=session_id)
                await asyncio.sleep(_backoff_for_attempt(0))
                continue
            if step.row is None:
                unit.release()
                if step.finished:
                    logger.debug(_WORKER_DONE_EVENT, session_id=session_id)
                    return
                if step.pause_s > _NO_WAIT_S:
                    await asyncio.sleep(step.pause_s)
                continue
            try:
                wait_s = await unit.carry(self._deliver_claimed_row(step.row, session_id))
            except Exception:
                logger.exception(_WORKER_DELIVERY_ERRORED_EVENT, session_id=session_id, inbound_row_id=step.row["id"])
                wait_s = _backoff_for_attempt(0)
            if wait_s > _NO_WAIT_S:
                await asyncio.sleep(wait_s)

    async def _claim_next_row(self, session_id: str) -> _ClaimStep:
        """Process a pending hold notice or claim the session's next row; the caller holds the claim's unit."""
        now = datetime.now(UTC)
        now_iso = now.isoformat()
        lock_cutoff = now - timedelta(seconds=_LOCK_TIMEOUT_S)
        lock_cutoff_iso = lock_cutoff.isoformat()
        notice_processed, notice_retry_delay = await self._process_pending_hold_notice(session_id, now, lock_cutoff)
        if notice_processed:
            return _ClaimStep()

        rows = await db.fetch_inbound_pending(
            session_id=session_id,
            limit=_FETCH_LIMIT,
            now_iso=now_iso,
            lock_cutoff_iso=lock_cutoff_iso,
        )
        if not rows:
            if notice_retry_delay is not None:
                return _ClaimStep(pause_s=max(notice_retry_delay, 0.1))
            return _ClaimStep(finished=True)

        row = rows[0]
        claimed = await db.claim_inbound(row["id"], now_iso, lock_cutoff_iso)
        if not claimed:
            # Another worker claimed it — shouldn't happen (per-session) but be safe
            logger.debug(_ROW_CLAIM_FAILED_EVENT, session_id=session_id, inbound_row_id=row["id"])
            return _ClaimStep(pause_s=_CLAIM_LOST_PAUSE_S)
        return _ClaimStep(row=row)

    async def _deliver_claimed_row(self, row: InboundQueueRow, session_id: str) -> float:
        """Deliver one claimed row and record its outcome; the caller holds the row's owned unit.

        Returns the seconds the worker waits before its next row, spent after the unit has settled.
        """
        row_id = row["id"]
        if row["was_held"] and _held_message_seconds_remaining(row["created_at"], datetime.now(UTC)) <= 0:
            await self._expire_held_message(row)
            return _NO_WAIT_S

        try:
            await self._deliver_fn(row)
            await db.mark_inbound_delivered(row_id, datetime.now(UTC).isoformat())
            logger.info(
                _INBOUND_DELIVERY_COMMITTED_EVENT,
                outcome="delivered",
                inbound_row_id=row_id,
                target_session_id=session_id,
                occurrence_key=row["occurrence_key"],
                source_feature=row["source_feature"],
                text_kind=row["text_kind"],
            )
            logger.debug(_ROW_DELIVERED_EVENT, session_id=session_id, inbound_row_id=row_id)
        except InboundMessageHeldError as exc:
            backoff = _backoff_for_attempt(row["attempt_count"])
            retry_at = datetime.now(UTC)
            remaining = _held_message_seconds_remaining(row["created_at"], retry_at)
            if remaining <= 0:
                await self._expire_held_message(row)
                return _NO_WAIT_S
            backoff = min(backoff, remaining)
            await db.mark_inbound_held(
                row_id,
                now_iso=retry_at.isoformat(),
                backoff_seconds=backoff,
                reason=exc.reason,
            )
            logger.info(
                _ROW_DELIVERY_HELD_EVENT,
                session_id=session_id,
                inbound_row_id=row_id,
                backoff_seconds=backoff,
                reason=exc.reason.value,
            )
            remaining = _held_message_seconds_remaining(row["created_at"], datetime.now(UTC))
            return min(backoff, remaining)
        except SessionMessageRejectedError as exc:
            error_str = str(exc)
            await db.mark_inbound_expired(
                row_id,
                error=error_str,
                now_iso=datetime.now(UTC).isoformat(),
            )
            logger.info(
                _ROW_EXPIRED_EVENT,
                session_id=session_id,
                inbound_row_id=row_id,
                error=error_str,
            )
            logger.info(
                _INBOUND_DELIVERY_COMMITTED_EVENT,
                outcome="failed",
                reason="rejected",
                inbound_row_id=row_id,
                target_session_id=session_id,
                occurrence_key=row["occurrence_key"],
                source_feature=row["source_feature"],
                text_kind=row["text_kind"],
            )
            await self._notify_terminal_cause(row, DeliveryTerminalCause.REJECTED)
        except Exception as exc:
            error_str = str(exc)
            attempt = row["attempt_count"] + 1
            if attempt >= _MAX_DELIVERY_ATTEMPTS:
                await db.mark_inbound_retry_exhausted(
                    row_id,
                    error=error_str,
                    now_iso=datetime.now(UTC).isoformat(),
                )
                logger.info(
                    _INBOUND_DELIVERY_COMMITTED_EVENT,
                    outcome="failed",
                    reason="retry_exhausted",
                    inbound_row_id=row_id,
                    target_session_id=session_id,
                    occurrence_key=row["occurrence_key"],
                    source_feature=row["source_feature"],
                    text_kind=row["text_kind"],
                    attempts=attempt,
                )
                await self._notify_terminal_cause(row, DeliveryTerminalCause.RETRY_EXHAUSTED)
                return _NO_WAIT_S
            backoff = _backoff_for_attempt(row["attempt_count"])
            retry_at: datetime | None = None
            if row["was_held"]:
                retry_at = datetime.now(UTC)
                remaining = _held_message_seconds_remaining(row["created_at"], retry_at)
                if remaining <= 0:
                    await self._expire_held_message(row)
                    return _NO_WAIT_S
                backoff = min(backoff, remaining)
            logger.warning(
                _ROW_DELIVERY_FAILED_EVENT,
                session_id=session_id,
                inbound_row_id=row_id,
                attempt=attempt,
                backoff_seconds=backoff,
                error=error_str,
            )
            await db.mark_inbound_failed(
                row_id,
                error=error_str,
                now_iso=(retry_at or datetime.now(UTC)).isoformat(),
                backoff_seconds=backoff,
            )
            # Wait before next iteration to avoid tight retry loops
            if row["was_held"]:
                remaining = _held_message_seconds_remaining(row["created_at"], datetime.now(UTC))
                return min(backoff, remaining)
            return backoff
        return _NO_WAIT_S

    async def _notify_terminal_cause(self, row: InboundQueueRow, cause: DeliveryTerminalCause) -> None:
        """Hand a row's terminal cause to the producer-notice callback, best-effort."""
        if self._delivery_exhausted_callback is None:
            return
        try:
            await self._delivery_exhausted_callback(row, cause)
        except Exception as callback_exc:
            logger.warning(
                _DELIVERY_EXHAUSTED_CALLBACK_FAILED_EVENT,
                session_id=row["session_id"],
                inbound_row_id=row["id"],
                error=str(callback_exc),
            )

    async def _expire_held_message(self, row: InboundQueueRow) -> None:
        """End a held message at its deadline and surface its terminal cause.

        A conversation row's notice is persisted with the row and delivered by
        the worker's notice pass. A platform-authored row has no such channel;
        its producer hears through the same callback retry exhaustion uses.
        """
        now_iso = datetime.now(UTC).isoformat()
        await db.mark_inbound_expired(
            row["id"],
            error=_HELD_MESSAGE_EXPIRED_REASON,
            now_iso=now_iso,
            hold_notice_pending=_hold_notice_is_required(row),
        )
        logger.info(
            _ROW_EXPIRED_EVENT,
            session_id=row["session_id"],
            inbound_row_id=row["id"],
            error=_HELD_MESSAGE_EXPIRED_REASON,
        )
        logger.info(
            _INBOUND_DELIVERY_COMMITTED_EVENT,
            outcome="failed",
            reason=_HELD_MESSAGE_EXPIRED_REASON,
            inbound_row_id=row["id"],
            target_session_id=row["session_id"],
            occurrence_key=row["occurrence_key"],
            source_feature=row["source_feature"],
            text_kind=row["text_kind"],
        )
        if _row_authority(row) is not InjectedInputAuthority.CONVERSATION:
            await self._notify_terminal_cause(row, DeliveryTerminalCause.HOLD_EXPIRED)

    async def expire_session(self, session_id: str) -> None:
        """Mark all pending messages for a session as expired and cancel the worker."""
        worker = self._workers.pop(session_id, None)
        if worker is not None and not worker.done():
            worker.cancel()
            try:
                await worker
            except (asyncio.CancelledError, Exception):
                pass

        count = await db.expire_inbound_for_session(session_id, datetime.now(UTC).isoformat())
        if count:
            logger.info(_SESSION_EXPIRED_EVENT, session_id=session_id, expired_count=count)
        if await db.fetch_inbound_hold_notices(session_id):
            self._ensure_worker(session_id)

    async def startup(self) -> None:
        """Scan for pending messages and spawn workers for non-empty sessions."""
        session_ids = await db.fetch_sessions_with_pending_inbound()
        for session_id in session_ids:
            self._ensure_worker(session_id)
        if session_ids:
            logger.info(_WORKERS_RESUMED_EVENT, session_count=len(session_ids))

    async def shutdown(self) -> None:
        """Cancel all worker tasks. Messages remain in DB for next startup."""
        tasks = list(self._workers.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._workers.clear()
        logger.info(_WORKERS_SHUTDOWN_EVENT, task_count=len(tasks))
