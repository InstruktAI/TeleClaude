"""Functional checks for todo-kind routing: vocabulary, normalization, entry phases.

Pure and deterministic — no daemon, no I/O, no waiting. Captures the kind-collapse
contract (feature/change/bug) so a regression in the routing table is caught.
"""

from __future__ import annotations

import pytest

from teleclaude.core.next_machine.kinds import (
    FAST_TRACK_PREPARED_KINDS,
    FEATURE_PREPARE_KINDS,
    KIND_ENTRY_PHASE,
    PLAN_ONLY_PREPARE_KINDS,
    canonical_kind,
)
from teleclaude.types.lifecycle import LifecyclePhase
from teleclaude.types.todo_kind import (
    ALL_DUMP_KINDS,
    TODO_KIND_BUG,
    TODO_KIND_CHANGE,
    TODO_KIND_FEATURE,
)

pytestmark = pytest.mark.functional


def test_vocabulary_is_exactly_feature_change_bug() -> None:
    assert ALL_DUMP_KINDS == {TODO_KIND_FEATURE, TODO_KIND_CHANGE, TODO_KIND_BUG}


def test_canonical_kind_passes_through_a_current_kind() -> None:
    assert canonical_kind(TODO_KIND_CHANGE) == TODO_KIND_CHANGE


def test_canonical_kind_maps_legacy_kinds_to_their_successor() -> None:
    # refactor/migration/chore/prepped collapse onto change; todo/draft onto feature.
    assert canonical_kind("refactor") == TODO_KIND_CHANGE
    assert canonical_kind("todo") == TODO_KIND_FEATURE


def test_canonical_kind_defaults_absent_kind_to_feature() -> None:
    assert canonical_kind(None) == TODO_KIND_FEATURE


def test_entry_phase_table_maps_each_kind_to_its_entry() -> None:
    assert KIND_ENTRY_PHASE == {
        TODO_KIND_FEATURE: LifecyclePhase.PRD_DRAFTING,
        TODO_KIND_CHANGE: LifecyclePhase.PLAN_DRAFTING,
        TODO_KIND_BUG: LifecyclePhase.PREPARED,
    }


def test_frozenset_views_are_projections_of_the_entry_table() -> None:
    assert FEATURE_PREPARE_KINDS == {TODO_KIND_FEATURE}
    assert PLAN_ONLY_PREPARE_KINDS == {TODO_KIND_CHANGE}
    assert FAST_TRACK_PREPARED_KINDS == {TODO_KIND_BUG}
