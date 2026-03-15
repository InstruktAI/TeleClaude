"""Characterization tests for teleclaude.hooks.matcher."""

from __future__ import annotations

import pytest

from teleclaude.hooks.matcher import match_criterion, match_event
from teleclaude.hooks.webhook_models import Contract, HookEvent, PropertyCriterion, Target


class TestMatchCriterion:
    @pytest.mark.unit
    def test_optional_criteria_always_match(self) -> None:
        assert match_criterion(None, PropertyCriterion(required=False)) is True

    @pytest.mark.unit
    def test_presence_only_criteria_require_a_value(self) -> None:
        criterion = PropertyCriterion()

        assert match_criterion(None, criterion) is False
        assert match_criterion("present", criterion) is True

    @pytest.mark.unit
    def test_pattern_matching_uses_stringified_values(self) -> None:
        criterion = PropertyCriterion(pattern="session.*")

        assert match_criterion("session.started", criterion) is True
        assert match_criterion("command.finished", criterion) is False

    @pytest.mark.unit
    def test_list_matching_accepts_original_and_stringified_values(self) -> None:
        criterion = PropertyCriterion(match=["1", "2"])

        assert match_criterion(2, criterion) is True
        assert match_criterion(3, criterion) is False


class TestMatchEvent:
    @pytest.mark.unit
    def test_event_must_satisfy_source_type_and_property_criteria(self) -> None:
        event = HookEvent(
            source="github",
            type="pull_request",
            timestamp="2025-01-01T00:00:00+00:00",
            properties={"repo": "owner/repo", "action": "opened"},
        )
        contract = Contract(
            id="contract-1",
            target=Target(handler="handler"),
            source_criterion=PropertyCriterion(match="github"),
            type_criterion=PropertyCriterion(match="pull_request"),
            properties={
                "repo": PropertyCriterion(match="owner/repo"),
                "action": PropertyCriterion(pattern="open*"),
            },
        )

        assert match_event(event, contract) is True

    @pytest.mark.unit
    def test_event_fails_when_any_required_property_does_not_match(self) -> None:
        event = HookEvent(
            source="github",
            type="pull_request",
            timestamp="2025-01-01T00:00:00+00:00",
            properties={"repo": "owner/repo"},
        )
        contract = Contract(
            id="contract-2",
            target=Target(handler="handler"),
            properties={"action": PropertyCriterion(match="opened")},
        )

        assert match_event(event, contract) is False
