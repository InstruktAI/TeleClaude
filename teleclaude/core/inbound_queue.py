"""Durable inbound message queue for guaranteed delivery.

Adapters enqueue messages and return immediately.
Per-session workers drain the queue with FIFO ordering, CAS claim, and exponential backoff retry.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from instrukt_ai_logging import get_logger

from teleclaude.core.db import InboundQueueRow, db

logger = get_logger(__name__)

# Backoff schedule in seconds: attempt N uses index min(N, last) from this list
_BACKOFF_SCHEDULE = [5, 10, 20, 40, 80, 160, 300]
# Lock timeout: rows locked longer than this are considered stale and reclaimable
_LOCK_TIMEOUT_S = 300  # 5 minutes
# Fetch page size per worker drain tick
_FETCH_LIMIT = 1  # Process one at a time to preserve FIFO ordering

TypingCallback = Callable[[str, str], Awaitable[None]]
DeliverCallback = Callable[[InboundQueueRow], Awaitable[None]]

_manager: Optional[InboundQueueManager] = None


def init_inbound_queue_manager(
    deliver_fn: DeliverCallback,
    *,
    typing_callback: Optional[TypingCallback] = None,
    force: bool = False,
) -> "InboundQueueManager":
    """Initialize the global InboundQueueManager singleton."""
    global _manager
    if _manager is not None and not force:
        raise RuntimeError("InboundQueueManager already initialized")
    _manager = InboundQueueManager(deliver_fn=deliver_fn, typing_callback=typing_callback)
    return _manager


def get_inbound_queue_manager() -> "InboundQueueManager":
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


class InboundQueueManager:
    """Manages per-session worker tasks that drain the inbound queue."""

    def __init__(
        self,
        *,
        deliver_fn: DeliverCallback,
        typing_callback: Optional[TypingCallback] = None,
    ) -> None:
        self._deliver_fn = deliver_fn
        self._typing_callback = typing_callback
        self._workers: dict[str, asyncio.Task[None]] = {}

    async def enqueue(
        self,
        session_id: str,
        origin: str,
        content: str,
        *,
        message_type: str = "text",
        payload_json: str | None = None,
        actor_id: str | None = None,
        actor_name: str | None = None,
        actor_avatar_url: str | None = None,
        source_message_id: str | None = None,
        source_channel_id: str | None = None,
    ) -> int | None:
        """Enqueue a message, fire typing callback, and ensure worker is running.

        Returns the row ID or None if the message was a duplicate.
        """
        row_id = await db.enqueue_inbound(
            session_id=session_id,
            origin=origin,
            content=content,
            message_type=message_type,
            payload_json=payload_json,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_avatar_url=actor_avatar_url,
            source_message_id=source_message_id,
            source_channel_id=source_channel_id,
        )
        if row_id is None:
            logger.debug("Inbound dedup: origin=%s msg_id=%s", origin, source_message_id)
            return None

        if self._typing_callback is not None:
            try:
                await self._typing_callback(session_id, origin)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.debug("Typing callback failed for session %s", session_id[:8], exc_info=True)

        self._ensure_worker(session_id)
        return row_id

    def _ensure_worker(self, session_id: str) -> None:
        """Spawn a drain worker for session_id if one is not already running."""
        existing = self._workers.get(session_id)
        if existing is not None and not existing.done():
            return
        task = asyncio.create_task(
            self._worker_loop(session_id),
            name=f"inbound-worker-{session_id[:8]}",
        )
        self._workers[session_id] = task
        task.add_done_callback(lambda t: self._on_worker_done(session_id, t))

    def _on_worker_done(self, session_id: str, task: asyncio.Task[None]) -> None:
        self._workers.pop(session_id, None)
        if task.exception() is not None:
            logger.warning(
                "Inbound worker for session %s crashed: %s",
                session_id[:8],
                task.exception(),
                exc_info=task.exception(),
            )

    async def _worker_loop(self, session_id: str) -> None:
        """FIFO drain loop for a single session. Self-terminates when queue is empty."""
        logger.debug("Inbound worker starting for session %s", session_id[:8])
        while True:
            now = datetime.now(timezone.utc)
            now_iso = now.isoformat()
            from datetime import timedelta

            lock_cutoff_iso = (now - timedelta(seconds=_LOCK_TIMEOUT_S)).isoformat()

            rows = await db.fetch_inbound_pending(
                session_id=session_id,
                limit=_FETCH_LIMIT,
                now_iso=now_iso,
                lock_cutoff_iso=lock_cutoff_iso,
            )
            if not rows:
                logger.debug("Inbound worker done for session %s (queue empty)", session_id[:8])
                return

            row = rows[0]
            row_id = row["id"]

            claimed = await db.claim_inbound(row_id, now_iso, lock_cutoff_iso)
            if not claimed:
                # Another worker claimed it — shouldn't happen (per-session) but be safe
                logger.debug("Row %d claim failed for session %s; retrying", row_id, session_id[:8])
                await asyncio.sleep(0.1)
                continue

            try:
                await self._deliver_fn(row)
                await db.mark_inbound_delivered(row_id, datetime.now(timezone.utc).isoformat())
                logger.debug("Delivered inbound row %d for session %s", row_id, session_id[:8])
            except Exception as exc:  # pylint: disable=broad-exception-caught
                error_str = str(exc)
                backoff = _backoff_for_attempt(row["attempt_count"])
                logger.warning(
                    "Inbound delivery failed for row %d (attempt=%d, backoff=%.0fs): %s",
                    row_id,
                    row["attempt_count"] + 1,
                    backoff,
                    error_str,
                )
                await db.mark_inbound_failed(
                    row_id,
                    error=error_str,
                    now_iso=datetime.now(timezone.utc).isoformat(),
                    backoff_seconds=backoff,
                )
                # Wait before next iteration to avoid tight retry loops
                await asyncio.sleep(min(backoff, 5.0))

    async def expire_session(self, session_id: str) -> None:
        """Mark all pending messages for a session as expired and cancel the worker."""
        worker = self._workers.pop(session_id, None)
        if worker is not None and not worker.done():
            worker.cancel()
            try:
                await worker
            except (asyncio.CancelledError, Exception):
                pass

        count = await db.expire_inbound_for_session(session_id, datetime.now(timezone.utc).isoformat())
        if count:
            logger.info("Expired %d pending inbound messages for closed session %s", count, session_id[:8])

    async def startup(self) -> None:
        """Scan for pending messages and spawn workers for non-empty sessions."""
        session_ids = await db.fetch_sessions_with_pending_inbound()
        for session_id in session_ids:
            self._ensure_worker(session_id)
        if session_ids:
            logger.info("Inbound queue: resuming workers for %d sessions with pending messages", len(session_ids))

    async def shutdown(self) -> None:
        """Cancel all worker tasks. Messages remain in DB for next startup."""
        tasks = list(self._workers.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._workers.clear()
        logger.info("Inbound queue: all workers shut down (%d tasks cancelled)", len(tasks))
