"""Functional tests bound to the workflow drift-detection spec."""

from __future__ import annotations

import pytest

from teleclaude.constants import (
    ARTIFACT_IMPLEMENTATION_PLAN,
    STATE_KEY_ARCHITECTURE,
    STATE_KEY_DIAGNOSIS,
    STATE_KEY_IMPLEMENTATION_PLAN,
    STATE_KEY_INPUT,
    STATE_KEY_PRD,
)
from teleclaude.core.next_machine import git_ops, provenance, stamps
from teleclaude.core.next_machine.git_ops import (
    DRIFT_COSMETIC,
    DRIFT_FRESH,
    DRIFT_PENDING,
    derive_artifact_drift,
    derive_dependency_graph_drift,
    derive_upstream_artifact_drift,
    extract_referenced_paths,
)
from teleclaude.core.next_machine.lifecycle import collapse_drift, derive_lifecycle_drift
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.types.todos import DependencyEntry, DriftReviewedStamp, RoadmapStatusLiteral, TodoState

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/workflow/drift-detection"
_BUG_KIND = "bug"
_INPUT_DIGEST = "input-v1"
_DIAGNOSIS_DIGEST = "diagnosis-v1"
_REWRITTEN_DIGEST = "diagnosis-v2"


class _DependencyReader:
    def __init__(self, deps: list[DependencyEntry] | None = None) -> None:
        self._deps = deps or []

    async def get_deps_with_status(self, _slug: str) -> list[DependencyEntry]:
        return self._deps


def _empty_snippet_digest(_snippet_id: str) -> str:
    return ""


def _prepared_bug_model(*, diagnosis_digest: str = _DIAGNOSIS_DIGEST) -> TodoState:
    model = TodoState(kind=_BUG_KIND, lifecycle_phase="prepared", schema_version=4)
    model.plan_review.verdict = "approve"

    model.artifacts.input.digest = _INPUT_DIGEST
    model.artifacts.input.async_provenance_complete = True

    model.artifacts.diagnosis.digest = diagnosis_digest
    model.artifacts.diagnosis.upstream_digests = {STATE_KEY_INPUT: _INPUT_DIGEST}
    model.artifacts.diagnosis.async_provenance_complete = True

    model.artifacts.implementation_plan.digest = "plan-v1"
    model.artifacts.implementation_plan.upstream_digests = {
        STATE_KEY_PRD: "",
        STATE_KEY_ARCHITECTURE: "",
        STATE_KEY_DIAGNOSIS: _DIAGNOSIS_DIGEST,
    }
    model.artifacts.implementation_plan.async_provenance_complete = True
    model.approvals.drift_reviewed[ARTIFACT_IMPLEMENTATION_PLAN] = DriftReviewedStamp(
        verdict="cosmetic",
        upstream_digests_at_review={
            STATE_KEY_PRD: "",
            STATE_KEY_ARCHITECTURE: "",
            STATE_KEY_DIAGNOSIS: _DIAGNOSIS_DIGEST,
        },
    )
    return model


def _dependency_entry(dep_slug: str, roadmap_status: RoadmapStatusLiteral) -> DependencyEntry:
    return DependencyEntry(dep_slug=dep_slug, roadmap_status=roadmap_status)


def _plan_with_dependency_set(entries: list[DependencyEntry]) -> TodoState:
    model = TodoState(kind="change", lifecycle_phase="prepared", schema_version=4)
    model.artifacts.implementation_plan.digest = "plan-v1"
    model.artifacts.implementation_plan.async_provenance_complete = True
    model.artifacts.implementation_plan.dependency_set_at_write = entries
    return model


def test_referenced_paths_come_from_declared_contract_block() -> None:
    body = """
This plan mentions manifests/cli-surface.md in prose.

```referenced-paths
# ignored heading
teleclaude/core/next_machine/git_ops.py

tests/workflow/test_drift_detection.py
teleclaude/core/next_machine/git_ops.py
new/untracked/file.py
```
"""

    assert extract_referenced_paths(body) == [
        "new/untracked/file.py",
        "teleclaude/core/next_machine/git_ops.py",
        "tests/workflow/test_drift_detection.py",
    ]


def test_referenced_paths_ignore_prose_mentions_and_missing_contract_blocks() -> None:
    body = "Grounding mentions manifests/cli-surface.md, but no contract block declares it."
    entry = TodoState(kind="change", schema_version=4).artifacts.implementation_plan
    entry.digest = "plan-v1"
    entry.referenced_paths = extract_referenced_paths(body)

    assert entry.referenced_paths == []
    assert derive_artifact_drift(entry, None, "", "") == DRIFT_FRESH


@pytest.mark.spec(_SPEC, "UC-WDD7")
async def test_delivered_dependency_status_matches_recorded_active_status() -> None:
    model = _plan_with_dependency_set([_dependency_entry("dep", "active")])

    drift = await derive_dependency_graph_drift(
        "todo",
        model,
        ARTIFACT_IMPLEMENTATION_PLAN,
        todos_db=_DependencyReader([_dependency_entry("dep", "delivered")]),
    )

    assert drift == DRIFT_FRESH


