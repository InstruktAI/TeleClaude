"""Workflow-owned transaction coordination for documentation marker reconciliation."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from instrukt_ai_logging import get_logger

from teleclaude.core.next_machine.delivery import (
    GIT_COMMAND_TIMEOUT_SECONDS,
    GIT_TIMEOUT_ERROR_TEMPLATE,
    _run_git_cmd,
    git_name_set,
    parse_git_porcelain_paths,
)
from teleclaude.core.next_machine.marker_fold_evidence import (
    DEFAULT_FILE_MODE,
    GIT_PATH_OPTION_TEMPLATE,
    FoldResidue,
    GitTreeEntry,
    expected_blob_id,
    residue_is_intact,
    tree_entry_at_commit,
)
from teleclaude.docs_reconcile import (
    ReconciliationFault,
    ReconciliationMode,
    ReconciliationPlan,
    ReconciliationWrite,
    apply_reconciliation_plan,
    iter_reconciliation_roots,
    plan_snippet_reconciliation,
    restore_reconciliation_plan,
    reverse_reconciliation_plan,
)
from teleclaude.git import GIT_EXECUTABLE
from teleclaude.git_lock import wait_for_index_lock_clear
from teleclaude.quality.gate import FormatGateOutcome, format_paths_for_commit_gate
from teleclaude.runtime.command_runner import run_process_group_command

logger = get_logger(__name__)

RECONCILIATION_REQUESTED_EVENT = "workflow.marker_reconciliation.requested"
RECONCILIATION_FINISHED_EVENT = "workflow.marker_reconciliation.finished"
GIT_STATUS_ARGS = ("status", "--porcelain", "--")
GIT_SNIPPET_STATUS_ARGS = ("status", "--porcelain", "--untracked-files=all", "--no-renames", "--")
GIT_ADD_ARGS = ("add", "--")
GIT_CACHED_NAME_ARGS = ("diff", "--cached", "--name-only", "--no-renames")
GIT_UNSTAGE_PATHS_ARGS = ("reset", "-q", "--")
GIT_COMMIT_ARGS = ("commit", "-m")
GIT_HEAD_ARGS = ("rev-parse", "--verify", "HEAD")
GIT_REV_LIST_ARGS = ("rev-list", "--reverse")
GIT_COMMIT_MESSAGE_ARGS = ("show", "-s", "--format=%B")
GIT_CAT_FILE_FILTERS_ARGS = ("cat-file", "--filters")
GIT_FILE_MODE_CONFIG_ARGS = ("config", "--bool", "--get", "core.fileMode")
GIT_HEAD = "HEAD"
GIT_REVISION_RANGE_TEMPLATE = "{previous_head}..HEAD"
GIT_HEAD_PATH_TEMPLATE = "HEAD:{relative_path}"
UTF8_ENCODING = "utf-8"
EMPTY_ERROR = ""
EMPTY_PATH = ""
GIT_FALSE_VALUE = "false"
COMMITTED_VIEW_REASON = "committed_view_unavailable"
COMMITTED_VIEW_ERROR_TEMPLATE = "{reason}: {error}"
COMMIT_MESSAGE_TEMPLATE = "chore(docs): reconcile lifecycle markers for {slug}"
COMMIT_MESSAGE_WITH_TRANSITION_TEMPLATE = "{subject}\n\n{trailer}"
TRANSITION_TRAILER_KEY = "Reconciliation-Transition"
TRANSITION_TRAILER_TEMPLATE = "{key}: {transition_id}"
COMMIT_RESOLUTION_EVENT = "workflow.marker_reconciliation.commit_resolution"
COMMIT_FAILURE_LOG_MESSAGE = "Marker reconciliation commit command reported failure"
MULTIPLE_TRANSITION_COMMITS_REASON = "multiple commits carry the transition id"
COMMIT_TREE_MISMATCH_TEMPLATE = "recorded tree differs from rendered path {relative_path}"
FORMAT_FAILURE_REASON_TEMPLATE = "native format target failed for grading home(s): {homes}"
FORMAT_SNAPSHOT_FAILURE_TEMPLATE = "formatted content could not be identified for {relative_path}: {error}"
RECONCILIATION_REASON = "lifecycle_marker_reconciliation"
NOOP_REASON = "no_pending_material"
DIRTY_REASON = "affected_path_is_dirty"
STAGE_REASON = "staging_failed"
STAGED_SET_REASON = "staged_set_mismatch"
COMMIT_REASON = "commit_failed"
UNRESOLVED_COMMIT_REASON = "commit_outcome_unresolved_sources_restored"
UNIDENTIFIED_COMMIT_REASON = "recorded_commit_could_not_be_identified"
INDEX_RESTORE_REASON_TEMPLATE = "index_restore_failed: {error}"


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


class _IndexRestoreFault(ReconciliationFault):
    """The index rollback failed; the applied sources stay in place so the staged state is not split from them."""


@dataclass(frozen=True)
class _IndexRestore:
    """Outcome of one index rollback: whether the pathset was unstaged, and git's error when it was not."""

    restored: bool
    error: str = EMPTY_ERROR


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


