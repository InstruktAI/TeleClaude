"""Tests for shared todo kind groupings."""

from __future__ import annotations

from teleclaude.core.next_machine.kinds import (
    FAST_TRACK_PREPARED_KINDS,
    KIND_BUG,
    KIND_MIGRATION,
    KIND_PREPPED,
    KIND_REFACTOR,
    PLAN_ONLY_PREPARE_KINDS,
    PLAN_WITHOUT_INTENT_UPSTREAM_KINDS,
)


def test_plan_without_intent_upstream_kinds_include_all_plan_spec_sources() -> None:
    assert PLAN_ONLY_PREPARE_KINDS <= PLAN_WITHOUT_INTENT_UPSTREAM_KINDS
    assert KIND_REFACTOR in PLAN_WITHOUT_INTENT_UPSTREAM_KINDS
    assert KIND_MIGRATION in PLAN_WITHOUT_INTENT_UPSTREAM_KINDS
    assert KIND_PREPPED in PLAN_WITHOUT_INTENT_UPSTREAM_KINDS
    assert KIND_PREPPED in FAST_TRACK_PREPARED_KINDS
    assert KIND_BUG not in PLAN_WITHOUT_INTENT_UPSTREAM_KINDS
