"""Workflow-owned transaction coordination for documentation marker reconciliation."""

from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass, replace
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
    ReconciliationWrite,
    apply_reconciliation_plan,
    iter_reconciliation_roots,
    plan_snippet_reconciliation,
    restore_reconciliation_plan,
    reverse_reconciliation_plan,
)
from teleclaude.quality.gate import FormatGateOutcome, format_paths_for_commit_gate

logger = get_logger(__name__)

RECONCILIATION_REQUESTED_EVENT = "workflow.marker_reconciliation.requested"
RECONCILIATION_FINISHED_EVENT = "workflow.marker_reconciliation.finished"
GIT_STATUS_ARGS = ("status", "--porcelain", "--")
GIT_SNIPPET_STATUS_ARGS = ("status", "--porcelain", "--untracked-files=all", "--no-renames", "--")
GIT_ADD_ARGS = ("add", "--")
GIT_CACHED_NAME_ARGS = ("diff", "--cached", "--name-only", "--no-renames")
GIT_RESTORE_STAGED_ARGS = ("restore", "--staged", "--")
GIT_COMMIT_ARGS = ("commit", "-m")
GIT_HEAD_ARGS = ("rev-parse", "--verify", "HEAD")
GIT_REV_LIST_ARGS = ("rev-list", "--reverse")
GIT_COMMIT_MESSAGE_ARGS = ("show", "-s", "--format=%B")
GIT_HASH_OBJECT_ARGS = ("hash-object",)
GIT_LS_TREE_ARGS = ("ls-tree", "-z")
GIT_LS_FILES_STAGE_ARGS = ("ls-files", "--stage", "--")
GIT_CAT_FILE_FILTERS_ARGS = ("cat-file", "--filters")
GIT_FILE_MODE_CONFIG_ARGS = ("config", "--bool", "--get", "core.fileMode")
GIT_HEAD = "HEAD"
GIT_REVISION_RANGE_TEMPLATE = "{previous_head}..HEAD"
GIT_PATH_OPTION_TEMPLATE = "--path={relative_path}"
GIT_HEAD_PATH_TEMPLATE = "HEAD:{relative_path}"
GIT_TREE_FIELD_SEPARATOR = "\t"
GIT_TREE_RECORD_SEPARATOR = "\0"
GIT_INDEX_STAGE_SEPARATOR = "\t"
GIT_BLOB_OBJECT_TYPE = "blob"
UTF8_ENCODING = "utf-8"
EMPTY_ERROR = ""
EMPTY_PATH = ""
DEFAULT_FILE_MODE = "100644"
EXECUTABLE_FILE_MODE = "100755"
SYMLINK_FILE_MODE = "120000"
INDEX_STAGE_ZERO = "0"
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
COMMIT_PATH_NOT_BLOB_REASON = "commit path did not resolve to a blob"
COMMIT_PATH_MULTIPLE_ENTRIES_REASON = "commit path resolved to multiple tree entries"
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


@dataclass(frozen=True)
class _GitTreeEntry:
    """One regular Git tree entry's mode and blob identity."""

    mode: str
    blob: str


@dataclass(frozen=True)
class _FoldResidue:
    """Evidence that one dirty path contains only its own uncommitted fold."""

    write: ReconciliationWrite
    head_entry: _GitTreeEntry | None
    fold_blob: str | None
    expected_mode: str
    file_mode_enabled: bool
    formatted_blob: str | None = None


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
    residue: tuple[_FoldResidue, ...]
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


def _restore_index(project_root: Path, paths: tuple[str, ...]) -> None:
    """Unstage only the reconciliation pathset during transactional compensation."""
    if paths:
        _run_git_cmd([*GIT_RESTORE_STAGED_ARGS, *paths], cwd=str(project_root))


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


def _tree_entry_at_commit(
    project_root: Path,
    commit: str,
    relative_path: str,
) -> tuple[_GitTreeEntry | None, str]:
    """Read one exact path's mode and blob identity from a commit tree."""
    code, output, error = _run_git_cmd([*GIT_LS_TREE_ARGS, commit, "--", relative_path], cwd=str(project_root))
    if code != 0:
        return None, error
    entries: list[_GitTreeEntry] = []
    for record in output.split(GIT_TREE_RECORD_SEPARATOR):
        metadata, separator, path = record.partition(GIT_TREE_FIELD_SEPARATOR)
        if not separator or path != relative_path:
            continue
        fields = metadata.split()
        if len(fields) != 3 or fields[1] != GIT_BLOB_OBJECT_TYPE:
            return None, COMMIT_PATH_NOT_BLOB_REASON
        entries.append(_GitTreeEntry(mode=fields[0], blob=fields[2]))
    if len(entries) > 1:
        return None, COMMIT_PATH_MULTIPLE_ENTRIES_REASON
    return (entries[0] if entries else None), EMPTY_ERROR


def _index_entries(project_root: Path, relative_path: str) -> tuple[list[tuple[str, str, str]] | None, str]:
    """Read every index stage for one exact path."""
    code, output, error = _run_git_cmd(
        [*GIT_LS_FILES_STAGE_ARGS, relative_path], cwd=str(project_root), preserve_stdout_newlines=True
    )
    if code != 0:
        return None, error
    entries: list[tuple[str, str, str]] = []
    for line in output.splitlines():
        metadata, separator, path = line.partition(GIT_INDEX_STAGE_SEPARATOR)
        if not separator or path != relative_path:
            continue
        fields = metadata.split()
        if len(fields) != 3:
            return None, STAGE_REASON
        entries.append((fields[0], fields[1], fields[2]))
    return entries, EMPTY_ERROR


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


