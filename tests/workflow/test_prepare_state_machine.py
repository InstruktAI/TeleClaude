"""Functional tests bound to the workflow prepare-state-machine spec."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import pytest

import teleclaude.core.db as db_mod
from teleclaude.constants import (
    ARTIFACT_IMPLEMENTATION_PLAN,
    ARTIFACT_PRD,
    LOCAL_COMPUTER,
    STATE_KEY_ARCHITECTURE,
    STATE_KEY_DIAGNOSIS,
    STATE_KEY_IMPLEMENTATION_PLAN,
    STATE_KEY_INPUT,
    STATE_KEY_PRD,
)
from teleclaude.core.db import Db
from teleclaude.core.next_machine import provenance
from teleclaude.core.next_machine import work as work_machine
from teleclaude.core.next_machine._types import PreparePhase, WorkPhase
from teleclaude.core.next_machine.git_ops import DRIFT_FRESH, derive_artifact_drift
from teleclaude.core.next_machine.kinds import (
    BUG_DIAGNOSE_KINDS,
    FAST_TRACK_PREPARED_KINDS,
    KIND_BUG,
    KIND_CHANGE,
    KIND_FEATURE,
    KIND_TASK,
)
from teleclaude.core.next_machine.lifecycle import (
    LIFECYCLE_PHASE_ORDER,
    LifecyclePhase,
    adopt_prepare_handoff_phase,
    collapse_drift,
    derive_lifecycle_drift,
    is_ready_for_work,
    phase_is_complete,
)
from teleclaude.core.next_machine.prepare import next_prepare
from teleclaude.core.next_machine.prepare_step_support import prepare_step_prepared
from teleclaude.core.next_machine.prepare_steps import _prepare_dispatch
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.next_machine.work import next_work
from teleclaude.core.next_machine.work_steps import _artifact_contract_note
from teleclaude.core.origins import InputOrigin
from teleclaude.core.todos_db import TodosDb, close_todos_db_instances, get_todos_db
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import (
    DependencyEntry,
    DriftReviewedStamp,
    ParentPrdGroundEntry,
    TodoState,
    TodoStatusLiteral,
)

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/workflow/prepare-state-machine"
_WORK_SPEC = "project/spec/feature/workflow/work-state-machine"
_PROJECT_ROOT = "/repo"
_PARENT = "parent"
_CHILD = "child"
_PARENT_WORKER = "sess-parent-worker"
_PARENT_REVIEWER = "sess-parent-reviewer"
_UNRELATED = "sess-unrelated"
_PREFIX_COLLISION = "sess-prefix-collision"
_WORKTREE_SESSION = "sess-worktree"
_AUTO_CONTINUE_LABEL = "AUTO-CONTINUE"
_CHILD_SESSION_RUN = "telec sessions run --command /next-prepare"
_CHILD_SESSION_SEND = "telec sessions send"
_SELF_END = "telec sessions end self"
_DRIFT_SPEC = "project/spec/feature/workflow/drift-detection"
_DRIFT_SLUG = "matching-drift-bug"
_INPUT_DIGEST = "input-v1"
_DIAGNOSIS_DIGEST = "diagnosis-v1"


@dataclass(frozen=True)
class _Session:
    session_id: str
    title: str
    subdir: str | None = None


class _CapturingDb:
    def __init__(self, sessions: list[_Session]) -> None:
        self._sessions = sessions

    async def clear_expired_agent_availability(self) -> None:
        return None

    async def get_agent_availability(self, _agent_name: str) -> dict[str, str]:
        return {"status": "available"}

    async def list_sessions(self, *, include_closed: bool = False) -> list[_Session]:
        _ = include_closed
        return self._sessions


class _DependencyReader:
    def __init__(self, deps: list[DependencyEntry], states: dict[str, TodoState] | None = None) -> None:
        self._deps = deps
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


async def _project_db(project_root: Path) -> TodosDb:
    await close_todos_db_instances()
    return await get_todos_db(project_root)


async def _read_state(todos_db: TodosDb, slug: str) -> dict[str, StateValue]:
    state = await todos_db.read_state(slug)
    assert state is not None
    return state


async def _add_todo(
    todos_db: TodosDb,
    slug: str,
    *,
    lifecycle_phase: LifecyclePhase,
    after: list[str] | None = None,
) -> None:
    await todos_db.add_to_todo(slug, after=after)
    await todos_db.write_state(
        slug,
        {
            "schema_version": 4,
            "kind": "change",
            "phase": "pending",
            "lifecycle_phase": lifecycle_phase.value,
        },
    )


async def _create_human_runtime_session(project_root: Path, *, session_id: str) -> str:
    runtime_db = await db_mod.get_db()
    session = await runtime_db.create_session(
        computer_name=LOCAL_COMPUTER,
        tmux_session_name=f"tmux-{session_id}",
        last_input_origin=InputOrigin.TERMINAL.value,
        title=session_id,
        session_id=session_id,
        human_email="operator@example.test",
        human_role="owner",
        project_path=str(project_root),
        working_slug=None,
        emit_session_started=False,
    )
    return session.session_id


async def _add_feature_with_rewritten_approved_prd(
    todos_db: TodosDb,
    slug: str,
    *,
    caller_session_id: str,
    approved_digest: str | None,
) -> tuple[str, str]:
    await todos_db.add_to_todo(slug)
    await todos_db.write_artifact(slug, ARTIFACT_PRD, "# PRD\n\nApproved version.", updated_by="test")
    old_digest = await todos_db.artifact_digest(slug, ARTIFACT_PRD)
    await todos_db.write_artifact(slug, ARTIFACT_PRD, "# PRD\n\nCurrent version.", updated_by="test")
    current_digest = await todos_db.artifact_digest(slug, ARTIFACT_PRD)

    model = TodoState(kind=KIND_FEATURE, lifecycle_phase=LifecyclePhase.PREPARED.value, schema_version=4)
    model.artifacts.prd.digest = current_digest
    model.artifacts.prd.async_provenance_complete = True
    model.approvals.prd_approved.approved = True
    model.approvals.prd_approved.caller_session_id = caller_session_id
    model.approvals.prd_approved.approved_digest = old_digest if approved_digest is None else approved_digest
    await todos_db.write_state(slug, model.model_dump(exclude_none=True))
    return old_digest, current_digest


def _dependency_entry(dep_slug: str, todo_status: TodoStatusLiteral) -> DependencyEntry:
    return DependencyEntry(dep_slug=dep_slug, todo_status=todo_status)


def _parent_ground_entry(
    *,
    dep_slug: str = _PARENT,
    prd_digest: str = "parent-prd-v1",
    architecture_digest: str = "",
    implementation_plan_digest: str = "",
) -> ParentPrdGroundEntry:
    return ParentPrdGroundEntry(
        dep_slug=dep_slug,
        prd_digest=prd_digest,
        prd_approved_at="2026-06-10T00:00:00+00:00",
        prd_approved_by_session_id="human:parent",
        architecture_digest=architecture_digest,
        implementation_plan_digest=implementation_plan_digest,
    )


def _approved_parent_model(*, prd_digest: str = "parent-prd-v1") -> TodoState:
    model = TodoState(kind=KIND_FEATURE, lifecycle_phase=LifecyclePhase.PRD_HUMAN_APPROVAL.value, schema_version=4)
    model.artifacts.prd.digest = prd_digest
    model.approvals.prd_approved.approved = True
    model.approvals.prd_approved.approved_at = "2026-06-10T00:00:00+00:00"
    model.approvals.prd_approved.caller_session_id = "human:parent"
    model.approvals.prd_approved.approved_digest = prd_digest
    return model


def _prepared_dependent_with_parent_ground() -> TodoState:
    model = TodoState(kind=KIND_CHANGE, lifecycle_phase=LifecyclePhase.PREPARED.value, schema_version=4)
    model.plan_review.verdict = "approve"
    model.plan_review.approved_digest = "plan-v1"
    model.artifacts.input.digest = _INPUT_DIGEST
    model.artifacts.input.async_provenance_complete = True
    model.artifacts.implementation_plan.digest = "plan-v1"
    model.artifacts.implementation_plan.upstream_digests = {STATE_KEY_INPUT: _INPUT_DIGEST}
    model.artifacts.implementation_plan.async_provenance_complete = True
    model.artifacts.implementation_plan.dependency_set_at_write = [_dependency_entry(_PARENT, "active")]
    model.artifacts.implementation_plan.parent_prd_ground_at_write = [_parent_ground_entry()]
    return model


@pytest.mark.spec(_SPEC, "UC-WPS3")
async def test_prepare_selector_skips_kindless_todos_without_lifecycle_phase(tmp_path: Path, snapshot: object) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await todos_db.add_to_todo("classify-me")
    await todos_db.write_state("classify-me", {"schema_version": 4, "kind": None, "phase": "pending"})

    output = await next_prepare(cast(Db, _CapturingDb([])), None, str(project_root))

    assert output == snapshot


@pytest.mark.spec(_SPEC, "UC-WPS4")
async def test_prepare_unknown_slug_does_not_create_todo_row(tmp_path: Path, snapshot: object) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)

    output = await next_prepare(cast(Db, _CapturingDb([])), "unknown-prepare", str(project_root))

    assert not await todos_db.slug_in_todo("unknown-prepare")
    assert output == snapshot


@pytest.mark.spec(_SPEC, "UC-WPS5")
async def test_prepared_terminal_does_not_continue_into_child_slug(tmp_path: Path) -> None:
    todos_db = await _project_db(tmp_path / "project")
    await _add_todo(todos_db, _PARENT, lifecycle_phase=LifecyclePhase.PREPARED)
    await _add_todo(todos_db, _CHILD, lifecycle_phase=LifecyclePhase.DRAFT, after=[_PARENT])
    db = _CapturingDb(
        [
            _Session(_PARENT_WORKER, f"/next-prepare {_PARENT}"),
            _Session(_PARENT_REVIEWER, f"/next-review-plan {_PARENT}"),
            _Session(_UNRELATED, "/next-prepare unrelated"),
            _Session(_PREFIX_COLLISION, f"/next-prepare {_PARENT}-extra"),
            _Session(_WORKTREE_SESSION, f"/next-prepare {_PARENT}", subdir=f"trees/{_PARENT}"),
        ]
    )

    _, output = await prepare_step_prepared(cast(Db, db), todos_db, _PARENT, project_root=_PROJECT_ROOT)

    assert _AUTO_CONTINUE_LABEL not in output
    assert _CHILD_SESSION_RUN not in output
    assert _CHILD_SESSION_SEND not in output
    assert _PARENT_REVIEWER in output
    assert _SELF_END in output


@pytest.mark.spec(_SPEC, "UC-WPS5")
async def test_prepared_terminal_cleanup_without_parent_worker_reuse(tmp_path: Path) -> None:
    todos_db = await _project_db(tmp_path / "project")
    await _add_todo(todos_db, _PARENT, lifecycle_phase=LifecyclePhase.PREPARED)
    await _add_todo(todos_db, _CHILD, lifecycle_phase=LifecyclePhase.DRAFT, after=[_PARENT])

    db = _CapturingDb(
        [
            _Session(_PARENT_WORKER, f"/next-prepare {_PARENT}"),
            _Session(_PARENT_REVIEWER, f"/next-review-plan {_PARENT}"),
        ]
    )

    _, output = await prepare_step_prepared(cast(Db, db), todos_db, _PARENT, project_root=_PROJECT_ROOT)

    assert _AUTO_CONTINUE_LABEL not in output
    assert _CHILD_SESSION_RUN not in output
    assert _CHILD_SESSION_SEND not in output
    assert _PARENT_REVIEWER in output
    assert _SELF_END in output


def _bug_model() -> TodoState:
    return TodoState(kind=KIND_BUG, schema_version=4)


def _prepared_bug_model() -> TodoState:
    model = TodoState(kind=KIND_BUG, lifecycle_phase=LifecyclePhase.PREPARED.value, schema_version=4)
    model.plan_review.verdict = "approve"
    model.artifacts.input.digest = _INPUT_DIGEST
    model.artifacts.input.async_provenance_complete = True
    model.artifacts.diagnosis.digest = _DIAGNOSIS_DIGEST
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


async def _prepare_dispatch_for_substantive_drift_stamp(
    tmp_path: Path,
    *,
    phase: PreparePhase,
    artifact: str,
) -> str:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    slug = f"anomalous-{phase.value}-{artifact.replace('_', '-')}"
    await todos_db.add_to_todo(slug)
    model = _prepared_bug_model()
    model.lifecycle_phase = phase.value
    model.approvals.drift_reviewed[artifact] = DriftReviewedStamp(
        verdict="substantive",
        reason="mis-targeted substantive drift",
    )
    state = model.model_dump(exclude_none=True)
    await todos_db.write_state(slug, state)

    _, output = await _prepare_dispatch(
        db=cast(Db, _CapturingDb([])),
        todos_db=todos_db,
        slug=slug,
        cwd=str(project_root),
        phase=phase,
        state=state,
    )
    return output


def test_bug_kind_routes_through_diagnose_not_fast_track() -> None:
    assert KIND_BUG in BUG_DIAGNOSE_KINDS
    assert KIND_BUG not in FAST_TRACK_PREPARED_KINDS
    assert KIND_TASK in FAST_TRACK_PREPARED_KINDS
    arch_review = LIFECYCLE_PHASE_ORDER.index(LifecyclePhase.ARCHITECTURE_REVIEW)
    diagnose = LIFECYCLE_PHASE_ORDER.index(LifecyclePhase.DIAGNOSE)
    plan_drafting = LIFECYCLE_PHASE_ORDER.index(LifecyclePhase.PLAN_DRAFTING)
    assert arch_review < diagnose < plan_drafting


def test_bug_derives_diagnose_until_diagnosis_then_flows_like_a_plan() -> None:
    model = _bug_model()
    assert adopt_prepare_handoff_phase(model, artifact_presence={}) == LifecyclePhase.DIAGNOSE

    with_diagnosis = {STATE_KEY_DIAGNOSIS: True}
    assert adopt_prepare_handoff_phase(model, artifact_presence=with_diagnosis) == LifecyclePhase.PLAN_DRAFTING

    with_plan = {STATE_KEY_DIAGNOSIS: True, STATE_KEY_IMPLEMENTATION_PLAN: True}
    assert adopt_prepare_handoff_phase(model, artifact_presence=with_plan) == LifecyclePhase.PLAN_REVIEW

    model.plan_review.verdict = "approve"
    assert adopt_prepare_handoff_phase(model, artifact_presence=with_plan) == LifecyclePhase.PREPARED


@pytest.mark.spec(_SPEC, "UC-WPS8")
async def test_prd_rewritten_after_approval_is_re_approved(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    caller_session_id = await _create_human_runtime_session(
        project_root,
        session_id=f"{tmp_path.name}-prd-approval-human",
    )
    stale_slug = "stale-prd-approval"
    legacy_slug = "legacy-prd-approval"

    old_digest, current_digest = await _add_feature_with_rewritten_approved_prd(
        todos_db,
        stale_slug,
        caller_session_id=caller_session_id,
        approved_digest=None,
    )
    assert old_digest != current_digest

    await next_prepare(cast(Db, _CapturingDb([])), stale_slug, str(project_root))

    stale_state = await todos_db.read_state(stale_slug)
    assert stale_state is not None
    stale_writer = StateWriter(stale_state)
    assert stale_writer.state.lifecycle_phase == LifecyclePhase.PRD_HUMAN_APPROVAL.value

    await _add_feature_with_rewritten_approved_prd(
        todos_db,
        legacy_slug,
        caller_session_id=caller_session_id,
        approved_digest="",
    )

    await next_prepare(cast(Db, _CapturingDb([])), legacy_slug, str(project_root))

    legacy_state = await todos_db.read_state(legacy_slug)
    assert legacy_state is not None
    legacy_writer = StateWriter(legacy_state)
    assert legacy_writer.state.lifecycle_phase == LifecyclePhase.ARCHITECTURE_DRAFTING.value


@pytest.mark.spec(_SPEC, "UC-WPS7")
def test_review_approval_is_invalidated_when_its_artifact_is_rewritten() -> None:
    """An approve verdict satisfies its review gate only while approved_digest equals
    the live artifact digest; rewriting the artifact after approval re-opens the gate.
    Verified through the real derivation (adopt_prepare_handoff_phase) at the plan,
    architecture, and legacy-requirements gates — the architecture and requirements
    gates are reached via the no-PRD legacy-requirements path."""
    # Plan gate.
    plan = TodoState(kind=KIND_CHANGE, schema_version=4)
    plan.artifacts.implementation_plan.digest = "plan-approved"
    plan.plan_review.verdict = "approve"
    plan.plan_review.approved_digest = "plan-approved"
    assert adopt_prepare_handoff_phase(plan) == LifecyclePhase.PREPARED
    plan.artifacts.implementation_plan.digest = "plan-rewritten"
    assert adopt_prepare_handoff_phase(plan) == LifecyclePhase.PLAN_REVIEW

    # Architecture gate: current requirements pass the intent gate, current
    # architecture advances to plan_drafting; rewriting architecture re-opens review.
    arch = TodoState(kind=KIND_FEATURE, schema_version=4)
    arch.artifacts.requirements.digest = "req-current"
    arch.requirements_review.verdict = "approve"
    arch.requirements_review.approved_digest = "req-current"
    arch.artifacts.architecture.digest = "arch-approved"
    arch.architecture_review.verdict = "approve"
    arch.architecture_review.approved_digest = "arch-approved"
    assert adopt_prepare_handoff_phase(arch) == LifecyclePhase.PLAN_DRAFTING
    arch.artifacts.architecture.digest = "arch-rewritten"
    assert adopt_prepare_handoff_phase(arch) == LifecyclePhase.ARCHITECTURE_REVIEW

    # Legacy-requirements gate: current requirements advance past the intent gate;
    # rewriting requirements re-opens prd_human_approval.
    req = TodoState(kind=KIND_FEATURE, schema_version=4)
    req.artifacts.requirements.digest = "req-approved"
    req.requirements_review.verdict = "approve"
    req.requirements_review.approved_digest = "req-approved"
    assert adopt_prepare_handoff_phase(req) == LifecyclePhase.ARCHITECTURE_DRAFTING
    req.artifacts.requirements.digest = "req-rewritten"
    assert adopt_prepare_handoff_phase(req) == LifecyclePhase.PRD_HUMAN_APPROVAL


def _empty_snippet_digest(_snippet_id: str) -> str:
    return ""


def test_seeded_plan_is_held_in_plan_drafting_until_the_seed_clears() -> None:
    """A supplied --plan present at first entry must run a full plan-draft pass
    before review: the `seeded` flag overrides the plan-present⇒review default,
    and clearing it (same present, still-unreviewed artifact) advances to review."""
    model = TodoState(kind=KIND_CHANGE, schema_version=4)
    model.artifacts.implementation_plan.digest = "seed-v1"
    model.artifacts.implementation_plan.seeded = True
    assert adopt_prepare_handoff_phase(model) == LifecyclePhase.PLAN_DRAFTING

    model.artifacts.implementation_plan.seeded = False
    assert adopt_prepare_handoff_phase(model) == LifecyclePhase.PLAN_REVIEW


async def test_plan_rewrite_clears_the_seed_and_advances_to_plan_review(tmp_path: Path) -> None:
    """The drafting pass rewriting the implementation-plan flows through the
    canonical provenance rewrite-clear hook, dropping the seed so the next
    derivation hands the now-grounded plan to plan-review."""
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    slug = "seeded-rewrite"
    body = "# Plan\n\nSeeded hypothesis.\n"
    await todos_db.add_to_todo(slug)
    await todos_db.write_artifact(slug, ARTIFACT_IMPLEMENTATION_PLAN, body, updated_by="test")
    model = TodoState(kind=KIND_CHANGE, lifecycle_phase=LifecyclePhase.PLAN_DRAFTING.value, schema_version=4)
    model.artifacts.implementation_plan.digest = await todos_db.artifact_digest(slug, ARTIFACT_IMPLEMENTATION_PLAN)
    model.artifacts.implementation_plan.seeded = True
    await todos_db.write_state(slug, model.model_dump(exclude_none=True))

    held = StateWriter(await _read_state(todos_db, slug))
    assert adopt_prepare_handoff_phase(held.state) == LifecyclePhase.PLAN_DRAFTING

    enriched = "# Plan\n\nGrounded + blast-radius-informed + doc-reflected.\n"
    await todos_db.write_artifact(slug, ARTIFACT_IMPLEMENTATION_PLAN, enriched, updated_by="test")
    writer = StateWriter(await _read_state(todos_db, slug))
    await provenance.sync_artifact_provenance(
        todos_db,
        writer,
        slug,
        ARTIFACT_IMPLEMENTATION_PLAN,
        repo_root=str(project_root),
        artifact_body=enriched,
        snippet_digest_fn=_empty_snippet_digest,
    )
    await writer.commit(todos_db, slug)

    cleared = StateWriter(await _read_state(todos_db, slug))
    assert cleared.state.artifacts.implementation_plan.seeded is False
    assert adopt_prepare_handoff_phase(cleared.state) == LifecyclePhase.PLAN_REVIEW


async def test_non_plan_rewrite_leaves_a_seeded_plan_untouched(tmp_path: Path) -> None:
    """The rewrite-clear hook is keyed to the rewritten artifact: syncing a
    non-plan artifact must not drop a seeded implementation-plan."""
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    slug = "seeded-other-rewrite"
    await todos_db.add_to_todo(slug)
    await todos_db.write_artifact(slug, ARTIFACT_IMPLEMENTATION_PLAN, "# Plan\n\nSeeded.\n", updated_by="test")
    prd_body = "# PRD\n\nUnrelated rewrite.\n"
    await todos_db.write_artifact(slug, ARTIFACT_PRD, prd_body, updated_by="test")
    model = TodoState(kind=KIND_CHANGE, lifecycle_phase=LifecyclePhase.PLAN_DRAFTING.value, schema_version=4)
    model.artifacts.implementation_plan.digest = await todos_db.artifact_digest(slug, ARTIFACT_IMPLEMENTATION_PLAN)
    model.artifacts.implementation_plan.seeded = True
    await todos_db.write_state(slug, model.model_dump(exclude_none=True))

    writer = StateWriter(await _read_state(todos_db, slug))
    await provenance.sync_artifact_provenance(
        todos_db,
        writer,
        slug,
        ARTIFACT_PRD,
        repo_root=str(project_root),
        artifact_body=prd_body,
        snippet_digest_fn=_empty_snippet_digest,
    )
    await writer.commit(todos_db, slug)

    after = StateWriter(await _read_state(todos_db, slug))
    assert after.state.artifacts.implementation_plan.seeded is True


_PRD_DIGEST = "prd-approved"
_INPUT_AT_WRITE = "input-v1"
_INPUT_DRIFTED = "input-v2"
_APPROVAL_TS = "2026-06-14T10:00:00+00:00"
_DRIFT_AFTER_APPROVAL = "2026-06-14T12:00:00+00:00"


def _feature_with_prd_drift(
    *,
    caller_session_id: str,
    approved_at: str,
    input_drifted: bool,
    drift_verdict: Literal["substantive", "cosmetic"] | None,
    drift_stamped_at: str = _DRIFT_AFTER_APPROVAL,
) -> TodoState:
    """Build a feature whose PRD is human-approved at its current digest, with the
    input either drifted (upstream-artifact drift) or unchanged, and an optional
    drift_reviewed["prd"] stamp."""
    current_input = _INPUT_DRIFTED if input_drifted else _INPUT_AT_WRITE
    model = TodoState(kind=KIND_FEATURE, schema_version=4)
    model.artifacts.prd.digest = _PRD_DIGEST
    model.artifacts.prd.upstream_digests = {STATE_KEY_INPUT: _INPUT_AT_WRITE}
    model.artifacts.input.digest = current_input
    model.approvals.prd_approved.approved = True
    model.approvals.prd_approved.caller_session_id = caller_session_id
    model.approvals.prd_approved.approved_digest = _PRD_DIGEST
    model.approvals.prd_approved.approved_at = approved_at
    if drift_verdict is not None:
        model.approvals.drift_reviewed[ARTIFACT_PRD] = DriftReviewedStamp(
            verdict=drift_verdict,
            stamped_at=drift_stamped_at,
            upstream_digests_at_review={STATE_KEY_INPUT: current_input},
        )
    return model


@pytest.mark.spec(_SPEC, "UC-WPS9")
async def test_substantive_upstream_prd_drift_reopens_human_approval_gate(tmp_path: Path) -> None:
    """A pending substantive UPSTREAM-artifact (input) drift re-opens prd_human_approval
    so an intent-level input change re-derives and re-approves the PRD. A substantive
    verdict driven by downstream evidence (input unchanged) does NOT re-open; a cosmetic
    drift does not re-open; a legacy (no approved_at) approval and a drift with no
    stamped_at yield to the drift; a re-approval that post-dates the drift advances."""
    project_root = tmp_path / "project"
    await _project_db(project_root)
    caller_session_id = await _create_human_runtime_session(
        project_root,
        session_id=f"{tmp_path.name}-prd-drift-human",
    )

    upstream_drift_supersedes = _feature_with_prd_drift(
        caller_session_id=caller_session_id,
        approved_at=_APPROVAL_TS,
        input_drifted=True,
        drift_verdict="substantive",
    )
    assert adopt_prepare_handoff_phase(upstream_drift_supersedes) == LifecyclePhase.PRD_HUMAN_APPROVAL
    assert phase_is_complete(upstream_drift_supersedes, LifecyclePhase.PRD_HUMAN_APPROVAL) is False

    downstream_only_drift = _feature_with_prd_drift(
        caller_session_id=caller_session_id,
        approved_at=_APPROVAL_TS,
        input_drifted=False,
        drift_verdict="substantive",
    )
    assert adopt_prepare_handoff_phase(downstream_only_drift) == LifecyclePhase.ARCHITECTURE_DRAFTING

    legacy_untimestamped_approval = _feature_with_prd_drift(
        caller_session_id=caller_session_id,
        approved_at="",
        input_drifted=True,
        drift_verdict="substantive",
    )
    assert adopt_prepare_handoff_phase(legacy_untimestamped_approval) == LifecyclePhase.PRD_HUMAN_APPROVAL

    untimestamped_drift = _feature_with_prd_drift(
        caller_session_id=caller_session_id,
        approved_at=_APPROVAL_TS,
        input_drifted=True,
        drift_verdict="substantive",
        drift_stamped_at="",
    )
    assert adopt_prepare_handoff_phase(untimestamped_drift) == LifecyclePhase.PRD_HUMAN_APPROVAL

    reapproved_after_drift = _feature_with_prd_drift(
        caller_session_id=caller_session_id,
        approved_at=_DRIFT_AFTER_APPROVAL,
        input_drifted=True,
        drift_verdict="substantive",
        drift_stamped_at=_APPROVAL_TS,
    )
    assert adopt_prepare_handoff_phase(reapproved_after_drift) == LifecyclePhase.ARCHITECTURE_DRAFTING
    assert phase_is_complete(reapproved_after_drift, LifecyclePhase.PRD_HUMAN_APPROVAL) is True

    cosmetic_drift = _feature_with_prd_drift(
        caller_session_id=caller_session_id,
        approved_at=_APPROVAL_TS,
        input_drifted=True,
        drift_verdict="cosmetic",
    )
    assert adopt_prepare_handoff_phase(cosmetic_drift) == LifecyclePhase.ARCHITECTURE_DRAFTING

    legacy_no_drift = _feature_with_prd_drift(
        caller_session_id=caller_session_id,
        approved_at="",
        input_drifted=False,
        drift_verdict=None,
    )
    legacy_no_drift.approvals.prd_approved.approved_digest = ""
    assert adopt_prepare_handoff_phase(legacy_no_drift) == LifecyclePhase.ARCHITECTURE_DRAFTING


@pytest.mark.spec(_SPEC, "UC-WPS9")
def test_stray_substantive_prd_drift_is_inert_for_plan_only_kind() -> None:
    """The prd_human_approval re-open is feature-gate only; a change todo that never
    gates on prd_approved is unaffected by a stray substantive prd drift stamp."""
    model = TodoState(kind=KIND_CHANGE, schema_version=4)
    model.artifacts.implementation_plan.digest = "plan-approved"
    model.plan_review.verdict = "approve"
    model.plan_review.approved_digest = "plan-approved"
    model.approvals.drift_reviewed[ARTIFACT_PRD] = DriftReviewedStamp(
        verdict="substantive",
        stamped_at=_DRIFT_AFTER_APPROVAL,
    )
    assert adopt_prepare_handoff_phase(model) == LifecyclePhase.PREPARED


def test_bug_is_not_work_ready_before_prepared() -> None:
    diagnose_ready, _ = is_ready_for_work(kind=KIND_BUG, lifecycle_phase=LifecyclePhase.DIAGNOSE.value)
    plan_ready, _ = is_ready_for_work(kind=KIND_BUG, lifecycle_phase=LifecyclePhase.PLAN_DRAFTING.value)
    prepared_ready, _ = is_ready_for_work(kind=KIND_BUG, lifecycle_phase=LifecyclePhase.PREPARED.value)
    assert diagnose_ready is False
    assert plan_ready is False
    assert prepared_ready is True


@pytest.mark.spec(_WORK_SPEC, "UC-WSM1")
def test_bug_work_mandate_names_plan_and_diagnosis(snapshot: object) -> None:
    assert _artifact_contract_note("my-bug", KIND_BUG) == snapshot


@pytest.mark.spec(_SPEC, "UC-WPS2")
async def test_prepared_cleanup_is_unchanged_without_unblocked_children(tmp_path: Path, snapshot: object) -> None:
    todos_db = await _project_db(tmp_path / "project")
    await _add_todo(todos_db, _PARENT, lifecycle_phase=LifecyclePhase.PREPARED)
    db = _CapturingDb(
        [
            _Session(_PARENT_WORKER, f"/next-prepare {_PARENT}"),
            _Session(_PARENT_REVIEWER, f"/next-review-plan {_PARENT}"),
        ]
    )

    _, output = await prepare_step_prepared(cast(Db, db), todos_db, _PARENT, project_root=_PROJECT_ROOT)

    assert output == snapshot


@pytest.mark.spec(_DRIFT_SPEC, "UC-WDD3")
async def test_prepared_bug_with_matching_diagnosis_upstream_does_not_redispatch_drift_analyzer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await todos_db.add_to_todo(_DRIFT_SLUG)
    state = _prepared_bug_model().model_dump(exclude_none=True)
    await todos_db.write_state(_DRIFT_SLUG, state)
    monkeypatch.setattr("teleclaude.core.next_machine.prepare_steps.compose_agent_guidance", _test_guidance)
    db = _CapturingDb([])

    _, output = await _prepare_dispatch(
        db=cast(Db, db),
        todos_db=todos_db,
        slug=_DRIFT_SLUG,
        cwd=str(project_root),
        phase=PreparePhase.PREPARED,
        state=state,
    )

    assert output == snapshot


@pytest.mark.spec(_DRIFT_SPEC, "UC-WDD4")
async def test_out_of_matrix_substantive_drift_stamps_halt_for_operator_inspection(
    tmp_path: Path,
    snapshot: object,
) -> None:
    outputs = {
        "prepared_input": await _prepare_dispatch_for_substantive_drift_stamp(
            tmp_path,
            phase=PreparePhase.PREPARED,
            artifact=STATE_KEY_INPUT,
        ),
        "blocked_diagnosis": await _prepare_dispatch_for_substantive_drift_stamp(
            tmp_path,
            phase=PreparePhase.BLOCKED,
            artifact=STATE_KEY_DIAGNOSIS,
        ),
        "prepared_unknown": await _prepare_dispatch_for_substantive_drift_stamp(
            tmp_path,
            phase=PreparePhase.PREPARED,
            artifact="operator-note",
        ),
    }

    assert outputs == snapshot


@pytest.mark.spec(_DRIFT_SPEC, "UC-WDD4")
async def test_out_of_matrix_substantive_drift_halt_does_not_recall_prepare(tmp_path: Path) -> None:
    output = await _prepare_dispatch_for_substantive_drift_stamp(
        tmp_path,
        phase=PreparePhase.PREPARED,
        artifact=STATE_KEY_INPUT,
    )

    assert f"telec todo prepare anomalous-prepared-{STATE_KEY_INPUT}" not in output


@pytest.mark.spec(_DRIFT_SPEC, "UC-WDD9")
async def test_prepare_hydration_refreshes_stale_referenced_paths_without_stamp_churn(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    slug = "stale-reference-refresh"
    await todos_db.add_to_todo(slug)
    await todos_db.write_artifact(
        slug,
        ARTIFACT_IMPLEMENTATION_PLAN,
        "Grounding mentions manifests/cli-surface.md, but no contract block declares it.",
    )
    model = _prepared_bug_model()
    entry = model.artifacts.implementation_plan
    entry.produced_at = "2026-06-10T00:00:00+00:00"
    entry.codebase_sha_at_write = "write-sha"
    entry.referenced_paths = [
        "manifests/cli-surface.md",
        "teleclaude/core/next_machine/git_ops.py",
    ]
    entry.dependency_set_at_write = [_dependency_entry("dep", "active")]
    produced_at_before = entry.produced_at
    state = model.model_dump(exclude_none=True)
    await todos_db.write_state(slug, state)
    stamp_before = model.approvals.drift_reviewed[ARTIFACT_IMPLEMENTATION_PLAN].model_copy(deep=True)

    await next_prepare(cast(Db, _CapturingDb([])), slug, str(project_root))

    persisted = await todos_db.read_state(slug)
    assert persisted is not None
    writer = StateWriter(persisted)
    refreshed = writer.state.artifacts.implementation_plan
    assert refreshed.referenced_paths == []
    assert refreshed.async_provenance_complete is True
    assert refreshed.dependency_set_at_write == [_dependency_entry("dep", "active")]
    assert refreshed.produced_at == produced_at_before
    assert writer.state.approvals.drift_reviewed[ARTIFACT_IMPLEMENTATION_PLAN] == stamp_before
    assert derive_artifact_drift(refreshed, None, "", "") == DRIFT_FRESH

    drift = await derive_lifecycle_drift(
        slug,
        writer.state,
        repo_root=str(project_root),
        todos_db=_DependencyReader([_dependency_entry("dep", "delivered")]),
        snippet_digest_fn=lambda _snippet_id: "",
        writer=writer,
    )
    assert collapse_drift(drift)[ARTIFACT_IMPLEMENTATION_PLAN] == DRIFT_FRESH


@pytest.mark.spec(_DRIFT_SPEC, "UC-WDD5")
async def test_prepare_dispatches_drift_analyzer_for_parent_prd_ground_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await todos_db.add_to_todo(_PARENT)
    await todos_db.write_state(
        _PARENT, _approved_parent_model(prd_digest="parent-prd-v2").model_dump(exclude_none=True)
    )
    await todos_db.add_to_todo(_CHILD, after=[_PARENT])
    await todos_db.write_state(_CHILD, _prepared_dependent_with_parent_ground().model_dump(exclude_none=True))
    monkeypatch.setattr("teleclaude.core.next_machine.prepare_steps.compose_agent_guidance", _test_guidance)

    output = await next_prepare(cast(Db, _CapturingDb([])), _CHILD, str(project_root))

    assert output.replace(str(project_root), "<project>") == snapshot


async def test_prepare_hydration_refreshes_declared_referenced_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    slug = "declared-reference-refresh"
    await todos_db.add_to_todo(slug)
    await todos_db.write_artifact(
        slug,
        ARTIFACT_IMPLEMENTATION_PLAN,
        """
