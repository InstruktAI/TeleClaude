"""Workflow-owned transaction coordination for documentation marker reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from instrukt_ai_logging import get_logger

from teleclaude.core.next_machine.delivery import _run_git_cmd, git_name_set, parse_git_porcelain_paths
from teleclaude.docs_reconcile import (
    ReconciliationFault,
    ReconciliationMode,
    ReconciliationPlan,
    apply_reconciliation_plan,
    plan_snippet_reconciliation,
    restore_reconciliation_plan,
    reverse_reconciliation_plan,
)

logger = get_logger(__name__)

RECONCILIATION_REQUESTED_EVENT = "workflow.marker_reconciliation.requested"
RECONCILIATION_FINISHED_EVENT = "workflow.marker_reconciliation.finished"
GIT_STATUS_ARGS = ("status", "--porcelain", "--")
GIT_ADD_ARGS = ("add", "--")
GIT_CACHED_NAME_ARGS = ("diff", "--cached", "--name-only")
GIT_RESTORE_STAGED_ARGS = ("restore", "--staged", "--")
GIT_COMMIT_ARGS = ("commit", "-m")
COMMIT_MESSAGE_TEMPLATE = "chore(docs): reconcile lifecycle markers for {slug}"
RECONCILIATION_REASON = "lifecycle_marker_reconciliation"
NOOP_REASON = "no_pending_material"
DIRTY_REASON = "affected_path_is_dirty"
STAGE_REASON = "staging_failed"
STAGED_SET_REASON = "staged_set_mismatch"
COMMIT_REASON = "commit_failed"


class MarkerMoment(StrEnum):
    """Lifecycle doors that may move pending documentation identity."""

    DELIVER = "deliver"
    ABANDON = "abandon"
    RENAME = "rename"
    SPLIT = "split"
    REGROUP = "regroup"
    REACTIVATE = "reactivate"
    RETRACT = "retract"
    KICKBACK = "kickback"


class MarkerOutcome(StrEnum):
    """One terminal outcome for every reconciliation opportunity."""

    APPLIED = "applied"
    NOOP = "noop"
    FAULTED = "faulted"


@dataclass(frozen=True)
class MarkerReceipt:
    """Typed proof that a lifecycle caller may persist its succeeding state transition."""

    transition_id: str
    slug: str
    moment: MarkerMoment
    outcome: MarkerOutcome
    plan: ReconciliationPlan | None
    commit: str | None
    reason: str

    @property
    def succeeded(self) -> bool:
        """Whether this receipt authorizes the following lifecycle mutation."""
        return self.outcome in (MarkerOutcome.APPLIED, MarkerOutcome.NOOP)


def _mode_for_moment(moment: MarkerMoment) -> ReconciliationMode | None:
    """Map public lifecycle moments to their mechanical documentation semantics."""
    if moment is MarkerMoment.DELIVER:
        return ReconciliationMode.DELIVER
    if moment is MarkerMoment.ABANDON:
        return ReconciliationMode.ABANDON
    if moment in (MarkerMoment.RENAME, MarkerMoment.SPLIT):
        return ReconciliationMode.RENAME
    return None


def _relative_paths(plan: ReconciliationPlan) -> tuple[str, ...]:
    """Return a deterministic exact pathset for Git preflight and staging."""
    return tuple(dict.fromkeys(write.relative_path for write in plan.writes))


def _fault_receipt(
    transition_id: str,
    slug: str,
    moment: MarkerMoment,
    *,
    reason: str,
    fault: ReconciliationFault | None = None,
) -> MarkerReceipt:
    """Emit and return the single terminal fault for one lifecycle opportunity."""
    if fault is not None:
        logger.error(
            "Marker reconciliation faulted",
            event=RECONCILIATION_FINISHED_EVENT,
            transition_id=transition_id,
            todo_id=slug,
            slug=slug,
            moment=moment.value,
            outcome=MarkerOutcome.FAULTED.value,
            reason=reason,
            relative_path=fault.relative_path,
            line=fault.line,
        )
    else:
        logger.error(
            "Marker reconciliation faulted",
            event=RECONCILIATION_FINISHED_EVENT,
            transition_id=transition_id,
            todo_id=slug,
            slug=slug,
            moment=moment.value,
            outcome=MarkerOutcome.FAULTED.value,
            reason=reason,
        )
    return MarkerReceipt(transition_id, slug, moment, MarkerOutcome.FAULTED, None, None, reason)


def _restore_index(project_root: Path, paths: tuple[str, ...]) -> None:
    """Unstage only the reconciliation pathset during transactional compensation."""
    if paths:
        _run_git_cmd([*GIT_RESTORE_STAGED_ARGS, *paths], cwd=str(project_root))


def _preflight_plan(project_root: Path, slug: str, plan: ReconciliationPlan) -> set[str]:
    """Refuse foreign dirt before this coordinator writes its own plan."""
    paths = _relative_paths(plan)
    if not paths:
        return set()
    status_code, status_output, status_error = _run_git_cmd([*GIT_STATUS_ARGS, *paths], cwd=str(project_root))
    if status_code != 0:
        raise ReconciliationFault(slug, "", 0, status_error)
    if parse_git_porcelain_paths(status_output) & set(paths):
        raise ReconciliationFault(slug, "", 0, DIRTY_REASON)
    staged_before = git_name_set(project_root, list(GIT_CACHED_NAME_ARGS))
    if staged_before is None:
        raise ReconciliationFault(slug, "", 0, STAGE_REASON)
    return staged_before


def _commit_plan(project_root: Path, slug: str, plan: ReconciliationPlan, staged_before: set[str]) -> str | None:
    """Stage and commit exactly a clean preflighted reconciliation pathset."""
    paths = _relative_paths(plan)
    if not paths:
        return None
    add_code, _add_output, add_error = _run_git_cmd([*GIT_ADD_ARGS, *paths], cwd=str(project_root))
    if add_code != 0:
        _restore_index(project_root, paths)
        raise ReconciliationFault(slug, "", 0, add_error or STAGE_REASON)
    staged_after = git_name_set(project_root, list(GIT_CACHED_NAME_ARGS))
    if staged_after != staged_before | set(paths):
        _restore_index(project_root, paths)
        raise ReconciliationFault(slug, "", 0, STAGED_SET_REASON)
    message = COMMIT_MESSAGE_TEMPLATE.format(slug=slug)
    commit_code, commit_output, commit_error = _run_git_cmd(
        [*GIT_COMMIT_ARGS, message, "--", *paths], cwd=str(project_root)
    )
    if commit_code != 0:
        _restore_index(project_root, paths)
        raise ReconciliationFault(slug, "", 0, commit_error or COMMIT_REASON)
    return commit_output.strip()


def reconcile_lifecycle_markers(
    project_root: Path,
    slug: str,
    moment: MarkerMoment,
    *,
    new_slug: str | None = None,
) -> MarkerReceipt:
    """Reconcile one lifecycle door or return its sole typed terminal receipt."""
    transition_id = str(uuid4())
    logger.info(
        "Marker reconciliation requested",
        event=RECONCILIATION_REQUESTED_EVENT,
        transition_id=transition_id,
        todo_id=slug,
        slug=slug,
        moment=moment.value,
    )
    mode = _mode_for_moment(moment)
    if mode is None:
        reason = (
            "pending_preserved"
            if moment in (MarkerMoment.REGROUP, MarkerMoment.RETRACT, MarkerMoment.KICKBACK)
            else NOOP_REASON
        )
        logger.info(
            "Marker reconciliation finished",
            event=RECONCILIATION_FINISHED_EVENT,
            transition_id=transition_id,
            todo_id=slug,
            slug=slug,
            moment=moment.value,
            outcome=MarkerOutcome.NOOP.value,
            reason=reason,
        )
        return MarkerReceipt(transition_id, slug, moment, MarkerOutcome.NOOP, None, None, reason)
    try:
        plan = plan_snippet_reconciliation(project_root, slug, mode, new_slug=new_slug)
        if not plan.writes:
            logger.info(
                "Marker reconciliation finished",
                event=RECONCILIATION_FINISHED_EVENT,
                transition_id=transition_id,
                todo_id=slug,
                slug=slug,
                moment=moment.value,
                outcome=MarkerOutcome.NOOP.value,
                reason=NOOP_REASON,
            )
            return MarkerReceipt(transition_id, slug, moment, MarkerOutcome.NOOP, plan, None, NOOP_REASON)
        staged_before = _preflight_plan(project_root, slug, plan)
        apply_reconciliation_plan(plan)
        try:
            commit = _commit_plan(project_root, slug, plan, staged_before)
        except ReconciliationFault:
            restore_reconciliation_plan(plan)
            raise
    except ReconciliationFault as fault:
        return _fault_receipt(transition_id, slug, moment, reason=fault.reason, fault=fault)
    logger.info(
        "Marker reconciliation finished",
        event=RECONCILIATION_FINISHED_EVENT,
        transition_id=transition_id,
        todo_id=slug,
        slug=slug,
        moment=moment.value,
        outcome=MarkerOutcome.APPLIED.value,
        reason=RECONCILIATION_REASON,
        changed_path_count=len(plan.writes),
    )
    return MarkerReceipt(transition_id, slug, moment, MarkerOutcome.APPLIED, plan, commit, RECONCILIATION_REASON)


def restore_lifecycle_markers(project_root: Path, slug: str, plan: ReconciliationPlan) -> MarkerReceipt:
    """Restore a removed todo's exact pending-documentation snapshot."""
    restored = reverse_reconciliation_plan(plan)
    transition_id = str(uuid4())
    logger.info(
        "Marker reconciliation requested",
        event=RECONCILIATION_REQUESTED_EVENT,
        transition_id=transition_id,
        todo_id=slug,
        slug=slug,
        moment=MarkerMoment.REACTIVATE.value,
    )
    try:
        staged_before = _preflight_plan(project_root, slug, restored)
        apply_reconciliation_plan(restored)
        try:
            commit = _commit_plan(project_root, slug, restored, staged_before)
        except ReconciliationFault:
            restore_reconciliation_plan(restored)
            raise
    except ReconciliationFault as fault:
        return _fault_receipt(transition_id, slug, MarkerMoment.REACTIVATE, reason=fault.reason, fault=fault)
    logger.info(
        "Marker reconciliation finished",
        event=RECONCILIATION_FINISHED_EVENT,
        transition_id=transition_id,
        todo_id=slug,
        slug=slug,
        moment=MarkerMoment.REACTIVATE.value,
        outcome=MarkerOutcome.APPLIED.value,
        reason=RECONCILIATION_REASON,
        changed_path_count=len(restored.writes),
    )
    return MarkerReceipt(
        transition_id,
        slug,
        MarkerMoment.REACTIVATE,
        MarkerOutcome.APPLIED,
        restored,
        commit,
        RECONCILIATION_REASON,
    )
