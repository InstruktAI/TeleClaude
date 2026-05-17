"""Tests for the v2 → v1 Redis identity bridge."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from teleclaude.transport.identity_bridge import (
    PRINCIPAL_PREFIX,
    TOKEN_PREFIX,
    IdentityBridge,
    IdentityEnvelope,
    MalformedIdentityEnvelopeError,
    decode_envelope,
)


def _envelope(
    *,
    channel: str = PRINCIPAL_PREFIX + "created",
    idempotency_key: str = "key-1",
    payload: dict[str, object] | None = None,  # guard: loose-dict - mirrors envelope payload shape
    principal: dict[str, object] | None = None,  # guard: loose-dict - mirrors envelope principal shape
) -> IdentityEnvelope:
    return IdentityEnvelope(
        channel=channel,
        idempotency_key=idempotency_key,
        emitted_at="2026-05-17T12:00:00Z",
        principal=principal,
        payload=payload if payload is not None else {"email": "owner@example.com"},
    )


def _bridge(dispatch: Any) -> IdentityBridge:
    return IdentityBridge(redis_factory=lambda: MagicMock(), dispatch=dispatch)


class TestProcessEnvelope:
    def test_dispatches_principal_envelope(self) -> None:
        dispatch = MagicMock()
        bridge = _bridge(dispatch)
        envelope = _envelope(channel="identity.principal.created")

        dispatched = bridge.process_envelope(envelope)

        assert dispatched is True
        dispatch.assert_called_once_with(envelope)

    def test_dispatches_token_envelope(self) -> None:
        dispatch = MagicMock()
        bridge = _bridge(dispatch)
        envelope = _envelope(channel=TOKEN_PREFIX + "issued", idempotency_key="t-1")

        dispatched = bridge.process_envelope(envelope)

        assert dispatched is True
        dispatch.assert_called_once_with(envelope)

    def test_unknown_channel_is_dropped(self) -> None:
        dispatch = MagicMock()
        bridge = _bridge(dispatch)
        envelope = _envelope(channel="workflow.todo.created", idempotency_key="u-1")

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

    def test_dispatcher_exception_does_not_propagate(self) -> None:
        dispatch = MagicMock(side_effect=RuntimeError("boom"))
        bridge = _bridge(dispatch)

        # process_envelope swallows dispatcher exceptions and returns False.
        assert bridge.process_envelope(_envelope()) is False


CHANNEL_PRINCIPAL_CREATED = PRINCIPAL_PREFIX + "created"
PRINCIPAL_KIND_HUMAN = "human"


class TestDecodeEnvelope:
    def test_decodes_valid_payload(self) -> None:
        idempotency_key = "k-1"
        raw = json.dumps(
            {
                "channel": CHANNEL_PRINCIPAL_CREATED,
                "idempotency_key": idempotency_key,
                "emitted_at": "2026-05-17T12:00:00Z",
                "principal": {"kind": PRINCIPAL_KIND_HUMAN, "email": "owner@example.com"},
                "payload": {"email": "owner@example.com"},
            }
        )

        envelope = decode_envelope(raw)

        # Compare against the constants the production code exposes — the
        # encoded payload routes back to those identifiers verbatim.
        assert envelope.channel == CHANNEL_PRINCIPAL_CREATED
        assert envelope.idempotency_key == idempotency_key
        assert envelope.principal_kind == PRINCIPAL_KIND_HUMAN

    def test_rejects_invalid_json(self) -> None:
        with pytest.raises(MalformedIdentityEnvelopeError):
            decode_envelope("not json")

    def test_rejects_non_object_root(self) -> None:
        with pytest.raises(MalformedIdentityEnvelopeError):
            decode_envelope("[]")

    def test_rejects_missing_channel(self) -> None:
        raw = json.dumps(
            {
                "idempotency_key": "k-1",
                "emitted_at": "2026-05-17T12:00:00Z",
                "payload": {},
            }
        )
        with pytest.raises(MalformedIdentityEnvelopeError):
            decode_envelope(raw)

    def test_rejects_non_object_principal(self) -> None:
        raw = json.dumps(
            {
                "channel": "identity.principal.created",
                "idempotency_key": "k-1",
                "emitted_at": "2026-05-17T12:00:00Z",
                "principal": "not-an-object",
                "payload": {},
            }
        )
        with pytest.raises(MalformedIdentityEnvelopeError):
            decode_envelope(raw)