```referenced-paths
teleclaude/core/next_machine/git_ops.py
tests/workflow/test_prepare_state_machine.py
```
""",
    )
    model = _prepared_bug_model()
    model.artifacts.implementation_plan.produced_at = "2026-06-10T00:00:00+00:00"
    model.artifacts.implementation_plan.referenced_paths = ["manifests/cli-surface.md"]
    produced_at_before = model.artifacts.implementation_plan.produced_at
    await todos_db.write_state(slug, model.model_dump(exclude_none=True))
    monkeypatch.setattr("teleclaude.core.next_machine.prepare_steps.compose_agent_guidance", _test_guidance)

    await next_prepare(cast(Db, _CapturingDb([])), slug, str(project_root))

    persisted = await todos_db.read_state(slug)
    assert persisted is not None
    writer = StateWriter(persisted)
    assert writer.state.artifacts.implementation_plan.referenced_paths == [
        "teleclaude/core/next_machine/git_ops.py",
        "tests/workflow/test_prepare_state_machine.py",
    ]
    assert writer.state.artifacts.implementation_plan.produced_at == produced_at_before


@pytest.mark.spec(_DRIFT_SPEC, "UC-WDD6")
async def test_work_entry_with_matching_diagnosis_upstream_dispatches_build_started(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: object,
) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await todos_db.add_to_todo(_DRIFT_SLUG)
    await todos_db.write_state(_DRIFT_SLUG, _prepared_bug_model().model_dump(exclude_none=True))
    worktree_cwd = project_root / "trees" / _DRIFT_SLUG
    worktree_cwd.mkdir(parents=True)
    dispatch_phases: list[WorkPhase] = []

    async def _ensure_ready(_cwd: str, _slug: str, _phase_slug: str) -> tuple[str, None]:
        return str(worktree_cwd), None

    async def _dispatch_build_started(**kwargs: object) -> tuple[bool, str]:
        phase = kwargs["phase"]
        assert isinstance(phase, WorkPhase)
        dispatch_phases.append(phase)
        return False, "BUILD_START_DISPATCH: matching-drift-bug"

    monkeypatch.setattr(work_machine, "get_stash_entries", lambda _cwd: [])
    monkeypatch.setattr(work_machine, "_ensure_worktree_ready", _ensure_ready)
    monkeypatch.setattr(work_machine, "_merge_origin_main_into_worktree", lambda _cwd, _slug: "")
    monkeypatch.setattr(work_machine, "get_head_commit", lambda _cwd: "head-sha")
    monkeypatch.setattr(work_machine, "_work_dispatch", _dispatch_build_started)

    output = await next_work(cast(Db, _CapturingDb([])), _DRIFT_SLUG, str(project_root))

    assert dispatch_phases == [WorkPhase.BUILD_STARTED]
    assert output == snapshot


@pytest.mark.spec(_DRIFT_SPEC, "UC-WDD5")
async def test_work_entry_bounces_before_worktree_setup_for_parent_prd_ground_drift(
    tmp_path: Path,
    snapshot: object,
) -> None:
    project_root = tmp_path / "project"
    todos_db = await _project_db(project_root)
    await todos_db.add_to_todo(_PARENT)
    await todos_db.write_state(
        _PARENT, _approved_parent_model(prd_digest="parent-prd-v2").model_dump(exclude_none=True)
    )
    await todos_db.add_to_todo(_CHILD, after=[_PARENT])
    await todos_db.write_state(_CHILD, _prepared_dependent_with_parent_ground().model_dump(exclude_none=True))

    output = await work_machine._check_work_entry_drift(todos_db, _CHILD, str(project_root), _CHILD)

    assert output is not None
    assert output == snapshot
    assert not (project_root / "trees" / _CHILD).exists()


async def _test_guidance(_db: Db) -> str:
    return "agent guidance"