@dataclass(frozen=True)
class _ApplyCommitOutcome:
    """The normalized commit plan, commit id, and formatter path count."""

    plan: ReconciliationPlan
    commit: str | None
    normalized_path_count: int = 0


@dataclass
class _FormatAttempt:
    """Mutable transaction snapshot updated even when formatting raises."""

    plan: ReconciliationPlan
    apply_plan: ReconciliationPlan
    residue: tuple[FoldResidue, ...]
    normalized_path_count: int
    outcome: FormatGateOutcome
    snapshot_error: str


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


def _unmodified_output(output: str) -> str:
    return output


def _run_commit(project_root: Path, args: list[str]) -> tuple[int, str]:
    """Run the hook-bearing commit under the git command bound; return its exit code and failure evidence.

    On expiry the runner terminates git's process group so git releases its own index lock.
    """
    result = run_process_group_command(
        [GIT_EXECUTABLE, *args],
        project_root,
        timeout_seconds=GIT_COMMAND_TIMEOUT_SECONDS,
        capture_output=_unmodified_output,
    )
    if result.timed_out:
        return 1, GIT_TIMEOUT_ERROR_TEMPLATE.format(timeout=GIT_COMMAND_TIMEOUT_SECONDS)
    return result.exit_code, result.output_tail or EMPTY_ERROR


def _restore_index(project_root: Path, paths: tuple[str, ...]) -> _IndexRestore:
    """Unstage only the reconciliation pathset; a refused unstage clears a holder-less index lock and retries once.

    A path git does not know has nothing to unstage, so it never refuses the rest of the set.
    """
    if not paths:
        return _IndexRestore(True)
    args = [*GIT_UNSTAGE_PATHS_ARGS, *paths]
    code, _output, error = _run_git_cmd(args, cwd=str(project_root))
    if code != 0:
        wait_for_index_lock_clear(project_root)
        code, _output, error = _run_git_cmd(args, cwd=str(project_root))
    return _IndexRestore(code == 0, error)


def _preflight_plan(
    project_root: Path,
    slug: str,
    plan: ReconciliationPlan,
    *,
    allowed_dirty_paths: frozenset[str] = frozenset(),
) -> set[str]:
    """Refuse foreign dirt before this coordinator writes its own plan."""
    paths = _relative_paths(plan)
    if not paths:
        return set()
    status_code, status_output, status_error = _run_git_cmd([*GIT_STATUS_ARGS, *paths], cwd=str(project_root))
    if status_code != 0:
        raise ReconciliationFault(slug, "", 0, status_error)
    dirty_paths = parse_git_porcelain_paths(status_output) & set(paths)
    if dirty_paths - allowed_dirty_paths:
        raise ReconciliationFault(slug, "", 0, DIRTY_REASON)
    staged_before = git_name_set(project_root, list(GIT_CACHED_NAME_ARGS))
    if staged_before is None:
        raise ReconciliationFault(slug, "", 0, STAGE_REASON)
    return staged_before


def _file_mode_enabled(project_root: Path, slug: str) -> bool:
    """Resolve the repository's effective executable-bit tracking setting."""
    code, output, error = _run_git_cmd(list(GIT_FILE_MODE_CONFIG_ARGS), cwd=str(project_root))
    if code == 1 and not output.strip():
        return True
    if code != 0:
        reason = COMMITTED_VIEW_ERROR_TEMPLATE.format(
            reason=COMMITTED_VIEW_REASON,
            error=error or STAGE_REASON,
        )
        raise ReconciliationFault(slug, EMPTY_PATH, 0, reason)
    return output.strip() != GIT_FALSE_VALUE


def _raise_dirty_path(slug: str, write: ReconciliationWrite) -> None:
    """Raise the existing fail-closed result for unattributable path content."""
    raise ReconciliationFault(slug, write.relative_path, write.line, DIRTY_REASON)


