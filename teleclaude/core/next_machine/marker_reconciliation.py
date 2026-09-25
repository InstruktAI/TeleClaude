"""Workflow-owned transaction coordination for documentation marker reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryDirectory
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
GIT_HEAD_ARGS = ("rev-parse", "--verify", "HEAD")
GIT_REV_LIST_ARGS = ("rev-list", "--reverse")
GIT_COMMIT_MESSAGE_ARGS = ("show", "-s", "--format=%B")
GIT_HASH_OBJECT_ARGS = ("hash-object",)
GIT_LS_TREE_ARGS = ("ls-tree", "-z")
GIT_REVISION_RANGE_TEMPLATE = "{previous_head}..HEAD"
GIT_PATH_OPTION_TEMPLATE = "--path={relative_path}"
GIT_TREE_FIELD_SEPARATOR = "\t"
GIT_TREE_RECORD_SEPARATOR = "\0"
GIT_BLOB_OBJECT_TYPE = "blob"
UTF8_ENCODING = "utf-8"
COMMIT_MESSAGE_TEMPLATE = "chore(docs): reconcile lifecycle markers for {slug}"
COMMIT_MESSAGE_WITH_TRANSITION_TEMPLATE = "{subject}\n\n{trailer}"
TRANSITION_TRAILER_KEY = "Reconciliation-Transition"
TRANSITION_TRAILER_TEMPLATE = "{key}: {transition_id}"
COMMIT_RESOLUTION_EVENT = "workflow.marker_reconciliation.commit_resolution"
COMMIT_FAILURE_LOG_MESSAGE = "Marker reconciliation commit command reported failure"
MULTIPLE_TRANSITION_COMMITS_REASON = "multiple commits carry the transition id"
COMMIT_PATH_NOT_BLOB_REASON = "commit path did not resolve to a blob"
COMMIT_PATH_MULTIPLE_ENTRIES_REASON = "commit path resolved to multiple tree entries"
COMMIT_TREE_MISMATCH_TEMPLATE = "recorded tree differs from rendered path {relative_path}"
RECONCILIATION_REASON = "lifecycle_marker_reconciliation"
NOOP_REASON = "no_pending_material"
DIRTY_REASON = "affected_path_is_dirty"
STAGE_REASON = "staging_failed"
STAGED_SET_REASON = "staged_set_mismatch"
COMMIT_REASON = "commit_failed"
UNRESOLVED_COMMIT_REASON = "commit_outcome_unresolved_sources_restored"
UNIDENTIFIED_COMMIT_REASON = "recorded_commit_could_not_be_identified"


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


class CommitResolution(StrEnum):
    """Repository evidence for the result of one reconciliation commit attempt."""

    LANDED = "landed"
    NOT_LANDED = "not_landed"
    UNRESOLVED = "unresolved"


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


@dataclass(frozen=True)
class _CommitResolution:
    """Read-only resolution of one attempt's commit in its reachable range."""

    outcome: CommitResolution
    commit: str | None = None
    error: str = ""


@dataclass(frozen=True)
class _CommitPlanResult:
    """Commit outcome and whether its caller must restore the applied sources."""

    commit: str | None
    fault: ReconciliationFault | None = None
    restore_sources: bool = False


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


def _expected_blob_id(
    project_root: Path,
    relative_path: str,
    content: str,
    temporary_root: Path,
    index: int,
) -> tuple[str | None, str]:
    """Hash rendered bytes using the clean filter selected for their Git path."""
    temporary_file = temporary_root / str(index)
    try:
        temporary_file.write_bytes(content.encode(UTF8_ENCODING))
    except OSError as write_error:
        return None, str(write_error)
    code, output, error = _run_git_cmd(
        [*GIT_HASH_OBJECT_ARGS, GIT_PATH_OPTION_TEMPLATE.format(relative_path=relative_path), str(temporary_file)],
        cwd=str(project_root),
    )
    if code != 0:
        return None, error
    return output.strip(), ""


def _blob_at_commit(project_root: Path, commit: str, relative_path: str) -> tuple[str | None, str]:
    """Read one exact path's blob identity from a commit tree."""
    code, output, error = _run_git_cmd([*GIT_LS_TREE_ARGS, commit, "--", relative_path], cwd=str(project_root))
    if code != 0:
        return None, error
    object_ids: list[str] = []
    for record in output.split(GIT_TREE_RECORD_SEPARATOR):
        metadata, separator, path = record.partition(GIT_TREE_FIELD_SEPARATOR)
        if not separator or path != relative_path:
            continue
        fields = metadata.split()
        if len(fields) != 3 or fields[1] != GIT_BLOB_OBJECT_TYPE:
            return None, COMMIT_PATH_NOT_BLOB_REASON
        object_ids.append(fields[2])
    if len(object_ids) > 1:
        return None, COMMIT_PATH_MULTIPLE_ENTRIES_REASON
    return (object_ids[0] if object_ids else None), ""


