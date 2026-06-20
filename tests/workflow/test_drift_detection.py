"""Functional tests bound to the workflow drift-detection spec."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from teleclaude.constants import (
    ARTIFACT_IMPLEMENTATION_PLAN,
    ARTIFACT_PRD,
    STATE_KEY_ARCHITECTURE,
    STATE_KEY_DIAGNOSIS,
    STATE_KEY_IMPLEMENTATION_PLAN,
    STATE_KEY_INPUT,
    STATE_KEY_PRD,
)
from teleclaude.core.next_machine import git_ops, provenance
from teleclaude.core.next_machine.git_ops import (
    DRIFT_COSMETIC,
    DRIFT_FRESH,
    DRIFT_PENDING,
    derive_artifact_drift,
    derive_dependency_graph_drift,
    derive_parent_prd_ground_drift,
    derive_upstream_artifact_drift,
    extract_referenced_paths,
)
from teleclaude.core.next_machine.lifecycle import collapse_drift, derive_lifecycle_drift
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.todos_db import close_todos_db_instances, get_todos_db
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import (
    DependencyEntry,
    DriftReviewedStamp,
    ParentPrdGroundEntry,
    TodoState,
    TodoStatusLiteral,
)

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/workflow/drift-detection"
_BUG_KIND = "bug"
_INPUT_DIGEST = "input-v1"
_DIAGNOSIS_DIGEST = "diagnosis-v1"
_REWRITTEN_DIGEST = "diagnosis-v2"


class _DependencyReader:
    def __init__(
        self,
        deps: list[DependencyEntry] | None = None,
        states: dict[str, TodoState] | None = None,
    ) -> None:
        self._deps = deps or []
        self._states = states or {}

    async def get_deps_with_status(self, _slug: str) -> list[DependencyEntry]:
        return self._deps

    async def read_state(self, slug: str) -> dict[str, StateValue] | None:
        state = self._states.get(slug)
        return state.model_dump(exclude_none=True) if state is not None else None


@pytest.fixture(autouse=True)
async def _close_todos_db_after_test() -> AsyncGenerator[None]:
    yield
    await close_todos_db_instances()


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


def _dependency_entry(dep_slug: str, todo_status: TodoStatusLiteral) -> DependencyEntry:
    return DependencyEntry(dep_slug=dep_slug, todo_status=todo_status)


def _plan_with_dependency_set(entries: list[DependencyEntry]) -> TodoState:
    model = TodoState(kind="change", lifecycle_phase="prepared", schema_version=4)
    model.artifacts.implementation_plan.digest = "plan-v1"
    model.artifacts.implementation_plan.async_provenance_complete = True
    model.artifacts.implementation_plan.dependency_set_at_write = entries
    return model


def _approved_parent_model(
    *,
    prd_digest: str = "parent-prd-v1",
    approved_at: str = "2026-06-10T00:00:00+00:00",
    caller_session_id: str = "human:parent",
    architecture_digest: str = "",
    implementation_plan_digest: str = "",
) -> TodoState:
    model = TodoState(kind="feature", lifecycle_phase="prd_human_approval", schema_version=4)
    model.artifacts.prd.digest = prd_digest
    model.approvals.prd_approved.approved = True
    model.approvals.prd_approved.approved_at = approved_at
    model.approvals.prd_approved.caller_session_id = caller_session_id
    model.approvals.prd_approved.approved_digest = prd_digest
    model.artifacts.architecture.digest = architecture_digest
    model.artifacts.implementation_plan.digest = implementation_plan_digest
    return model


def _parent_ground_entry(
    *,
    dep_slug: str = "parent",
    prd_digest: str = "parent-prd-v1",
    approved_at: str = "2026-06-10T00:00:00+00:00",
    caller_session_id: str = "human:parent",
    architecture_digest: str = "",
    implementation_plan_digest: str = "",
) -> ParentPrdGroundEntry:
    return ParentPrdGroundEntry(
        dep_slug=dep_slug,
        prd_digest=prd_digest,
        prd_approved_at=approved_at,
        prd_approved_by_session_id=caller_session_id,
        architecture_digest=architecture_digest,
        implementation_plan_digest=implementation_plan_digest,
    )


def _plan_with_parent_ground(entries: list[ParentPrdGroundEntry]) -> TodoState:
    model = TodoState(kind="change", lifecycle_phase="prepared", schema_version=4)
    model.artifacts.implementation_plan.digest = "plan-v1"
    model.artifacts.implementation_plan.async_provenance_complete = True
    model.artifacts.implementation_plan.parent_prd_ground_at_write = entries
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


async def test_parent_prd_ground_provenance_records_direct_prd_approved_dependency(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await get_todos_db(project_root)
    await todos_db.add_to_todo("parent")
    await todos_db.write_artifact("parent", ARTIFACT_PRD, "# Parent PRD\n", updated_by="test")
    parent = _approved_parent_model(prd_digest=await todos_db.artifact_digest("parent", ARTIFACT_PRD))
    parent.artifacts.architecture.digest = "parent-architecture"
    await todos_db.write_state("parent", parent.model_dump(exclude_none=True))
    await todos_db.add_to_todo("child", after=["parent"])
    await todos_db.write_artifact("child", ARTIFACT_IMPLEMENTATION_PLAN, "# Plan\n", updated_by="test")
    child = TodoState(kind="change", lifecycle_phase="plan_review", schema_version=4)
    writer = StateWriter(child.model_dump(exclude_none=True))

    await provenance.sync_artifact_provenance(
        todos_db,
        writer,
        "child",
        ARTIFACT_IMPLEMENTATION_PLAN,
        repo_root=str(project_root),
        artifact_body="# Plan\n",
        snippet_digest_fn=_empty_snippet_digest,
    )

    assert writer.state.artifacts.implementation_plan.parent_prd_ground_at_write == [
        _parent_ground_entry(prd_digest=parent.artifacts.prd.digest, architecture_digest="parent-architecture")
    ]


@pytest.mark.spec(_SPEC, "UC-WDD5")
async def test_parent_prd_ground_drift_detects_parent_prd_and_later_artifact_changes() -> None:
    model = _plan_with_parent_ground([_parent_ground_entry()])

    fresh = await derive_parent_prd_ground_drift(
        "child",
        model,
        ARTIFACT_IMPLEMENTATION_PLAN,
        todos_db=_DependencyReader(
            [_dependency_entry("parent", "active")],
            {"parent": _approved_parent_model()},
        ),
    )
    prd_changed = await derive_parent_prd_ground_drift(
        "child",
        model,
        ARTIFACT_IMPLEMENTATION_PLAN,
        todos_db=_DependencyReader(
            [_dependency_entry("parent", "active")],
            {"parent": _approved_parent_model(prd_digest="parent-prd-v2")},
        ),
    )
    architecture_appeared = await derive_parent_prd_ground_drift(
        "child",
        model,
        ARTIFACT_IMPLEMENTATION_PLAN,
        todos_db=_DependencyReader(
            [_dependency_entry("parent", "active")],
            {"parent": _approved_parent_model(architecture_digest="parent-architecture")},
        ),
    )
    delivered = await derive_parent_prd_ground_drift(
        "child",
        model,
        ARTIFACT_IMPLEMENTATION_PLAN,
        todos_db=_DependencyReader(
            [_dependency_entry("parent", "delivered")],
            {"parent": _approved_parent_model(prd_digest="parent-prd-v2")},
        ),
    )

    assert fresh == DRIFT_FRESH
    assert prd_changed == DRIFT_PENDING
    assert architecture_appeared == DRIFT_PENDING
    assert delivered == DRIFT_FRESH


async def test_parent_prd_ground_review_anchor_can_mark_current_evidence_cosmetic() -> None:
    model = _plan_with_parent_ground([])
    model.approvals.drift_reviewed[ARTIFACT_IMPLEMENTATION_PLAN] = DriftReviewedStamp(
        verdict=DRIFT_COSMETIC,
        parent_prd_ground_at_review=[_parent_ground_entry()],
    )

    drift = await derive_parent_prd_ground_drift(
        "child",
        model,
        ARTIFACT_IMPLEMENTATION_PLAN,
        todos_db=_DependencyReader(
            [_dependency_entry("parent", "active")],
            {"parent": _approved_parent_model()},
        ),
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


@pytest.mark.spec(_SPEC, "UC-WDD5")
async def test_lifecycle_drift_includes_parent_prd_ground_for_dependent_artifacts() -> None:
    model = _plan_with_parent_ground([_parent_ground_entry()])

    drift = await derive_lifecycle_drift(
        "child",
        model,
        repo_root="",
        todos_db=_DependencyReader(
            [_dependency_entry("parent", "active")],
            {"parent": _approved_parent_model(prd_digest="parent-prd-v2")},
        ),
        snippet_digest_fn=_empty_snippet_digest,
        writer=StateWriter(model.model_dump(exclude_none=True)),
    )

    assert drift[ARTIFACT_IMPLEMENTATION_PLAN]["parent-prd-ground"] == DRIFT_PENDING
    assert collapse_drift(drift)[ARTIFACT_IMPLEMENTATION_PLAN] == DRIFT_PENDING


@pytest.mark.spec(_SPEC, "UC-WDD2")
def test_diagnosis_rewrite_drifts_bug_implementation_plan() -> None:
    model = _prepared_bug_model(diagnosis_digest=_REWRITTEN_DIGEST)

    assert derive_upstream_artifact_drift(model, ARTIFACT_IMPLEMENTATION_PLAN) == DRIFT_PENDING


@pytest.mark.spec(_SPEC, "UC-WDD4")
async def test_input_and_diagnosis_are_not_lifecycle_drift_targets() -> None:
    model = _prepared_bug_model()
    model.artifacts.diagnosis.upstream_digests = {STATE_KEY_INPUT: _INPUT_DIGEST}
    model.artifacts.input.digest = "input-v2"
    model.artifacts.diagnosis.digest = _REWRITTEN_DIGEST

    drift = await derive_lifecycle_drift(
        "my-bug",
        model,
        repo_root="",
        todos_db=_DependencyReader(),
        snippet_digest_fn=_empty_snippet_digest,
        writer=StateWriter(model.model_dump(exclude_none=True)),
    )

    assert STATE_KEY_INPUT not in drift
    assert STATE_KEY_DIAGNOSIS not in drift
    assert collapse_drift(drift)[ARTIFACT_IMPLEMENTATION_PLAN] == DRIFT_PENDING


@pytest.mark.spec(_SPEC, "UC-WDD5")
async def test_lifecycle_drift_tracks_plan_diagnosis_evidence_without_tracking_diagnosis() -> None:
    model = _prepared_bug_model()

    assert not hasattr(git_ops, "_ARTIFACT_UPSTREAMS")
    assert git_ops.ARTIFACT_UPSTREAMS[STATE_KEY_IMPLEMENTATION_PLAN] == (
        STATE_KEY_PRD,
        STATE_KEY_ARCHITECTURE,
        STATE_KEY_DIAGNOSIS,
    )
    assert git_ops.ARTIFACT_UPSTREAMS[STATE_KEY_DIAGNOSIS] == (STATE_KEY_INPUT,)
    assert derive_upstream_artifact_drift(model, ARTIFACT_IMPLEMENTATION_PLAN) == DRIFT_FRESH

    drift = await derive_lifecycle_drift(
        "my-bug",
        model,
        repo_root="",
        todos_db=_DependencyReader(),
        snippet_digest_fn=_empty_snippet_digest,
        writer=StateWriter(model.model_dump(exclude_none=True)),
    )

    assert STATE_KEY_INPUT not in drift
    assert STATE_KEY_DIAGNOSIS not in drift
    assert collapse_drift(drift)[ARTIFACT_IMPLEMENTATION_PLAN] != DRIFT_PENDING
