"""Outbound webhook delivery worker."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import httpx
from instrukt_ai_logging import get_logger

from teleclaude.core.db import db

if TYPE_CHECKING:
    from teleclaude.core import db_models

logger = get_logger(__name__)

# Delivery worker configuration
WEBHOOK_POLL_INTERVAL_S = 2.0
WEBHOOK_BATCH_SIZE = 25
WEBHOOK_BASE_BACKOFF_S = 1.0
WEBHOOK_MAX_BACKOFF_S = 60.0
WEBHOOK_DELIVERY_TIMEOUT_S = 10.0


def compute_signature(body: bytes, secret: str) -> str:
    """Compute HMAC-SHA256 signature for webhook payload."""
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def compute_backoff(attempt: int) -> float:
    """Exponential backoff: 1s, 2s, 4s, 8s, 16s, 32s, 60s cap."""
    delay = WEBHOOK_BASE_BACKOFF_S * (2.0 ** max(0, attempt - 1))
    return min(delay, WEBHOOK_MAX_BACKOFF_S)


class WebhookDeliveryWorker:
    """Background worker that delivers webhooks from the outbox."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=WEBHOOK_DELIVERY_TIMEOUT_S)
        return self._client

    async def close(self) -> None:
        """Shut down the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Main delivery loop."""
        try:
            while not shutdown_event.is_set():
                now = datetime.now(timezone.utc)
                now_iso = now.isoformat()
                rows = await db.fetch_webhook_batch(WEBHOOK_BATCH_SIZE, now_iso)

                if not rows:
                    await asyncio.sleep(WEBHOOK_POLL_INTERVAL_S)
                    continue

                for row in rows:
                    if shutdown_event.is_set():
                        break
                    claimed = await db.claim_webhook(row.id, now_iso)
                    if not claimed:
                        continue
                    await self._deliver(row)
        finally:
            await self.close()

    async def _deliver(self, row: db_models.WebhookOutbox) -> None:
        """Deliver a single webhook."""
        row_id = row.id
        if row_id is None:
            return
        body = row.event_json.encode()
        headers = {"Content-Type": "application/json"}

        if row.target_secret:
            headers["X-Hook-Signature"] = compute_signature(body, row.target_secret)

        client = await self._get_client()
        try:
            response = await client.post(row.target_url, content=body, headers=headers)
            if response.status_code < 400:
                await db.mark_webhook_delivered(row_id)
                logger.debug("Webhook delivered: row=%s url=%s", row_id, row.target_url)
            elif response.status_code < 500:
                # 4xx = permanent failure
                await db.mark_webhook_delivered(row_id)
                logger.warning(
                    "Webhook permanent failure (4xx): row=%s status=%s",
                    row_id,
                    response.status_code,
                )
            else:
                # 5xx = transient, retry
                attempt = (row.attempt_count or 0) + 1
                delay = compute_backoff(attempt)
                next_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
                await db.mark_webhook_failed(row_id, f"HTTP {response.status_code}", attempt, next_at)
                logger.warning(
                    "Webhook transient failure: row=%s status=%s retry_in=%.1fs",
                    row_id,
                    response.status_code,
                    delay,
                )
        except httpx.TimeoutException:
            attempt = (row.attempt_count or 0) + 1
            delay = compute_backoff(attempt)
            next_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
            await db.mark_webhook_failed(row_id, "timeout", attempt, next_at)
            logger.warning("Webhook timeout: row=%s retry_in=%.1fs", row_id, delay)
        except Exception as exc:
            attempt = (row.attempt_count or 0) + 1
            delay = compute_backoff(attempt)
            next_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
            await db.mark_webhook_failed(row_id, str(exc), attempt, next_at)
            logger.error("Webhook delivery error: row=%s error=%s", row_id, exc)