def _resolve_commit(
    project_root: Path,
    plan: ReconciliationPlan,
    transition_id: str,
    previous_head: str,
) -> _CommitResolution:
    """Identify the attempt's commit and verify its tree matches the plan."""
    code, output, error = _run_git_cmd(
        [
            *GIT_REV_LIST_ARGS,
            GIT_REVISION_RANGE_TEMPLATE.format(previous_head=previous_head),
        ],
        cwd=str(project_root),
    )
    if code != 0:
        return _CommitResolution(CommitResolution.UNRESOLVED, error=error)

    attempt_commits: list[str] = []
    for commit_id in (line.strip() for line in output.splitlines()):
        if not commit_id:
            continue
        message_code, message, message_error = _run_git_cmd(
            [*GIT_COMMIT_MESSAGE_ARGS, commit_id], cwd=str(project_root)
        )
        if message_code != 0:
            return _CommitResolution(CommitResolution.UNRESOLVED, error=message_error)
        expected_trailer = TRANSITION_TRAILER_TEMPLATE.format(
            key=TRANSITION_TRAILER_KEY,
            transition_id=transition_id,
        )
        if expected_trailer in message.splitlines():
            attempt_commits.append(commit_id)

    if not attempt_commits:
        return _CommitResolution(CommitResolution.NOT_LANDED)
    if len(attempt_commits) != 1:
        return _CommitResolution(CommitResolution.UNRESOLVED, error=MULTIPLE_TRANSITION_COMMITS_REASON)

    commit_id = attempt_commits[0]
    try:
        with TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            for index, write in enumerate(plan.writes):
                expected_blob: str | None = None
                if write.rendered_content is not None:
                    expected_blob, hash_error = _expected_blob_id(
                        project_root,
                        write.relative_path,
                        write.rendered_content,
                        temporary_root,
                        index,
                    )
                    if hash_error:
                        return _CommitResolution(CommitResolution.UNRESOLVED, error=hash_error)
                actual_blob, tree_error = _blob_at_commit(project_root, commit_id, write.relative_path)
                if tree_error:
                    return _CommitResolution(CommitResolution.UNRESOLVED, error=tree_error)
                if actual_blob != expected_blob:
                    return _CommitResolution(
                        CommitResolution.UNRESOLVED,
                        error=COMMIT_TREE_MISMATCH_TEMPLATE.format(relative_path=write.relative_path),
                    )
    except OSError as temporary_error:
        return _CommitResolution(CommitResolution.UNRESOLVED, error=str(temporary_error))
    return _CommitResolution(CommitResolution.LANDED, commit=commit_id)


def _commit_plan(
    project_root: Path,
    slug: str,
    plan: ReconciliationPlan,
    staged_before: set[str],
    transition_id: str,
) -> _CommitPlanResult:
    """Stage and commit the exact pathset, resolving uncertain command results."""
    paths = _relative_paths(plan)
    if not paths:
        return _CommitPlanResult(None)
    add_code, _add_output, add_error = _run_git_cmd([*GIT_ADD_ARGS, *paths], cwd=str(project_root))
    if add_code != 0:
        _restore_index(project_root, paths)
        raise ReconciliationFault(slug, "", 0, add_error or STAGE_REASON)
    staged_after = git_name_set(project_root, list(GIT_CACHED_NAME_ARGS))
    if staged_after != staged_before | set(paths):
        _restore_index(project_root, paths)
        raise ReconciliationFault(slug, "", 0, STAGED_SET_REASON)
    previous_head_code, previous_head_output, previous_head_error = _run_git_cmd(
        list(GIT_HEAD_ARGS), cwd=str(project_root)
    )
    if previous_head_code != 0:
        _restore_index(project_root, paths)
        raise ReconciliationFault(slug, "", 0, previous_head_error or COMMIT_REASON)
    previous_head = previous_head_output.strip()
    if not previous_head:
        _restore_index(project_root, paths)
        raise ReconciliationFault(slug, "", 0, COMMIT_REASON)
    message = COMMIT_MESSAGE_WITH_TRANSITION_TEMPLATE.format(
        subject=COMMIT_MESSAGE_TEMPLATE.format(slug=slug),
        trailer=TRANSITION_TRAILER_TEMPLATE.format(
            key=TRANSITION_TRAILER_KEY,
            transition_id=transition_id,
        ),
    )
    commit_code, _commit_output, commit_error = _run_git_cmd(
        [*GIT_COMMIT_ARGS, message, "--", *paths], cwd=str(project_root)
    )
    resolution = _resolve_commit(project_root, plan, transition_id, previous_head)
    if commit_code != 0:
        logger.warning(
            COMMIT_FAILURE_LOG_MESSAGE,
            event=COMMIT_RESOLUTION_EVENT,
            transition_id=transition_id,
            slug=slug,
            error=commit_error,
            resolution=resolution.outcome.value,
            commit=resolution.commit,
        )
        if resolution.outcome is CommitResolution.LANDED:
            return _CommitPlanResult(resolution.commit)
        _restore_index(project_root, paths)
        if resolution.outcome is CommitResolution.NOT_LANDED:
            return _CommitPlanResult(
                None,
                ReconciliationFault(slug, "", 0, commit_error or COMMIT_REASON),
                restore_sources=True,
            )
        return _CommitPlanResult(
            None,
            ReconciliationFault(slug, "", 0, UNRESOLVED_COMMIT_REASON),
            restore_sources=True,
        )
    if resolution.outcome is not CommitResolution.LANDED or resolution.commit is None:
        return _CommitPlanResult(
            None,
            ReconciliationFault(slug, "", 0, UNIDENTIFIED_COMMIT_REASON),
        )
    return _CommitPlanResult(resolution.commit)


def _apply_commit_with_compensation(
    project_root: Path,
    slug: str,
    plan: ReconciliationPlan,
    transition_id: str,
) -> str | None:
    """Apply one plan and restore its sources if its commit step faults."""
    staged_before = _preflight_plan(project_root, slug, plan)
    apply_reconciliation_plan(plan)
    try:
        result = _commit_plan(project_root, slug, plan, staged_before, transition_id)
    except ReconciliationFault:
        restore_reconciliation_plan(plan)
        raise
    if result.fault is not None:
        if result.restore_sources:
            restore_reconciliation_plan(plan)
        raise result.fault
    return result.commit


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
        commit = _apply_commit_with_compensation(project_root, slug, plan, transition_id)
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
        commit=commit,
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
        commit = _apply_commit_with_compensation(project_root, slug, restored, transition_id)
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
        commit=commit,
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
