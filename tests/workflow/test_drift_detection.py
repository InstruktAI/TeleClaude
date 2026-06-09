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
    DRIFT_FRESH,
    DRIFT_PENDING,
    derive_upstream_artifact_drift,
)
from teleclaude.core.next_machine.lifecycle import collapse_drift, derive_lifecycle_drift
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.types.todos import DependencyEntry, DriftReviewedStamp, TodoState

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/workflow/drift-detection"
_BUG_KIND = "bug"
_INPUT_DIGEST = "input-v1"
_DIAGNOSIS_DIGEST = "diagnosis-v1"
_REWRITTEN_DIGEST = "diagnosis-v2"


class _DependencyReader:
    async def get_deps_with_status(self, _slug: str) -> list[DependencyEntry]:
        return []


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
