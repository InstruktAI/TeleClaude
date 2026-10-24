"""Resolve and persist the owed actions for one commit advancement."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from teleclaude.checkpoint_model import (
    ActivationRange,
    main_only_judgment_action_ids_for_files,
)
from teleclaude.constants import LOG_CHECK_ACTION_ID, RESTART_MAINTENANCE_ACTION_ID, CheckpointModel
from teleclaude.core.integration._maintenance_records import (
    MaintenanceActionRecord,
    MaintenanceRecordState,
    commit_activation_key,
    record_path,
    write_record,
)
from teleclaude.git import Repo
from teleclaude.hooks.integrator_judgment_marker import record_integrator_judgment_activation

_ZERO_SHA_CHARACTER = "0"
_SYNC_ACTION_ID = "sync"
_GIT_HEAD_REFERENCE = "HEAD"
_GIT_ORIGINAL_HEAD_REFERENCE = "ORIG_HEAD"


def resolve_activation_range(project_root: Path, before_ref: str | None, after_ref: str) -> ActivationRange:
    """Resolve hook refs to immutable object ids before selecting any action."""
    repository = Repo(str(project_root.resolve()))
    before_sha = repository.commit(before_ref).hexsha if before_ref is not None else None
    after_sha = repository.commit(after_ref).hexsha
    return ActivationRange(before_sha=before_sha, after_sha=after_sha)


def resolve_post_commit_activation_range(project_root: Path) -> ActivationRange:
    """Resolve the new tip and its parent, preserving an absent root parent."""
    repository = Repo(str(project_root.resolve()))
    after_commit = repository.commit(_GIT_HEAD_REFERENCE)
    before_sha = after_commit.parents[0].hexsha if after_commit.parents else None
    return ActivationRange(before_sha=before_sha, after_sha=after_commit.hexsha)


def resolve_post_merge_activation_range(project_root: Path) -> ActivationRange:
    """Resolve the pre-merge and post-merge tips before any maintenance runs."""
    return resolve_activation_range(project_root, _GIT_ORIGINAL_HEAD_REFERENCE, _GIT_HEAD_REFERENCE)


def resolve_current_tip_activation_range(project_root: Path, after_sha: str | None = None) -> ActivationRange:
    """Resolve an unregistered checkout tip from the previous HEAD reflog position."""
    repository = Repo(str(project_root.resolve()))
    after_commit = repository.commit(after_sha or _GIT_HEAD_REFERENCE)
    after = after_commit.hexsha
    previous = next(
        (entry.oldhexsha for entry in reversed(repository.head.log()) if entry.newhexsha == after),
        None,
    )
    before = None if previous is None or not previous.strip(_ZERO_SHA_CHARACTER) else previous
    return ActivationRange(before_sha=before, after_sha=after)


def derive_window_action(
    action_ids: tuple[str, ...], path_action_ids: tuple[str, ...], model: CheckpointModel
) -> tuple[str, ...]:
    """Owe the replacement action when selected path work is not serving-tolerant."""
    actions = tuple(action_id for action_id in action_ids if action_id != RESTART_MAINTENANCE_ACTION_ID)
    if RESTART_MAINTENANCE_ACTION_ID not in model.maintenance:
        return actions
    if any(
        action_id != RESTART_MAINTENANCE_ACTION_ID
        and (action_id not in model.maintenance or not model.maintenance[action_id].runs_while_serving)
        for action_id in path_action_ids
    ):
        return (*actions, RESTART_MAINTENANCE_ACTION_ID)
    return actions


def write_owed_records(
    root: Path, activation_range: ActivationRange, action_ids: tuple[str, ...], changed_files: tuple[str, ...]
) -> None:
    """Write each owed action's record that does not exist yet, then the integrator judgment the paths owe."""
    queued_at = datetime.now(UTC).isoformat()
    for action_id in action_ids:
        path = record_path(root, commit_activation_key(activation_range.after_sha), action_id)
        if path.exists():
            continue
        record = MaintenanceActionRecord(
            activation=activation_range,
            action_id=action_id,
            queued_at=queued_at,
            state=MaintenanceRecordState.PENDING,
        )
        write_record(path, record)

    judgment_action_ids = main_only_judgment_action_ids_for_files(list(changed_files), root)
    if LOG_CHECK_ACTION_ID in judgment_action_ids:
        record_integrator_judgment_activation(
            root,
            activation_range,
            [LOG_CHECK_ACTION_ID],
            queued_at,
        )