def _remove_temporary_symlinks(temporary_root: Path) -> None:
    """Remove copied symlinks without traversing or mutating their targets."""
    pending_directories = [temporary_root]
    while pending_directories:
        directory = pending_directories.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                candidate = Path(entry.path)
                if entry.is_symlink():
                    candidate.unlink()
                elif entry.is_dir(follow_symlinks=False):
                    pending_directories.append(candidate)


def _reconciliation_transaction_plans(
    project_root: Path,
    slug: str,
    mode: ReconciliationMode,
    new_slug: str | None,
    working_plan: ReconciliationPlan,
) -> tuple[ReconciliationPlan, ReconciliationPlan, tuple[FoldResidue, ...]]:
    """Separate safe working-tree writes from this slug's committed-view residue."""
    reconciliation_roots = iter_reconciliation_roots(project_root)
    reconciliation_root_paths = tuple(str(root.relative_to(project_root)) for root in reconciliation_roots)
    status_code, status_output, status_error = _run_git_cmd(
        [*GIT_SNIPPET_STATUS_ARGS, *reconciliation_root_paths], cwd=str(project_root)
    )
    if status_code != 0:
        reason = COMMITTED_VIEW_ERROR_TEMPLATE.format(
            reason=COMMITTED_VIEW_REASON,
            error=status_error or STAGE_REASON,
        )
        raise ReconciliationFault(slug, EMPTY_PATH, 0, reason)
    dirty_paths = parse_git_porcelain_paths(status_output)
    if not dirty_paths:
        return working_plan, working_plan, ()

    working_writes = {write.relative_path: write for write in working_plan.writes}
    apply_writes: list[ReconciliationWrite] = []
    residue: list[FoldResidue] = []
    transaction_writes: list[ReconciliationWrite] = []
    try:
        with TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            for reconciliation_root in reconciliation_roots:
                if reconciliation_root.is_symlink():
                    continue
                relative_root = reconciliation_root.relative_to(project_root)
                shutil.copytree(
                    reconciliation_root,
                    temporary_root / relative_root,
                    dirs_exist_ok=True,
                    symlinks=True,
                )
            _remove_temporary_symlinks(temporary_root)

            head_entries: dict[str, GitTreeEntry | None] = {}
            for relative_path in sorted(dirty_paths):
                head_entry, tree_error = tree_entry_at_commit(project_root, GIT_HEAD, relative_path)
                if tree_error:
                    reason = COMMITTED_VIEW_ERROR_TEMPLATE.format(reason=COMMITTED_VIEW_REASON, error=tree_error)
                    raise ReconciliationFault(slug, relative_path, 0, reason)
                head_entries[relative_path] = head_entry
                temporary_path = temporary_root / relative_path
                if head_entry is None:
                    temporary_path.unlink(missing_ok=True)
                    continue
                cat_file_code, content, cat_file_error = _run_git_cmd(
                    [
                        *GIT_CAT_FILE_FILTERS_ARGS,
                        GIT_PATH_OPTION_TEMPLATE.format(relative_path=relative_path),
                        GIT_HEAD_PATH_TEMPLATE.format(relative_path=relative_path),
                    ],
                    cwd=str(project_root),
                    preserve_stdout_newlines=True,
                )
                if cat_file_code != 0:
                    reason = COMMITTED_VIEW_ERROR_TEMPLATE.format(
                        reason=COMMITTED_VIEW_REASON,
                        error=cat_file_error or STAGE_REASON,
                    )
                    raise ReconciliationFault(slug, relative_path, 0, reason)
                temporary_path.parent.mkdir(parents=True, exist_ok=True)
                temporary_path.write_bytes(content.encode(UTF8_ENCODING))

            committed_view_plan = plan_snippet_reconciliation(
                temporary_root,
                slug,
                mode,
                new_slug=new_slug,
            )
            committed_writes = tuple(
                ReconciliationWrite(
                    path=project_root / write.relative_path,
                    relative_path=write.relative_path,
                    original_content=write.original_content,
                    rendered_content=write.rendered_content,
                    line=write.line,
                    carrier=write.carrier,
                    reason=write.reason,
                )
                for write in committed_view_plan.writes
            )
            file_mode_enabled = _file_mode_enabled(project_root, slug)
            for write in committed_writes:
                working_write = working_writes.pop(write.relative_path, None)
                if write.relative_path not in dirty_paths:
                    if working_write is not None and (
                        working_write.original_content != write.original_content
                        or working_write.rendered_content != write.rendered_content
                    ):
                        _raise_dirty_path(slug, write)
                    applied_write = working_write or write
                    apply_writes.append(applied_write)
                    transaction_writes.append(applied_write)
                    continue

                if working_write is not None:
                    _raise_dirty_path(slug, write)
                fold_blob: str | None = None
                if write.rendered_content is not None:
                    fold_blob, hash_error = expected_blob_id(
                        project_root,
                        write.relative_path,
                        write.rendered_content,
                        temporary_root,
                        len(residue),
                    )
                    if hash_error or fold_blob is None:
                        reason = COMMITTED_VIEW_ERROR_TEMPLATE.format(
                            reason=COMMITTED_VIEW_REASON,
                            error=hash_error or STAGE_REASON,
                        )
                        raise ReconciliationFault(slug, write.relative_path, write.line, reason)
                head_entry = head_entries.get(write.relative_path)
                expected_mode = head_entry.mode if head_entry is not None else DEFAULT_FILE_MODE
                evidence = FoldResidue(
                    write=write,
                    head_entry=head_entry,
                    fold_blob=fold_blob,
                    expected_mode=expected_mode,
                    file_mode_enabled=file_mode_enabled,
                )
                if not residue_is_intact(project_root, evidence):
                    _raise_dirty_path(slug, write)
                residue.append(evidence)
                transaction_writes.append(write)

            for working_write in working_writes.values():
                apply_writes.append(working_write)
                transaction_writes.append(working_write)
    except OSError as temporary_error:
        raise ReconciliationFault(
            slug,
            EMPTY_PATH,
            0,
            COMMITTED_VIEW_ERROR_TEMPLATE.format(reason=COMMITTED_VIEW_REASON, error=temporary_error),
        ) from temporary_error

    transaction_plan = ReconciliationPlan(slug=slug, mode=mode, writes=tuple(transaction_writes))
    apply_plan = ReconciliationPlan(slug=slug, mode=mode, writes=tuple(apply_writes))
    return transaction_plan, apply_plan, tuple(residue)


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
                    expected_blob, hash_error = expected_blob_id(
                        project_root,
                        write.relative_path,
                        write.rendered_content,
                        temporary_root,
                        index,
                    )
                    if hash_error:
                        return _CommitResolution(CommitResolution.UNRESOLVED, error=hash_error)
                actual_entry, tree_error = tree_entry_at_commit(project_root, commit_id, write.relative_path)
                if tree_error:
                    return _CommitResolution(CommitResolution.UNRESOLVED, error=tree_error)
                actual_blob = actual_entry.blob if actual_entry is not None else None
                if actual_blob != expected_blob:
                    return _CommitResolution(
                        CommitResolution.UNRESOLVED,
                        error=COMMIT_TREE_MISMATCH_TEMPLATE.format(relative_path=write.relative_path),
                    )
    except OSError as temporary_error:
        return _CommitResolution(CommitResolution.UNRESOLVED, error=str(temporary_error))
    return _CommitResolution(CommitResolution.LANDED, commit=commit_id)


