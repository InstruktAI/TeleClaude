"""Worker loop for notification outbox processing with retry."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.core import db as db_module

from .discovery import build_notification_subscriptions
from .telegram import send_telegram_dm

if TYPE_CHECKING:
    from teleclaude.core.db import Db, NotificationOutboxRow

logger = get_logger(__name__)

MAX_RETRIES = 10


class NotificationOutboxWorker:
    """Background worker for draining notification outbox rows."""

    def __init__(
        self,
        *,
        db: "Db | None" = None,
        shutdown_event: asyncio.Event,
        poll_interval_s: float = 1.0,
        batch_size: int = 25,
        lock_ttl_s: float = 30.0,
        base_backoff_s: float = 1.0,
        max_backoff_s: float = 60.0,
        root: Path | None = None,
    ) -> None:
        self.db = db or db_module.db
        self.shutdown_event = shutdown_event
        self.poll_interval_s = poll_interval_s
        self.batch_size = batch_size
        self.lock_ttl_s = lock_ttl_s
        self.base_backoff_s = base_backoff_s
        self.max_backoff_s = max_backoff_s
        self.root = root
        self._recipient_cache: dict[str, str] = {}
        self._recipient_cache_dirty = True

    @staticmethod
    def _backoff_seconds(attempt: int) -> float:
        """Exponential backoff with upper cap."""
        base = 1 << max(0, attempt - 1)
        delay = float(base)
        return delay

    def _build_backoff(self, attempt: int) -> float:
        delay = self._backoff_seconds(attempt) * self.base_backoff_s
        return min(self.max_backoff_s, delay)

    def _recipient_for_email(self, email: str) -> str | None:
        if self._recipient_cache_dirty:
            index = build_notification_subscriptions(self.root)
            self._recipient_cache = {
                recipient.email: recipient.telegram_chat_id
                for channel in index.by_channel
                for recipient in index.for_channel(channel)
            }
            self._recipient_cache_dirty = False
        return self._recipient_cache.get(email)

    async def run(self) -> None:
        """Run continuously until shutdown event is set."""
        while not self.shutdown_event.is_set():
            try:
                await self._process_once()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.exception("notification worker failed", error=str(exc))
                await self._sleep(self.poll_interval_s)

    async def _process_once(self) -> None:
        """Process one poll cycle."""
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        lock_cutoff = (now - timedelta(seconds=self.lock_ttl_s)).isoformat()

        rows = await self.db.fetch_notification_batch(
            now_iso,
            self.batch_size,
            lock_cutoff,
            max_attempts=MAX_RETRIES,
        )
        if not rows:
            await self._sleep(self.poll_interval_s)
            return

        for row in rows:
            if self.shutdown_event.is_set():
                return

            row_id = row["id"]
            claimed = await self.db.claim_notification(row_id, now_iso, lock_cutoff)
            if not claimed:
                continue

            try:
                await self._deliver_row(row)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error("notification row delivery failed outside lifecycle", row_id=row_id, error=str(exc))

    async def _deliver_row(self, row: "NotificationOutboxRow") -> None:
        """Deliver one outbox row with retry bookkeeping."""
        row_id = row["id"]
        email = str(row["recipient_email"])
        content = str(row["content"] or "")
        file_path = row.get("file_path")
        file_path_value = str(file_path) if file_path else None

        chat_id = self._recipient_for_email(email)
        if not chat_id:
            logger.warning("undeliverable notification; no chat_id configured", row_id=row_id, email=email)
            await self.db.mark_notification_failed(
                row_id,
                MAX_RETRIES,
                "",
                "No telegram_chat_id configured for recipient",
            )
            return

        try:
            await send_telegram_dm(chat_id=chat_id, content=content, file=file_path_value)
        except Exception as exc:
            attempt = int(row.get("attempt_count", 0)) + 1
            if attempt >= MAX_RETRIES:
                logger.error(
                    "notification permanently failed after max retries",
                    row_id=row_id,
                    attempt=attempt,
                    error=str(exc),
                )
                await self.db.mark_notification_failed(row_id, attempt, "", str(exc))
                return
            next_attempt = (datetime.now(timezone.utc) + timedelta(seconds=self._build_backoff(attempt))).isoformat()
            logger.warning(
                "notification delivery failed; retrying",
                row_id=row_id,
                attempt=attempt,
                error=str(exc),
                next_attempt=next_attempt,
            )
            await self.db.mark_notification_failed(row_id, attempt, next_attempt, str(exc))
            return

        try:
            await self.db.mark_notification_delivered(row_id)
        except Exception as exc:
            logger.error(
                "notification sent but DB update failed; skipping retry to avoid duplicate",
                row_id=row_id,
                error=str(exc),
            )

    async def _sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        await asyncio.sleep(seconds)
