"""Tests for per-class drift derivation helpers."""

from __future__ import annotations

from teleclaude.core.next_machine.git_ops import (
    DRIFT_COSMETIC,
    DRIFT_FRESH,
    DRIFT_PENDING,
    derive_age_drift,
    derive_dependency_graph_drift,
    derive_owned_snippet_drift,
    derive_upstream_artifact_drift,
    derive_upstream_snippet_drift,
)
from teleclaude.types.todos import DependencyEntry, DriftReviewedStamp, TodoState

_ARCHITECTURE = "architecture"
_IMPLEMENTATION_PLAN = "implementation-plan"
_IMPLEMENTATION_PLAN_STATE_KEY = "implementation_plan"
_PRD = "prd"
_SNIPPET_ID = "project/spec/example"
_STALE_DIGEST = "stale-digest"
_CURRENT_DIGEST = "current-digest"
_COSMETIC_REASON = "cosmetic"
_ACTIVE_STATUS = "active"
_DEPENDENCY_SLUG = "dependency"


class _FakeTodosDb:
    def __init__(self, deps: list[DependencyEntry]) -> None:
        self._deps = deps

    async def get_deps_with_status(self, _slug: str) -> list[DependencyEntry]:
        return self._deps


def _snippet_digest(snippet_id: str) -> str:
    return _CURRENT_DIGEST if snippet_id == _SNIPPET_ID else ""


def test_upstream_artifact_drift_is_fresh_when_recorded_digests_match_current_state() -> None:
    state = TodoState.defaults()
    state.artifacts.prd.digest = _CURRENT_DIGEST
    state.artifacts.architecture.digest = "architecture-digest"
    state.artifacts.architecture.upstream_digests = {_PRD: _CURRENT_DIGEST}

    status = derive_upstream_artifact_drift(state, _ARCHITECTURE)

    assert status == DRIFT_FRESH


def test_upstream_artifact_drift_is_pending_when_recorded_digest_is_stale_without_anchor() -> None:
    state = TodoState.defaults()
    state.artifacts.prd.digest = _CURRENT_DIGEST
    state.artifacts.architecture.digest = "architecture-digest"
    state.artifacts.architecture.upstream_digests = {_PRD: _STALE_DIGEST}

    status = derive_upstream_artifact_drift(state, _ARCHITECTURE)

    assert status == DRIFT_PENDING


def test_upstream_artifact_drift_uses_cosmetic_anchor_for_current_evidence() -> None:
    state = TodoState.defaults()
    state.artifacts.prd.digest = _CURRENT_DIGEST
    state.artifacts.architecture.digest = "architecture-digest"
    state.artifacts.architecture.upstream_digests = {_PRD: _STALE_DIGEST}
    state.approvals.drift_reviewed[_ARCHITECTURE] = DriftReviewedStamp(
        verdict=DRIFT_COSMETIC,
        reason=_COSMETIC_REASON,
        upstream_digests_at_review={_PRD: _CURRENT_DIGEST},
    )

    status = derive_upstream_artifact_drift(state, _ARCHITECTURE)

    assert status == DRIFT_COSMETIC


def test_owned_snippet_drift_is_pending_until_async_provenance_is_complete() -> None:
    state = TodoState.defaults()
    state.artifacts.architecture.digest = "architecture-digest"
    state.artifacts.architecture.owned_snippet_digests = {_SNIPPET_ID: _CURRENT_DIGEST}

    status = derive_owned_snippet_drift(state, _ARCHITECTURE, snippet_digest_fn=_snippet_digest)

    assert status == DRIFT_PENDING


def test_owned_snippet_drift_is_fresh_when_digests_match() -> None:
    state = TodoState.defaults()
    state.artifacts.architecture.digest = "architecture-digest"
    state.artifacts.architecture.async_provenance_complete = True
    state.artifacts.architecture.owned_snippet_digests = {_SNIPPET_ID: _CURRENT_DIGEST}

    status = derive_owned_snippet_drift(state, _ARCHITECTURE, snippet_digest_fn=_snippet_digest)

    assert status == DRIFT_FRESH


def test_upstream_snippet_drift_re_pends_when_cosmetic_anchor_is_stale() -> None:
    state = TodoState.defaults()
    state.artifacts.implementation_plan.digest = "plan-digest"
    state.artifacts.implementation_plan.async_provenance_complete = True
    state.artifacts.implementation_plan.referenced_snippet_digests = {_SNIPPET_ID: _STALE_DIGEST}
    state.approvals.drift_reviewed[_IMPLEMENTATION_PLAN] = DriftReviewedStamp(
        verdict=DRIFT_COSMETIC,
        reason=_COSMETIC_REASON,
        snippet_digests_at_review={_SNIPPET_ID: _STALE_DIGEST},
    )

    status = derive_upstream_snippet_drift(state, _IMPLEMENTATION_PLAN_STATE_KEY, snippet_digest_fn=_snippet_digest)

    assert status == DRIFT_PENDING


async def test_dependency_graph_drift_is_fresh_when_snapshot_matches_current_direct_deps() -> None:
    dep = DependencyEntry(dep_slug=_DEPENDENCY_SLUG, roadmap_status=_ACTIVE_STATUS)
    state = TodoState.defaults()
    state.artifacts.implementation_plan.digest = "plan-digest"
    state.artifacts.implementation_plan.async_provenance_complete = True
    state.artifacts.implementation_plan.dependency_set_at_write = [dep]

    status = await derive_dependency_graph_drift(
        "child",
        state,
        _IMPLEMENTATION_PLAN_STATE_KEY,
        todos_db=_FakeTodosDb([dep]),
    )

    assert status == DRIFT_FRESH


async def test_dependency_graph_drift_is_pending_when_direct_dep_status_changes() -> None:
    recorded = DependencyEntry(dep_slug=_DEPENDENCY_SLUG, roadmap_status=_ACTIVE_STATUS)
    current = DependencyEntry(dep_slug=_DEPENDENCY_SLUG, roadmap_status="delivered")
    state = TodoState.defaults()
    state.artifacts.implementation_plan.digest = "plan-digest"
    state.artifacts.implementation_plan.async_provenance_complete = True
    state.artifacts.implementation_plan.dependency_set_at_write = [recorded]

    status = await derive_dependency_graph_drift(
        "child",
        state,
        _IMPLEMENTATION_PLAN_STATE_KEY,
        todos_db=_FakeTodosDb([current]),
    )

    assert status == DRIFT_PENDING


def test_age_drift_is_fresh_when_age_window_is_disabled() -> None:
    state = TodoState.defaults()
    state.artifacts.architecture.digest = "architecture-digest"
    state.artifacts.architecture.produced_at = "2020-01-01T00:00:00+00:00"

    status = derive_age_drift(state, _ARCHITECTURE, age_window_seconds=None)

    assert status == DRIFT_FRESH


def test_age_drift_is_pending_when_artifact_is_older_than_window() -> None:
    state = TodoState.defaults()
    state.artifacts.architecture.digest = "architecture-digest"
    state.artifacts.architecture.produced_at = "2020-01-01T00:00:00+00:00"

    status = derive_age_drift(state, _ARCHITECTURE, age_window_seconds=1, now_iso="2020-01-01T00:00:02+00:00")

    assert status == DRIFT_PENDING