def _restore_failed_index(
    project_root: Path,
    slug: str,
    paths: tuple[str, ...],
    residue: tuple[FoldResidue, ...],
) -> None:
    """Restore ordinary paths and only still-owned fold residue in the index.

    Raises ``_IndexRestoreFault`` when a restore is still refused after lock recovery.
    """
    residue_by_path = {evidence.write.relative_path: evidence for evidence in residue}
    ordinary_paths = tuple(path for path in paths if path not in residue_by_path)
    _require_index_restored(slug, _restore_index(project_root, ordinary_paths))
    safe_residue_paths = tuple(
        path for path in paths if path in residue_by_path and residue_is_intact(project_root, residue_by_path[path])
    )
    _require_index_restored(slug, _restore_index(project_root, safe_residue_paths))


def _require_index_restored(slug: str, outcome: _IndexRestore) -> None:
    if not outcome.restored:
        raise _IndexRestoreFault(slug, EMPTY_PATH, 0, INDEX_RESTORE_REASON_TEMPLATE.format(error=outcome.error))


def _restore_transaction_sources(
    project_root: Path,
    slug: str,
    apply_plan: ReconciliationPlan,
    residue: tuple[FoldResidue, ...],
) -> None:
    """Undo applied writes and restore only residue that still matches its transaction evidence."""
    restore_reconciliation_plan(apply_plan)
    safe_writes = tuple(evidence.write for evidence in residue if residue_is_intact(project_root, evidence))
    if safe_writes:
        residue_plan = ReconciliationPlan(
            slug=slug,
            mode=ReconciliationMode.RESTORE,
            writes=safe_writes,
        )
        restore_reconciliation_plan(residue_plan)


