"""Lifecycle compatibility helpers.

The canonical current-phase source is now ``state["lifecycle_phase"]``. These
helpers remain as compatibility shims for legacy callers that still ask for a
prepare/work projection. When the canonical field is missing, they fall back to
the historical primitive derivation so old rows continue to load.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from teleclaude.core.next_machine._types import DOR_READY_THRESHOLD, PreparePhase, StateValue, WorkPhase
from teleclaude.core.next_machine.build_gates import run_build_gates
from teleclaude.core.next_machine.lifecycle import (
    LifecyclePhase,
    coerce_lifecycle_phase,
    is_prepare_lifecycle_phase,
    is_work_lifecycle_phase,
)
from teleclaude.git import GitCommandError, Repo

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb


GatesChecker = Callable[[str, str], tuple[bool, str]]


def derive_work_phase(
    state: dict[str, StateValue],
    worktree_cwd: str,
    slug: str,
    *,
    gates_checker: GatesChecker = run_build_gates,
) -> WorkPhase:
    """Return the current work projection from canonical lifecycle state."""
    lifecycle = coerce_lifecycle_phase(state.get("lifecycle_phase"))
    if lifecycle is not None and is_work_lifecycle_phase(lifecycle):
        return WorkPhase(lifecycle.value)
    return _derive_work_phase_from_primitives(state, worktree_cwd, slug, gates_checker=gates_checker)


def _derive_work_phase_from_primitives(
    state: dict[str, StateValue],
    worktree_cwd: str,
    slug: str,
    *,
    gates_checker: GatesChecker,
) -> WorkPhase:
    """Primitive-only work-phase derivation.

    Signals (in precedence order):

    - ``finalize.status == "handed_off"`` → :data:`WorkPhase.HANDED_OFF`
    - ``finalize.status == "ready"``      → :data:`WorkPhase.FINALIZE_READY`
    - ``build_review.verdict == "approve"``          → :data:`WorkPhase.REVIEW_APPROVED`
    - ``build_review.verdict == "changes_requested"`` → :data:`WorkPhase.REVIEW_CHANGES_REQUESTED`
    - has build commits + gates pass → :data:`WorkPhase.BUILD_COMPLETE`
    - otherwise                      → :data:`WorkPhase.BUILD_STARTED`
    """
    finalize_raw = state.get("finalize")
    finalize = finalize_raw if isinstance(finalize_raw, dict) else {}
    finalize_status = finalize.get("status", "pending")
    if finalize_status == "handed_off":
        return WorkPhase.HANDED_OFF
    if finalize_status == "ready":
        return WorkPhase.FINALIZE_READY

    build_review_raw = state.get("build_review")
    build_review = build_review_raw if isinstance(build_review_raw, dict) else {}
    verdict = build_review.get("verdict", "")
    if verdict == "approve":
        return WorkPhase.REVIEW_APPROVED
    if verdict == "changes_requested":
        return WorkPhase.REVIEW_CHANGES_REQUESTED

    if not _has_build_commits_beyond_main(worktree_cwd):
        return WorkPhase.BUILD_STARTED
    gates_passed, _ = gates_checker(worktree_cwd, slug)
    if not gates_passed:
        return WorkPhase.BUILD_STARTED
    return WorkPhase.BUILD_COMPLETE


async def derive_prepare_phase(
    state: dict[str, StateValue],
    todos_db: TodosDb,
    slug: str,
) -> PreparePhase:
    """Return the current prepare projection from canonical lifecycle state."""
    lifecycle = coerce_lifecycle_phase(state.get("lifecycle_phase"))
    if lifecycle is not None:
        if is_prepare_lifecycle_phase(lifecycle):
            return PreparePhase(lifecycle.value)
        if lifecycle in WORK_LIFECYCLE_EQUIVALENT_PREPARED:
            return PreparePhase.PREPARED
    return await _derive_prepare_phase_from_primitives(state, todos_db, slug)


async def _derive_prepare_phase_from_primitives(
    state: dict[str, StateValue],
    todos_db: TodosDb,
    slug: str,
) -> PreparePhase:
    """Primitive-only prepare-phase derivation.

    Signals (in precedence order):

    - missing requirements artifact         → :data:`PreparePhase.INPUT_ASSESSMENT`
    - requirements present, no verdict      → :data:`PreparePhase.REQUIREMENTS_REVIEW`
    - requirements approved, no specs stamp → :data:`PreparePhase.TEST_SPEC_BUILD`
    - specs stamped, no spec verdict        → :data:`PreparePhase.TEST_SPEC_REVIEW`
    - spec approved, no plan                → :data:`PreparePhase.PLAN_DRAFTING`
    - plan present, no plan verdict         → :data:`PreparePhase.PLAN_REVIEW`
    - plan approved, DOR < threshold        → :data:`PreparePhase.GATE`
    - DOR passes, grounding invalid         → :data:`PreparePhase.GROUNDING_CHECK`
    - all primitives satisfied              → :data:`PreparePhase.PREPARED`
    """
    req_review_raw = state.get("requirements_review")
    req_review = req_review_raw if isinstance(req_review_raw, dict) else {}
    req_verdict = req_review.get("verdict", "")

    if not await todos_db.artifact_exists(slug, "requirements"):
        # Prepped todos have requirements_review.verdict == "skipped" — they
        # bypass the requirements artifact entirely.
        if req_verdict != "skipped":
            return PreparePhase.INPUT_ASSESSMENT

    if req_verdict not in ("approve", "skipped"):
        return PreparePhase.REQUIREMENTS_REVIEW

    artifacts_raw = state.get("artifacts")
    artifacts = artifacts_raw if isinstance(artifacts_raw, dict) else {}
    test_specs_raw = artifacts.get("test_specs")
    test_specs = test_specs_raw if isinstance(test_specs_raw, dict) else {}
    if not test_specs.get("produced_at"):
        return PreparePhase.TEST_SPEC_BUILD

    spec_review_raw = state.get("test_spec_review")
    spec_review = spec_review_raw if isinstance(spec_review_raw, dict) else {}
    spec_verdict = spec_review.get("verdict", "")
    if spec_verdict not in ("approve", "skipped"):
        return PreparePhase.TEST_SPEC_REVIEW

    plan_review_raw = state.get("plan_review")
    plan_review = plan_review_raw if isinstance(plan_review_raw, dict) else {}
    plan_verdict = plan_review.get("verdict", "")

    if plan_verdict not in ("approve", "skipped"):
        # If plan review hasn't been done, check if the artifact even exists
        if not await todos_db.artifact_exists(slug, "implementation-plan"):
            return PreparePhase.PLAN_DRAFTING
        return PreparePhase.PLAN_REVIEW

    dor_raw = state.get("dor")
    dor = dor_raw if isinstance(dor_raw, dict) else {}
    score_raw = dor.get("score", 0)
    score = score_raw if isinstance(score_raw, int) else 0
    if score < DOR_READY_THRESHOLD:
        return PreparePhase.GATE

    grounding_raw = state.get("grounding")
    grounding = grounding_raw if isinstance(grounding_raw, dict) else {}
    if not grounding.get("valid"):
        return PreparePhase.GROUNDING_CHECK

    return PreparePhase.PREPARED


async def is_prepared(state: dict[str, StateValue], todos_db: TodosDb, slug: str) -> bool:
    """Return True when the prepare lifecycle has reached the PREPARED terminal phase."""
    lifecycle = coerce_lifecycle_phase(state.get("lifecycle_phase"))
    if lifecycle is not None:
        return lifecycle == LifecyclePhase.PREPARED or is_work_lifecycle_phase(lifecycle)
    return (await derive_prepare_phase(state, todos_db, slug)) == PreparePhase.PREPARED


WORK_LIFECYCLE_EQUIVALENT_PREPARED: frozenset[LifecyclePhase] = frozenset(
    {
        LifecyclePhase.BUILD_STARTED,
        LifecyclePhase.BUILD_COMPLETE,
        LifecyclePhase.REVIEW_CHANGES_REQUESTED,
        LifecyclePhase.REVIEW_APPROVED,
        LifecyclePhase.FINALIZE_READY,
        LifecyclePhase.HANDED_OFF,
    }
)


def _has_build_commits_beyond_main(worktree_cwd: str) -> bool:
    """Return True when the worktree branch has commits ahead of main."""
    try:
        repo = Repo(worktree_cwd)
        base = repo.git.merge_base("HEAD", "main").strip()
        log_output = repo.git.log("--oneline", f"{base}..HEAD")
        return bool(log_output.strip())
    except (GitCommandError, OSError):
        return False


__all__ = [
    "GatesChecker",
    "derive_prepare_phase",
    "derive_work_phase",
    "is_prepared",
]