def _working_file_mode(path: Path, expected_mode: str, file_mode_enabled: bool) -> str:
    """Return the mode Git would stage for a working-tree path."""
    if path.is_symlink():
        return SYMLINK_FILE_MODE
    if not file_mode_enabled:
        return expected_mode
    file_mode = path.stat().st_mode
    return EXECUTABLE_FILE_MODE if file_mode & stat.S_IXUSR else DEFAULT_FILE_MODE


def _residue_is_intact(project_root: Path, residue: _FoldResidue) -> bool:
    """Check that working bytes, mode, and every index stage still identify this fold."""
    write = residue.write
    path = project_root / write.relative_path
    if write.rendered_content is None:
        if path.exists() or path.is_symlink():
            return False
    else:
        try:
            if path.read_bytes() != write.rendered_content.encode(UTF8_ENCODING):
                return False
            if _working_file_mode(path, residue.expected_mode, residue.file_mode_enabled) != residue.expected_mode:
                return False
        except OSError:
            return False

    entries, error = _index_entries(project_root, write.relative_path)
    if error or entries is None:
        return False
    head_index_entry = (
        [(residue.head_entry.mode, residue.head_entry.blob, INDEX_STAGE_ZERO)] if residue.head_entry is not None else []
    )
    allowed_entries = [head_index_entry]
    if residue.fold_blob is not None:
        allowed_entries.append([(residue.expected_mode, residue.fold_blob, INDEX_STAGE_ZERO)])
    if residue.formatted_blob is not None and residue.formatted_blob != residue.fold_blob:
        allowed_entries.append([(residue.expected_mode, residue.formatted_blob, INDEX_STAGE_ZERO)])
    if residue.fold_blob is None and not head_index_entry:
        allowed_entries.append([])
    return entries in allowed_entries


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
) -> tuple[ReconciliationPlan, ReconciliationPlan, tuple[_FoldResidue, ...]]:
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
    residue: list[_FoldResidue] = []
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

            head_entries: dict[str, _GitTreeEntry | None] = {}
            for relative_path in sorted(dirty_paths):
                head_entry, tree_error = _tree_entry_at_commit(project_root, GIT_HEAD, relative_path)
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
                    fold_blob, hash_error = _expected_blob_id(
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
                evidence = _FoldResidue(
                    write=write,
                    head_entry=head_entry,
                    fold_blob=fold_blob,
                    expected_mode=expected_mode,
                    file_mode_enabled=file_mode_enabled,
                )
                if not _residue_is_intact(project_root, evidence):
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
                    expected_blob, hash_error = _expected_blob_id(
                        project_root,
                        write.relative_path,
                        write.rendered_content,
                        temporary_root,
                        index,
                    )
                    if hash_error:
                        return _CommitResolution(CommitResolution.UNRESOLVED, error=hash_error)
                actual_entry, tree_error = _tree_entry_at_commit(project_root, commit_id, write.relative_path)
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
    paths: tuple[str, ...],
    residue: tuple[_FoldResidue, ...],
) -> None:
    """Restore ordinary paths and only still-owned fold residue in the index."""
    residue_by_path = {evidence.write.relative_path: evidence for evidence in residue}
    ordinary_paths = tuple(path for path in paths if path not in residue_by_path)
    _restore_index(project_root, ordinary_paths)
    safe_residue_paths = tuple(
        path for path in paths if path in residue_by_path and _residue_is_intact(project_root, residue_by_path[path])
    )
    _restore_index(project_root, safe_residue_paths)


def _restore_transaction_sources(
    project_root: Path,
    slug: str,
    apply_plan: ReconciliationPlan,
    residue: tuple[_FoldResidue, ...],
) -> None:
    """Undo applied writes and restore only residue that still matches its transaction evidence."""
    restore_reconciliation_plan(apply_plan)
    safe_writes = tuple(evidence.write for evidence in residue if _residue_is_intact(project_root, evidence))
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
    residue: tuple[_FoldResidue, ...] = (),
) -> _CommitPlanResult:
    """Stage and commit the exact pathset, resolving uncertain command results."""
    paths = _relative_paths(plan)
    if not paths:
        return _CommitPlanResult(None)
    for evidence in residue:
        if not _residue_is_intact(project_root, evidence):
            _raise_dirty_path(slug, evidence.write)
    add_code, _add_output, add_error = _run_git_cmd([*GIT_ADD_ARGS, *paths], cwd=str(project_root))
    if add_code != 0:
        _restore_failed_index(project_root, paths, residue)
        raise ReconciliationFault(slug, "", 0, add_error or STAGE_REASON)
    staged_after = git_name_set(project_root, list(GIT_CACHED_NAME_ARGS))
    if staged_after != staged_before | set(paths):
        _restore_failed_index(project_root, paths, residue)
        raise ReconciliationFault(slug, "", 0, STAGED_SET_REASON)
    previous_head_code, previous_head_output, previous_head_error = _run_git_cmd(
        list(GIT_HEAD_ARGS), cwd=str(project_root)
    )
    if previous_head_code != 0:
        _restore_failed_index(project_root, paths, residue)
        raise ReconciliationFault(slug, "", 0, previous_head_error or COMMIT_REASON)
    previous_head = previous_head_output.strip()
    if not previous_head:
        _restore_failed_index(project_root, paths, residue)
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
        _restore_failed_index(project_root, paths, residue)
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
                        formatted_blob, hash_error = _expected_blob_id(
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
    residue: tuple[_FoldResidue, ...] = (),
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
