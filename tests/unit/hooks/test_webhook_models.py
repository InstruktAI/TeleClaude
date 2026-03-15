"""Characterization tests for teleclaude.hooks.webhook_models."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from teleclaude.hooks.webhook_models import Contract, HookEvent, PropertyCriterion, Target


class TestHookEvent:
    @pytest.mark.unit
    def test_to_json_and_from_json_round_trip_payload_and_properties(self) -> None:
        event = HookEvent(
            source="github",
            type="pull_request",
            timestamp="2025-01-01T00:00:00+00:00",
            properties={"repo": "owner/repo", "count": 2},
            payload={"action": "opened"},
        )

        assert HookEvent.from_json(event.to_json()) == event

    @pytest.mark.unit
    def test_now_populates_timestamp_and_empty_defaults(self) -> None:
        event = HookEvent.now(source="whatsapp", type="message.text")

        assert event.source == "whatsapp"
        assert event.type == "message.text"
        assert event.properties == {}
        assert event.payload == {}
        assert datetime.fromisoformat(event.timestamp).tzinfo == UTC


class TestContract:
    @pytest.mark.unit
    def test_is_expired_is_false_when_no_expiration_is_set(self) -> None:
        contract = Contract(id="contract-1", target=Target(handler="handler"))

        assert contract.is_expired is False

    @pytest.mark.unit
    def test_is_expired_tracks_past_and_future_timestamps(self) -> None:
        expired = Contract(
            id="expired",
            target=Target(handler="handler"),
            expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        )
        active = Contract(
            id="active",
            target=Target(handler="handler"),
            expires_at=(datetime.now(UTC) + timedelta(seconds=60)).isoformat(),
        )

        assert expired.is_expired is True
        assert active.is_expired is False

    @pytest.mark.unit
    def test_to_json_and_from_json_round_trip_nested_contract_fields(self) -> None:
        contract = Contract(
            id="contract-2",
            target=Target(handler="handler", url=None, secret="secret"),
            source_criterion=PropertyCriterion(match="github"),
            type_criterion=PropertyCriterion(pattern="pull_*"),
            properties={"repo": PropertyCriterion(match=["owner/repo", "owner/docs"])},
            expires_at="2025-01-01T00:00:00+00:00",
            source="config",
        )

        restored = Contract.from_json(contract.to_json())

        assert restored == contract
