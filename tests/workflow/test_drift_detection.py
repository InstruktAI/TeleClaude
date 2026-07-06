"""Functional tests bound to the workflow drift-detection spec."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest

from teleclaude.constants import (
    ARTIFACT_IMPLEMENTATION_PLAN,
    STATE_KEY_ARCHITECTURE,
    STATE_KEY_DIAGNOSIS,
    STATE_KEY_IMPLEMENTATION_PLAN,
    STATE_KEY_INPUT,
    STATE_KEY_PRD,
)
from teleclaude.core.next_machine import git_ops
from teleclaude.core.next_machine.git_ops import (
    DRIFT_COSMETIC,
    DRIFT_FRESH,
    DRIFT_PENDING,
    derive_artifact_drift,
    derive_upstream_artifact_drift,
    extract_referenced_paths,
)
from teleclaude.core.next_machine.lifecycle import collapse_drift, derive_lifecycle_drift
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.todos_db import close_todos_db_instances
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import (
    DependencyEntry,
    DriftReviewedStamp,
    TodoState,
)

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/workflow/drift-detection"
_BUG_KIND = "bug"
_CHANGE_KIND = "change"
_INPUT_DIGEST = "input-v1"
_REWRITTEN_INPUT_DIGEST = "input-v2"
_DIAGNOSIS_DIGEST = "diagnosis-v1"
_REWRITTEN_DIGEST = "diagnosis-v2"


def _prepared_change_model(
    *, input_digest: str = _INPUT_DIGEST, recorded_input_digest: str = _INPUT_DIGEST
) -> TodoState:
    """A prepared change Todo whose plan was drafted directly from input (no PRD/diagnosis)."""
    model = TodoState(kind=_CHANGE_KIND, lifecycle_phase="prepared", schema_version=5)
    model.plan_review.verdict = "approve"

    model.artifacts.input.digest = input_digest
    model.artifacts.input.async_provenance_complete = True

    model.artifacts.implementation_plan.digest = "plan-v1"
    model.artifacts.implementation_plan.upstream_digests = {STATE_KEY_INPUT: recorded_input_digest}
    model.artifacts.implementation_plan.async_provenance_complete = True
    return model


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
    model = TodoState(kind=_BUG_KIND, lifecycle_phase="prepared", schema_version=5)
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


def _prepared_feature_model(*, recorded_architecture_digest: str, current_architecture_digest: str) -> TodoState:
    """A prepared feature Todo whose plan tracks prd + architecture; diagnosis is structurally absent."""
    model = TodoState(kind="feature", lifecycle_phase="prepared", schema_version=5)
    model.plan_review.verdict = "approve"

    model.artifacts.input.digest = _INPUT_DIGEST
    model.artifacts.input.async_provenance_complete = True

    model.artifacts.prd.digest = "prd-v1"
    model.artifacts.prd.async_provenance_complete = True

    model.artifacts.architecture.digest = current_architecture_digest
    model.artifacts.architecture.async_provenance_complete = True

    model.artifacts.implementation_plan.digest = "plan-v1"
    model.artifacts.implementation_plan.upstream_digests = {
        STATE_KEY_PRD: "prd-v1",
        STATE_KEY_ARCHITECTURE: recorded_architecture_digest,
        STATE_KEY_DIAGNOSIS: "",
    }
    model.artifacts.implementation_plan.async_provenance_complete = True
    model.approvals.drift_reviewed[ARTIFACT_IMPLEMENTATION_PLAN] = DriftReviewedStamp(
        verdict="cosmetic",
        upstream_digests_at_review={
            STATE_KEY_PRD: "prd-v1",
            STATE_KEY_ARCHITECTURE: current_architecture_digest,
            STATE_KEY_DIAGNOSIS: "",
        },
    )
    return model


@pytest.mark.spec(_SPEC, "UC-WDD12")
async def test_matching_cosmetic_stamp_clears_upstream_drift_past_absent_upstream() -> None:
    model = _prepared_feature_model(
        recorded_architecture_digest="arch-old",
        current_architecture_digest="arch-new",
    )

    assert derive_upstream_artifact_drift(model, ARTIFACT_IMPLEMENTATION_PLAN) == DRIFT_COSMETIC

    drift = await derive_lifecycle_drift(
        "my-feature",
        model,
        repo_root="",
        todos_db=_DependencyReader(),
        snippet_digest_fn=_empty_snippet_digest,
        writer=StateWriter(model.model_dump(exclude_none=True)),
    )
    assert collapse_drift(drift)[ARTIFACT_IMPLEMENTATION_PLAN] != DRIFT_PENDING


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
    entry = TodoState(kind="change", schema_version=5).artifacts.implementation_plan
    entry.digest = "plan-v1"
    entry.referenced_paths = extract_referenced_paths(body)

    assert entry.referenced_paths == []
    assert derive_artifact_drift(entry, None, "", "") == DRIFT_FRESH


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


@pytest.mark.spec(_SPEC, "UC-WDD10")
async def test_change_input_rewrite_drifts_implementation_plan() -> None:
    model = _prepared_change_model(input_digest=_REWRITTEN_INPUT_DIGEST, recorded_input_digest=_INPUT_DIGEST)

    assert derive_upstream_artifact_drift(model, ARTIFACT_IMPLEMENTATION_PLAN) == DRIFT_PENDING

    drift = await derive_lifecycle_drift(
        "my-change",
        model,
        repo_root="",
        todos_db=_DependencyReader(),
        snippet_digest_fn=_empty_snippet_digest,
        writer=StateWriter(model.model_dump(exclude_none=True)),
    )

    assert STATE_KEY_INPUT not in drift
    assert collapse_drift(drift)[ARTIFACT_IMPLEMENTATION_PLAN] == DRIFT_PENDING


@pytest.mark.spec(_SPEC, "UC-WDD11")
def test_change_implementation_plan_is_fresh_when_input_unchanged() -> None:
    model = _prepared_change_model(input_digest=_INPUT_DIGEST, recorded_input_digest=_INPUT_DIGEST)

    assert derive_upstream_artifact_drift(model, ARTIFACT_IMPLEMENTATION_PLAN) == DRIFT_FRESH


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
