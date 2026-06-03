"""Characterization tests for teleclaude.channels.worker."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, call, patch

import pytest

import teleclaude.channels.worker as worker
from teleclaude.config.schema import ChannelSubscription


class TestRunSubscriptionWorker:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_returns_immediately_when_no_subscriptions(self) -> None:
        redis = object()

        with (
            patch("teleclaude.channels.worker.ensure_consumer_group", new=AsyncMock()) as mock_ensure_group,
            patch("teleclaude.channels.worker.consume", new=AsyncMock()) as mock_consume,
        ):
            await worker.run_subscription_worker(redis, [])

        mock_ensure_group.assert_not_called()
        mock_consume.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_creates_distinct_computer_scoped_groups_and_dispatches_only_matching_messages(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def run_once(computer_name: str) -> tuple[set[str], set[str], AsyncMock]:
            monkeypatch.setattr(worker.config.computer, "name", computer_name)
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

            created_groups = {call_args.args[2] for call_args in mock_ensure_group.await_args_list}
            consumed_groups = {call_args.args[2].group for call_args in mock_consume.await_args_list}
            return created_groups, consumed_groups, mock_dispatch

        first_created_groups, first_consumed_groups, mock_dispatch = await run_once("MozMini")
        second_created_groups, second_consumed_groups, _mock_dispatch = await run_once("MozBook")

        assert first_created_groups == first_consumed_groups
        assert second_created_groups == second_consumed_groups
        assert first_created_groups != second_created_groups
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