def _commit_plan(
    project_root: Path,
    slug: str,
    plan: ReconciliationPlan,
    staged_before: set[str],
    transition_id: str,
    residue: tuple[FoldResidue, ...] = (),
) -> _CommitPlanResult:
    """Stage and commit the exact pathset, resolving uncertain command results."""
    paths = _relative_paths(plan)
    if not paths:
        return _CommitPlanResult(None)
    for evidence in residue:
        if not residue_is_intact(project_root, evidence):
            _raise_dirty_path(slug, evidence.write)
    add_code, _add_output, add_error = _run_git_cmd([*GIT_ADD_ARGS, *paths], cwd=str(project_root))
    if add_code != 0:
        _restore_failed_index(project_root, slug, paths, residue)
        raise ReconciliationFault(slug, "", 0, add_error or STAGE_REASON)
    staged_after = git_name_set(project_root, list(GIT_CACHED_NAME_ARGS))
    if staged_after != staged_before | set(paths):
        _restore_failed_index(project_root, slug, paths, residue)
        raise ReconciliationFault(slug, "", 0, STAGED_SET_REASON)
    previous_head_code, previous_head_output, previous_head_error = _run_git_cmd(
        list(GIT_HEAD_ARGS), cwd=str(project_root)
    )
    if previous_head_code != 0:
        _restore_failed_index(project_root, slug, paths, residue)
        raise ReconciliationFault(slug, "", 0, previous_head_error or COMMIT_REASON)
    previous_head = previous_head_output.strip()
    if not previous_head:
        _restore_failed_index(project_root, slug, paths, residue)
        raise ReconciliationFault(slug, "", 0, COMMIT_REASON)
    message = COMMIT_MESSAGE_WITH_TRANSITION_TEMPLATE.format(
        subject=COMMIT_MESSAGE_TEMPLATE.format(slug=slug),
        trailer=TRANSITION_TRAILER_TEMPLATE.format(
            key=TRANSITION_TRAILER_KEY,
            transition_id=transition_id,
        ),
    )
    commit_code, commit_error = _run_commit(project_root, [*GIT_COMMIT_ARGS, message, "--", *paths])
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
        _restore_failed_index(project_root, slug, paths, residue)
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


def _normalized_plan(plan: ReconciliationPlan, formatted: dict[str, ReconciliationWrite]) -> ReconciliationPlan:
    return ReconciliationPlan(
        slug=plan.slug,
        mode=plan.mode,
        writes=tuple(formatted.get(write.relative_path, write) for write in plan.writes),
    )


def _format_reconciliation_writes(
    project_root: Path,
    attempt: _FormatAttempt,
) -> None:
    """Format every reconciliation write and capture snapshots in a finally block."""
    selected_writes = {
        write.relative_path: write for write in attempt.plan.writes if write.rendered_content is not None
    }
    if not selected_writes:
        return

    try:
        attempt.outcome = format_paths_for_commit_gate(project_root, sorted(selected_writes))
    finally:
        formatted_writes: dict[str, ReconciliationWrite] = {}
        snapshot_error = EMPTY_ERROR
        for relative_path, write in selected_writes.items():
            try:
                formatted_bytes = (project_root / relative_path).read_bytes()
                formatted_content = formatted_bytes.decode(UTF8_ENCODING)
            except (OSError, UnicodeError) as error:
                snapshot_error = FORMAT_SNAPSHOT_FAILURE_TEMPLATE.format(relative_path=relative_path, error=error)
                break
            formatted_writes[relative_path] = replace(write, rendered_content=formatted_content)

        attempt.plan = _normalized_plan(attempt.plan, formatted_writes)
        attempt.apply_plan = _normalized_plan(attempt.apply_plan, formatted_writes)
        attempt.residue = tuple(
            replace(evidence, write=formatted_writes.get(evidence.write.relative_path, evidence.write))
            for evidence in attempt.residue
        )
        attempt.normalized_path_count = len(attempt.outcome.formatted_paths)
        attempt.snapshot_error = snapshot_error
        if not snapshot_error:
            try:
                with TemporaryDirectory() as temporary_directory:
                    temporary_root = Path(temporary_directory)
                    for index, evidence in enumerate(attempt.residue):
                        formatted_write = formatted_writes.get(evidence.write.relative_path)
                        if formatted_write is None or formatted_write.rendered_content is None:
                            continue
                        formatted_blob, hash_error = expected_blob_id(
                            project_root,
                            formatted_write.relative_path,
                            formatted_write.rendered_content,
                            temporary_root,
                            index,
                        )
                        if hash_error or formatted_blob is None:
                            attempt.snapshot_error = FORMAT_SNAPSHOT_FAILURE_TEMPLATE.format(
                                relative_path=formatted_write.relative_path,
                                error=hash_error or STAGE_REASON,
                            )
                            break
                        attempt.residue = tuple(
                            replace(item, formatted_blob=formatted_blob)
                            if item.write.relative_path == formatted_write.relative_path
                            else item
                            for item in attempt.residue
                        )
            except OSError as error:
                attempt.snapshot_error = FORMAT_SNAPSHOT_FAILURE_TEMPLATE.format(relative_path=EMPTY_PATH, error=error)