@pytest.mark.spec(_SPEC, "UC-WDD8")
async def test_dependency_graph_still_drifts_for_icebox_and_set_membership_changes() -> None:
    held_to_delivered = await derive_dependency_graph_drift(
        "todo",
        _plan_with_dependency_set([_dependency_entry("dep", "icebox")]),
        ARTIFACT_IMPLEMENTATION_PLAN,
        todos_db=_DependencyReader([_dependency_entry("dep", "delivered")]),
    )
    removed = await derive_dependency_graph_drift(
        "todo",
        _plan_with_dependency_set([_dependency_entry("dep", "active")]),
        ARTIFACT_IMPLEMENTATION_PLAN,
        todos_db=_DependencyReader([]),
    )
    added = await derive_dependency_graph_drift(
        "todo",
        _plan_with_dependency_set([]),
        ARTIFACT_IMPLEMENTATION_PLAN,
        todos_db=_DependencyReader([_dependency_entry("dep", "active")]),
    )

    assert held_to_delivered == DRIFT_PENDING
    assert removed == DRIFT_PENDING
    assert added == DRIFT_PENDING


async def test_dependency_graph_review_anchor_uses_normalized_statuses() -> None:
    model = _plan_with_dependency_set([])
    model.approvals.drift_reviewed[ARTIFACT_IMPLEMENTATION_PLAN] = DriftReviewedStamp(
        verdict=DRIFT_COSMETIC,
        dep_set_at_review=[_dependency_entry("dep", "delivered")],
    )

    drift = await derive_dependency_graph_drift(
        "todo",
        model,
        ARTIFACT_IMPLEMENTATION_PLAN,
        todos_db=_DependencyReader([_dependency_entry("dep", "active")]),
    )

    assert drift == DRIFT_COSMETIC


@pytest.mark.spec(_SPEC, "UC-WDD1")
async def test_bug_implementation_plan_upstream_drift_is_fresh_when_diagnosis_matches() -> None:
    model = _prepared_bug_model()

    assert derive_upstream_artifact_drift(model, ARTIFACT_IMPLEMENTATION_PLAN) == DRIFT_FRESH

    drift = await derive_lifecycle_drift(
        "my-bug",
        model,
        repo_root="",
        todos_db=_DependencyReader(),
        snippet_digest_fn=_empty_snippet_digest,
        writer=StateWriter(model.model_dump(exclude_none=True)),
    )
    assert collapse_drift(drift)[ARTIFACT_IMPLEMENTATION_PLAN] != DRIFT_PENDING


@pytest.mark.spec(_SPEC, "UC-WDD2")
def test_diagnosis_rewrite_drifts_bug_implementation_plan() -> None:
    model = _prepared_bug_model(diagnosis_digest=_REWRITTEN_DIGEST)

    assert derive_upstream_artifact_drift(model, ARTIFACT_IMPLEMENTATION_PLAN) == DRIFT_PENDING


@pytest.mark.spec(_SPEC, "UC-WDD4")
def test_diagnosis_upstream_drift_detects_input_rewrites() -> None:
    model = _prepared_bug_model()
    model.artifacts.diagnosis.upstream_digests = {STATE_KEY_INPUT: _INPUT_DIGEST}

    assert derive_upstream_artifact_drift(model, STATE_KEY_DIAGNOSIS) == DRIFT_FRESH

    model.artifacts.input.digest = "input-v2"

    assert derive_upstream_artifact_drift(model, STATE_KEY_DIAGNOSIS) == DRIFT_PENDING


@pytest.mark.spec(_SPEC, "UC-WDD5")
def test_artifact_upstream_topology_is_shared_by_all_consumers() -> None:
    model = _prepared_bug_model()
    writer = StateWriter(model.model_dump(exclude_none=True))

    assert not hasattr(git_ops, "_ARTIFACT_UPSTREAMS")
    assert not hasattr(provenance, "_ARTIFACT_UPSTREAMS")
    assert not hasattr(stamps, "_ARTIFACT_UPSTREAMS")

    assert git_ops.ARTIFACT_UPSTREAMS is provenance.ARTIFACT_UPSTREAMS
    assert git_ops.ARTIFACT_UPSTREAMS is stamps.ARTIFACT_UPSTREAMS

    for current_upstreams in (git_ops.ARTIFACT_UPSTREAMS, provenance.ARTIFACT_UPSTREAMS, stamps.ARTIFACT_UPSTREAMS):
        assert current_upstreams[STATE_KEY_IMPLEMENTATION_PLAN] == (
            STATE_KEY_PRD,
            STATE_KEY_ARCHITECTURE,
            STATE_KEY_DIAGNOSIS,
        )
        assert current_upstreams[STATE_KEY_DIAGNOSIS] == (STATE_KEY_INPUT,)

    assert provenance._current_upstream_digests(writer, STATE_KEY_IMPLEMENTATION_PLAN) == {
        STATE_KEY_PRD: "",
        STATE_KEY_ARCHITECTURE: "",
        STATE_KEY_DIAGNOSIS: _DIAGNOSIS_DIGEST,
    }
    assert stamps._current_upstream_digests(writer, STATE_KEY_DIAGNOSIS) == {
        STATE_KEY_INPUT: _INPUT_DIGEST,
    }
    assert derive_upstream_artifact_drift(model, ARTIFACT_IMPLEMENTATION_PLAN) == DRIFT_FRESH
