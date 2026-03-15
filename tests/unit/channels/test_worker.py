"""Characterization tests for teleclaude.channels.worker."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from unittest.mock import AsyncMock, call, patch

import pytest

import teleclaude.channels.worker as worker
from teleclaude.config.schema import ChannelSubscription


class FakeLogger:
    def __init__(self) -> None:
        self.records: list[tuple[str, str, tuple[object, ...], Mapping[str, object]]] = []

    def info(self, message: str, *args: object, **kwargs: object) -> None:
        self.records.append(("info", message, args, dict(kwargs)))

    def debug(self, message: str, *args: object, **kwargs: object) -> None:
        self.records.append(("debug", message, args, dict(kwargs)))

    def warning(self, message: str, *args: object, **kwargs: object) -> None:
        self.records.append(("warning", message, args, dict(kwargs)))


class TestDispatchToTarget:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_notification_target_uses_defaults_and_summary_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        logger = FakeLogger()
        monkeypatch.setattr(worker, "logger", logger)

        await worker._dispatch_to_target({}, {"summary": "Deployment ready"})

        assert logger.records == [
            (
                "info",
                "Channel dispatch -> notification (delivery via event platform)",
                (),
                {"notification_channel": "telegram", "message_preview": "Deployment ready"},
            )
        ]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_command_target_logs_intent_without_execution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        logger = FakeLogger()
        monkeypatch.setattr(worker, "logger", logger)

        await worker._dispatch_to_target(
            {"type": "command", "project": "demo", "command": "next-build"},
            {"message": "ignored"},
        )

        assert logger.records == [
            (
                "info",
                "Channel dispatch -> command",
                (),
                {"project": "demo", "command": "next-build"},
            ),
            (
                "debug",
                "Command dispatch not yet wired",
                (),
                {"target": {"type": "command", "project": "demo", "command": "next-build"}},
            ),
        ]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_unknown_target_type_logs_warning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        logger = FakeLogger()
        monkeypatch.setattr(worker, "logger", logger)

        await worker._dispatch_to_target({"type": "mirror"}, {"message": "ignored"})

        assert logger.records == [("warning", "Unknown subscription target type: %s", ("mirror",), {})]


class TestMatchesFilter:
    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("msg_filter", "payload", "expected"),
        [
            (None, {"kind": "deploy"}, True),
            ({}, {"kind": "deploy"}, True),
            ({"kind": "deploy"}, {"kind": "deploy", "status": "ok"}, True),
            ({"kind": "deploy"}, {"kind": "alert"}, False),
        ],
    )
    def test_matches_filter_contract(
        self,
        msg_filter: Mapping[str, object] | None,
        payload: Mapping[str, object],
        expected: bool,
    ) -> None:
        assert worker._matches_filter(msg_filter, payload) is expected


class TestRunSubscriptionWorker:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_returns_immediately_when_no_subscriptions(self) -> None:
        await worker.run_subscription_worker(object(), [])

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_creates_groups_and_dispatches_only_matching_messages(self) -> None:
        redis = object()
        shutdown_event = asyncio.Event()
        subscriptions = [
            ChannelSubscription(
                channel="channel:demo:events",
                filter={"kind": "deploy"},
                target={"type": "notification", "channel": "telegram"},
            ),
            ChannelSubscription(
                channel="channel:demo:commands",
                target={"type": "command", "project": "demo", "command": "next-build"},
            ),
        ]

        async def stop_after_first_pass(_delay: float) -> None:
            shutdown_event.set()

        with (
            patch(
                "teleclaude.channels.worker.ensure_consumer_group",
                new=AsyncMock(side_effect=[RuntimeError("group failed"), None]),
            ) as mock_ensure_group,
            patch(
                "teleclaude.channels.worker.consume",
                new=AsyncMock(
                    side_effect=[
                        [
                            {"id": "1-0", "payload": {"kind": "deploy", "summary": "ready"}},
                            {"id": "1-1", "payload": {"kind": "ignore"}},
                        ],
                        [{"id": "2-0", "payload": {"message": "run"}}],
                    ]
                ),
            ) as mock_consume,
            patch("teleclaude.channels.worker._dispatch_to_target", new=AsyncMock()) as mock_dispatch,
            patch("teleclaude.channels.worker.asyncio.sleep", new=stop_after_first_pass),
        ):
            await worker.run_subscription_worker(redis, subscriptions, shutdown_event=shutdown_event)

        mock_ensure_group.assert_has_awaits(
            [
                call(redis, "channel:demo:events", worker._WORKER_GROUP),
                call(redis, "channel:demo:commands", worker._WORKER_GROUP),
            ]
        )
        mock_consume.assert_has_awaits(
            [
                call(
                    redis,
                    "channel:demo:events",
                    worker._WORKER_GROUP,
                    worker._WORKER_CONSUMER,
                    count=10,
                    block_ms=0,
                ),
                call(
                    redis,
                    "channel:demo:commands",
                    worker._WORKER_GROUP,
                    worker._WORKER_CONSUMER,
                    count=10,
                    block_ms=0,
                ),
            ]
        )
        mock_dispatch.assert_has_awaits(
            [
                call({"type": "notification", "channel": "telegram"}, {"kind": "deploy", "summary": "ready"}),
                call({"type": "command", "project": "demo", "command": "next-build"}, {"message": "run"}),
            ]
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_continues_after_consume_and_dispatch_failures(self) -> None:
        redis = object()
        shutdown_event = asyncio.Event()
        subscriptions = [
            ChannelSubscription(channel="channel:demo:events", target={"type": "notification"}),
            ChannelSubscription(channel="channel:demo:commands", target={"type": "command"}),
        ]

        async def stop_after_first_pass(_delay: float) -> None:
            shutdown_event.set()

        with (
            patch("teleclaude.channels.worker.ensure_consumer_group", new=AsyncMock()) as mock_ensure_group,
            patch(
                "teleclaude.channels.worker.consume",
                new=AsyncMock(
                    side_effect=[
                        RuntimeError("redis down"),
                        [{"id": "2-0", "payload": {"message": "run"}}],
                    ]
                ),
            ) as mock_consume,
            patch(
                "teleclaude.channels.worker._dispatch_to_target",
                new=AsyncMock(side_effect=RuntimeError("dispatch failed")),
            ) as mock_dispatch,
            patch("teleclaude.channels.worker.asyncio.sleep", new=stop_after_first_pass),
        ):
            await worker.run_subscription_worker(redis, subscriptions, shutdown_event=shutdown_event)

        assert mock_ensure_group.await_count == 2
        assert mock_consume.await_count == 2
        mock_dispatch.assert_awaited_once_with({"type": "command"}, {"message": "run"})
