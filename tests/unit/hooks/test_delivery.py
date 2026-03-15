"""Characterization tests for teleclaude.hooks.delivery."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

import teleclaude.hooks.delivery as delivery_module
from teleclaude.hooks.delivery import (
    WEBHOOK_POLL_INTERVAL_S,
    WebhookDeliveryWorker,
    compute_backoff,
    compute_signature,
)


def _make_row(**overrides: object) -> SimpleNamespace:
    data = {
        "id": 1,
        "contract_id": "contract-1",
        "event_json": '{"source":"github"}',
        "target_url": "https://example.test/hook",
        "target_secret": None,
        "attempt_count": 0,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class TestDeliveryHelpers:
    @pytest.mark.unit
    def test_compute_signature_returns_sha256_prefixed_hmac(self) -> None:
        assert compute_signature(b"payload", "secret") == (
            "sha256=b82fcb791acec57859b989b430a826488ce2e479fdf92326bd0a2e8375a42ba4"
        )

    @pytest.mark.unit
    def test_compute_backoff_doubles_then_caps_at_sixty_seconds(self) -> None:
        assert compute_backoff(1) == 1.0
        assert compute_backoff(4) == 8.0
        assert compute_backoff(10) == 60.0


class TestWebhookDeliveryWorker:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_run_delivers_claimed_rows_and_signs_secret_headers(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        shutdown_event = asyncio.Event()
        row = _make_row(target_secret="top-secret")
        db_stub = SimpleNamespace(
            fetch_webhook_batch=AsyncMock(return_value=[row]),
            claim_webhook=AsyncMock(return_value=True),
            mark_webhook_delivered=AsyncMock(side_effect=lambda _row_id: shutdown_event.set()),
            mark_webhook_failed=AsyncMock(),
        )
        client = SimpleNamespace(
            post=AsyncMock(return_value=SimpleNamespace(status_code=202)),
            aclose=AsyncMock(),
        )
        monkeypatch.setattr(delivery_module, "db", db_stub)

        worker = WebhookDeliveryWorker()
        worker._client = client

        await worker.run(shutdown_event)

        _, kwargs = client.post.await_args
        assert kwargs["headers"]["X-Hook-Signature"] == compute_signature(row.event_json.encode(), "top-secret")
        db_stub.mark_webhook_delivered.assert_awaited_once_with(1)
        client.aclose.assert_awaited_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_run_marks_http_4xx_responses_as_rejected_without_retry(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        shutdown_event = asyncio.Event()
        row = _make_row(id=2, attempt_count=1)
        db_stub = SimpleNamespace(
            fetch_webhook_batch=AsyncMock(return_value=[row]),
            claim_webhook=AsyncMock(return_value=True),
            mark_webhook_delivered=AsyncMock(),
            mark_webhook_failed=AsyncMock(side_effect=lambda *_args, **_kwargs: shutdown_event.set()),
        )
        client = SimpleNamespace(
            post=AsyncMock(return_value=SimpleNamespace(status_code=410)),
            aclose=AsyncMock(),
        )
        monkeypatch.setattr(delivery_module, "db", db_stub)

        worker = WebhookDeliveryWorker()
        worker._client = client

        await worker.run(shutdown_event)

        db_stub.mark_webhook_failed.assert_awaited_once_with(2, "HTTP 410", 2, None, status="rejected")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_run_marks_timeouts_for_retry_with_a_next_attempt_timestamp(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        shutdown_event = asyncio.Event()
        row = _make_row(id=3)
        db_stub = SimpleNamespace(
            fetch_webhook_batch=AsyncMock(return_value=[row]),
            claim_webhook=AsyncMock(return_value=True),
            mark_webhook_delivered=AsyncMock(),
            mark_webhook_failed=AsyncMock(side_effect=lambda *_args, **_kwargs: shutdown_event.set()),
        )
        client = SimpleNamespace(
            post=AsyncMock(side_effect=httpx.TimeoutException("timed out")),
            aclose=AsyncMock(),
        )
        monkeypatch.setattr(delivery_module, "db", db_stub)

        worker = WebhookDeliveryWorker()
        worker._client = client

        await worker.run(shutdown_event)

        args, kwargs = db_stub.mark_webhook_failed.await_args
        assert args[:3] == (3, "timeout", 1)
        assert isinstance(args[3], str)
        assert kwargs == {}

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_run_sleeps_for_the_poll_interval_when_the_outbox_is_empty(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        shutdown_event = asyncio.Event()
        db_stub = SimpleNamespace(
            fetch_webhook_batch=AsyncMock(return_value=[]),
            claim_webhook=AsyncMock(),
            mark_webhook_delivered=AsyncMock(),
            mark_webhook_failed=AsyncMock(),
        )
        sleep_calls: list[float] = []

        async def _sleep(delay: float) -> None:
            sleep_calls.append(delay)
            shutdown_event.set()

        monkeypatch.setattr(delivery_module, "db", db_stub)
        monkeypatch.setattr(delivery_module.asyncio, "sleep", _sleep)

        worker = WebhookDeliveryWorker()
        client = SimpleNamespace(aclose=AsyncMock())
        worker._client = client

        await worker.run(shutdown_event)

        assert sleep_calls == [WEBHOOK_POLL_INTERVAL_S]
        client.aclose.assert_awaited_once()
