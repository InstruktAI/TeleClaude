"""Tests for the v2 → v1 Redis workflow bridge."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from teleclaude.transport.workflow_bridge import (
    ARTIFACT_PREFIX,
    ROADMAP_PREFIX,
    TODO_PREFIX,
    MalformedEnvelopeError,
    WorkflowBridge,
    WorkflowEnvelope,
    decode_envelope,
)


def _envelope(
    *,
    channel: str = TODO_PREFIX + "created",
    idempotency_key: str = "key-1",
    payload: dict[str, object] | None = None,  # guard: loose-dict - mirrors envelope payload shape
    principal: dict[str, object] | None = None,  # guard: loose-dict - mirrors envelope principal shape
) -> WorkflowEnvelope:
    return WorkflowEnvelope(
        channel=channel,
        idempotency_key=idempotency_key,
        emitted_at="2026-05-16T12:00:00Z",
        principal=principal,
        payload=payload if payload is not None else {"slug": "foo", "project_path": "/p"},
    )


def _bridge(dispatch: Any) -> WorkflowBridge:
    return WorkflowBridge(redis_factory=lambda: MagicMock(), dispatch=dispatch)


class TestProcessEnvelope:
    def test_dispatches_todo_envelope(self) -> None:
        dispatch = MagicMock()
        bridge = _bridge(dispatch)
        envelope = _envelope(channel="workflow.todo.created")

        dispatched = bridge.process_envelope(envelope)

        assert dispatched is True
        dispatch.assert_called_once_with(envelope)

    def test_dispatches_roadmap_envelope(self) -> None:
        dispatch = MagicMock()
        bridge = _bridge(dispatch)
        envelope = _envelope(channel=ROADMAP_PREFIX + "entry_added", idempotency_key="r-1")

        dispatched = bridge.process_envelope(envelope)

        assert dispatched is True
        dispatch.assert_called_once_with(envelope)

    def test_dispatches_artifact_envelope(self) -> None:
        dispatch = MagicMock()
        bridge = _bridge(dispatch)
        envelope = _envelope(channel=ARTIFACT_PREFIX + "written", idempotency_key="a-1")

        dispatched = bridge.process_envelope(envelope)

        assert dispatched is True
        dispatch.assert_called_once_with(envelope)

    def test_unknown_channel_is_dropped(self) -> None:
        dispatch = MagicMock()
        bridge = _bridge(dispatch)
        envelope = _envelope(channel="agent_runtime.session.started", idempotency_key="u-1")

        dispatched = bridge.process_envelope(envelope)

        assert dispatched is False
        dispatch.assert_not_called()

    def test_idempotency_dedup_on_duplicate_key(self) -> None:
        dispatch = MagicMock()
        bridge = _bridge(dispatch)
        envelope = _envelope(idempotency_key="dup-key")

        first = bridge.process_envelope(envelope)
        second = bridge.process_envelope(envelope)

        assert first is True
        assert second is False
        assert dispatch.call_count == 1

    def test_dispatcher_exception_is_swallowed(self) -> None:
        dispatch = MagicMock(side_effect=RuntimeError("downstream failure"))
        bridge = _bridge(dispatch)
        envelope = _envelope()

        # Must not raise — subscriber loop continuation depends on it.
        dispatched = bridge.process_envelope(envelope)

        assert dispatched is False
        dispatch.assert_called_once()


class TestDecodeEnvelope:
    def test_decodes_valid_envelope_round_trips(self) -> None:
        expected = WorkflowEnvelope(
            channel=TODO_PREFIX + "updated",
            idempotency_key="k-1",
            emitted_at="2026-05-16T00:00:00Z",
            principal={"kind": "user", "id": "alice"},
            payload={"slug": "foo"},
        )
        raw = json.dumps(
            {
                "channel": expected.channel,
                "idempotency_key": expected.idempotency_key,
                "emitted_at": expected.emitted_at,
                "principal": expected.principal,
                "payload": expected.payload,
            }
        ).encode()

        assert decode_envelope(raw) == expected

    def test_rejects_non_json_payload(self) -> None:
        with pytest.raises(MalformedEnvelopeError):
            decode_envelope(b"not-json")

    def test_rejects_missing_required_field(self) -> None:
        raw = json.dumps(
            {
                "channel": TODO_PREFIX + "created",
                "idempotency_key": "k",
                # emitted_at missing
                "payload": {},
            }
        ).encode()

        with pytest.raises(MalformedEnvelopeError):
            decode_envelope(raw)

    def test_rejects_invalid_utf8(self) -> None:
        with pytest.raises(MalformedEnvelopeError):
            decode_envelope(b"\xff\xfe\xfd")


class TestSubscriberLoop:
    """Tests that exercise the run loop against a fake pubsub."""

    def test_malformed_envelope_does_not_crash(self) -> None:
        dispatch = MagicMock()
        bridge = _bridge(dispatch)

        # Direct exercise of the message handler used by the run loop.
        bridge._handle_raw_message(b"this is not JSON")

        dispatch.assert_not_called()

    def test_unexpected_payload_type_is_ignored(self) -> None:
        dispatch = MagicMock()
        bridge = _bridge(dispatch)

        bridge._handle_raw_message(12345)

        dispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_reconnects_with_exponential_backoff_on_connection_error(self) -> None:
        sleeps: list[float] = []

        async def _capture_sleep(delay: float) -> None:
            sleeps.append(delay)
            # Yield to the event loop so the stopper task can observe progress.
            await asyncio.sleep(0)

        attempt_count = {"n": 0}

        def _factory() -> Any:
            attempt_count["n"] += 1
            raise ConnectionError("redis down")

        dispatch = MagicMock()
        bridge = WorkflowBridge(
            redis_factory=_factory,
            dispatch=dispatch,
            initial_backoff_s=1.0,
            max_backoff_s=30.0,
            sleep=_capture_sleep,
        )

        async def _stop_after_three_attempts() -> None:
            # Yield to the run loop enough times for it to record three failures.
            while attempt_count["n"] < 3:
                await asyncio.sleep(0)
            await bridge.stop()

        stopper = asyncio.create_task(_stop_after_three_attempts())
        await bridge.run()
        await stopper

        assert attempt_count["n"] >= 3
        # First three backoffs follow the doubling schedule (1, 2, 4) capped at max.
        assert sleeps[0] == pytest.approx(1.0)
        assert sleeps[1] == pytest.approx(2.0)
        assert sleeps[2] == pytest.approx(4.0)