def _apply_commit_with_compensation(
    project_root: Path,
    slug: str,
    plan: ReconciliationPlan,
    transition_id: str,
    *,
    apply_plan: ReconciliationPlan | None = None,
    residue: tuple[FoldResidue, ...] = (),
) -> _ApplyCommitOutcome:
    """Apply one plan and restore its sources if its commit step faults."""
    writes_to_apply = apply_plan or plan
    residue_paths = frozenset(evidence.write.relative_path for evidence in residue)
    staged_before = _preflight_plan(project_root, slug, plan, allowed_dirty_paths=residue_paths)
    apply_reconciliation_plan(writes_to_apply)
    format_attempt = _FormatAttempt(plan, writes_to_apply, residue, 0, FormatGateOutcome(), EMPTY_ERROR)
    formatter_succeeded = False
    try:
        _format_reconciliation_writes(project_root, format_attempt)
        plan = format_attempt.plan
        writes_to_apply = format_attempt.apply_plan
        residue = format_attempt.residue
        normalized_path_count = format_attempt.normalized_path_count
        outcome = format_attempt.outcome
        snapshot_error = format_attempt.snapshot_error
        if snapshot_error or outcome.failure_reason or outcome.failed_homes:
            reason = (
                snapshot_error
                or outcome.failure_reason
                or FORMAT_FAILURE_REASON_TEMPLATE.format(homes=", ".join(str(home) for home in outcome.failed_homes))
            )
            affected_write = plan.writes[0]
            raise ReconciliationFault(slug, affected_write.relative_path, affected_write.line, reason)
        formatter_succeeded = True
    finally:
        plan = format_attempt.plan
        writes_to_apply = format_attempt.apply_plan
        residue = format_attempt.residue
        normalized_path_count = format_attempt.normalized_path_count
        if not formatter_succeeded:
            _restore_transaction_sources(project_root, slug, writes_to_apply, residue)
    try:
        result = _commit_plan(project_root, slug, plan, staged_before, transition_id, residue)
    except _IndexRestoreFault:
        raise
    except ReconciliationFault:
        _restore_transaction_sources(project_root, slug, writes_to_apply, residue)
        raise
    if result.fault is not None:
        if result.restore_sources:
            _restore_transaction_sources(project_root, slug, writes_to_apply, residue)
        raise result.fault
    return _ApplyCommitOutcome(plan, result.commit, normalized_path_count)


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
        working_plan = plan_snippet_reconciliation(project_root, slug, mode, new_slug=new_slug)
        if moment is MarkerMoment.DELIVER:
            plan, apply_plan, residue = _reconciliation_transaction_plans(
                project_root,
                slug,
                mode,
                new_slug,
                working_plan,
            )
        else:
            plan, apply_plan, residue = working_plan, working_plan, ()
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
        commit_outcome = _apply_commit_with_compensation(
            project_root,
            slug,
            plan,
            transition_id,
            apply_plan=apply_plan,
            residue=residue,
        )
        plan = commit_outcome.plan
        commit = commit_outcome.commit
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
        normalized_path_count=commit_outcome.normalized_path_count,
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
        commit_outcome = _apply_commit_with_compensation(project_root, slug, restored, transition_id)
        restored = commit_outcome.plan
        commit = commit_outcome.commit
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
        normalized_path_count=commit_outcome.normalized_path_count,
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
