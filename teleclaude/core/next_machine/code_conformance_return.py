"""Bounded return from held finalize-ready work to the existing build cycle."""

from __future__ import annotations

from datetime import UTC, datetime

from git import Repo
from git.exc import BadName, GitCommandError, InvalidGitRepositoryError, NoSuchPathError
from instrukt_ai_logging import get_logger

from teleclaude.constants import TodoStatus
from teleclaude.core.db import db as runtime_db
from teleclaude.core.integration.state_machine import (
    IntegrationRecoveryRefused,
    hold_integration_for_todo_recovery,
)
from teleclaude.core.next_machine._types import StateValue
from teleclaude.core.next_machine.kinds import KIND_TASK
from teleclaude.core.next_machine.lifecycle import LifecyclePhase, _clear_build_review, reset_finalize
from teleclaude.core.next_machine.runtime.sessions import find_all_live_sessions_for_slug
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.project_state import resolve_project_state_root as resolve_project_root
from teleclaude.core.workflow_store.store import WorkflowStore, get_workflow_store
from teleclaude.types.todo_return import TodoReturnToWorkAuditField, TodoReturnToWorkGitRef
from teleclaude.types.todos import Event, FinalizeStatus, TodoEventKind

logger = get_logger(__name__)

_RETURN_REQUIRED = "return-to-work requires non-empty --reason and --evidence values"
_CALLER_SESSION_REQUIRED = "a caller session is required to record the return"
_NOT_FOUND = "todo does not exist or is no longer active"
_NOT_ACTIVE = "todo must be active; unfreeze it with `telec todo unfreeze <slug>` before returning work"
_NOT_HELD = "todo is not held; hold it with `telec todo update <slug> --hold --reason <reason>` first"
_NOT_FINALIZE_READY = "todo has not completed its work cycle; continue through `telec todo work <slug>`"
_CLAIMED = "todo has an active lifecycle claim; let its owner release the claim before returning it"
_LIVE_SESSIONS = "todo has live worktree sessions"
_LIVE_SESSIONS_TEMPLATE = "{reason}: {sessions}; let them finish and release the claim before returning it"
_SESSION_ID_SEPARATOR = ", "
_WRONG_KIND = "task todos do not have a build/review/finalize cycle; continue through the task prepare/run lifecycle"
_INVALID_CANDIDATE = (
    "todo has no recorded finalization candidate; recover finalization through `telec todo work <slug>`"
)
_COMMITTED = (
    "candidate already reached the shared branch or was delivered; use the ordinary post-delivery defect or change path"
)
_MAIN_UNRESOLVED = "canonical main refs are unavailable; synchronize the repository and retry"
_CANDIDATE_CHANGED = "candidate changed during return; retry against the current candidate"
_CANDIDATE_STATE_UNAVAILABLE_TEMPLATE = "could not establish candidate integration state: {reason}"
_RETURN_COMPLETED_EVENT = "workflow.code_conformance_returned"


class CodeConformanceReturnRefused(ValueError):
    """A candidate does not meet the bounded code-conformance return contract."""


async def return_to_work_for_code_conformance(
    *,
    cwd: str,
    slug: str,
    reason: str,
    evidence: str,
    caller_session_id: str,
) -> dict[str, StateValue]:
    """Return one held, unintegrated candidate to the ordinary build/review cycle."""
    normalized_reason = reason.strip()
    normalized_evidence = evidence.strip()
    if not normalized_reason or not normalized_evidence:
        raise CodeConformanceReturnRefused(_RETURN_REQUIRED)
    if not caller_session_id:
        raise CodeConformanceReturnRefused(_CALLER_SESSION_REQUIRED)

    project_root = str(resolve_project_root(cwd))
    todos_db = await get_workflow_store(project_root)

    try:
        with hold_integration_for_todo_recovery(project_root, caller_session_id):
            candidate_sha = await _read_return_candidate(todos_db, slug, project_root)
            _refuse_committed_candidate(project_root, candidate_sha)
            updated_state = await todos_db.update_state_with_artifact_evidence(
                slug,
                [],
                lambda raw_state, _digests: _returned_state(
                    raw_state,
                    candidate_sha=candidate_sha,
                    reason=normalized_reason,
                    evidence=normalized_evidence,
                    caller_session_id=caller_session_id,
                ),
            )
            logger.info(
                _RETURN_COMPLETED_EVENT,
                event=_RETURN_COMPLETED_EVENT,
                project_root=project_root,
                slug=slug,
                candidate_sha=candidate_sha,
                from_phase=LifecyclePhase.FINALIZE_READY.value,
                to_phase=LifecyclePhase.BUILD_STARTED.value,
                caller_session_id=caller_session_id,
            )
            return updated_state
    except IntegrationRecoveryRefused as exc:
        raise CodeConformanceReturnRefused(str(exc)) from exc
    except (BadName, GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError) as exc:
        raise CodeConformanceReturnRefused(_CANDIDATE_STATE_UNAVAILABLE_TEMPLATE.format(reason=exc)) from exc


async def _read_return_candidate(todos_db: WorkflowStore, slug: str, project_root: str) -> str:
    """Read and validate the active, held candidate before the transactional transition."""
    row = await todos_db.read_todo_diagnostic_record(slug)
    if row is None:
        raise CodeConformanceReturnRefused(_NOT_FOUND)
    if row["status"] is TodoStatus.DELIVERED or row["delivered_at"] or row["delivered_commit"]:
        raise CodeConformanceReturnRefused(_COMMITTED)
    if row["status"] is not TodoStatus.ACTIVE:
        raise CodeConformanceReturnRefused(_NOT_ACTIVE)

    raw_state = await todos_db.read_state(slug)
    if raw_state is None:
        raise CodeConformanceReturnRefused(_NOT_FINALIZE_READY)
    state = StateWriter(raw_state).state
    if state.kind.value == KIND_TASK:
        raise CodeConformanceReturnRefused(_WRONG_KIND)
    if not state.hold:
        raise CodeConformanceReturnRefused(_NOT_HELD)
    if state.lifecycle_phase is not LifecyclePhase.FINALIZE_READY or state.finalize.status is not FinalizeStatus.READY:
        raise CodeConformanceReturnRefused(_NOT_FINALIZE_READY)
    if state.active_runner:
        raise CodeConformanceReturnRefused(_CLAIMED)
    live_sessions = await find_all_live_sessions_for_slug(runtime_db, slug, project_path=project_root)
    if live_sessions:
        raise CodeConformanceReturnRefused(
            _LIVE_SESSIONS_TEMPLATE.format(reason=_LIVE_SESSIONS, sessions=_SESSION_ID_SEPARATOR.join(live_sessions))
        )
    if not state.finalize.sha:
        raise CodeConformanceReturnRefused(_INVALID_CANDIDATE)
    return state.finalize.sha


def _returned_state(
    raw_state: dict[str, StateValue] | None,
    *,
    candidate_sha: str,
    reason: str,
    evidence: str,
    caller_session_id: str,
) -> dict[str, StateValue]:
    """Clear stale eligibility and append the recovery record in one state write."""
    if raw_state is None:
        raise CodeConformanceReturnRefused(_NOT_FINALIZE_READY)
    writer = StateWriter(raw_state)
    state = writer.state
    if not state.hold:
        raise CodeConformanceReturnRefused(_NOT_HELD)
    if state.lifecycle_phase is not LifecyclePhase.FINALIZE_READY or state.finalize.status is not FinalizeStatus.READY:
        raise CodeConformanceReturnRefused(_NOT_FINALIZE_READY)
    if state.active_runner:
        raise CodeConformanceReturnRefused(_CLAIMED)
    if state.finalize.sha != candidate_sha:
        raise CodeConformanceReturnRefused(_CANDIDATE_CHANGED)

    previous_phase = state.lifecycle_phase.value
    reset_finalize(state)
    _clear_build_review(state)
    state.lifecycle_phase = LifecyclePhase.BUILD_STARTED
    state.events.append(
        Event(
            at=datetime.now(UTC).isoformat(),
            actor=caller_session_id,
            kind=TodoEventKind.CODE_CONFORMANCE_RETURN,
            details={
                TodoReturnToWorkAuditField.REASON: reason,
                TodoReturnToWorkAuditField.EVIDENCE: evidence,
                TodoReturnToWorkAuditField.CANDIDATE_SHA: candidate_sha,
                TodoReturnToWorkAuditField.FROM_PHASE: previous_phase,
            },
        )
    )
    return writer.to_dict()


def _refuse_committed_candidate(project_root: str, candidate_sha: str) -> None:
    """Refuse candidates already reachable from either canonical main ref."""
    repository = Repo(project_root)
    candidate = repository.commit(candidate_sha)
    resolved_main_refs = 0
    for ref_name in (TodoReturnToWorkGitRef.LOCAL_MAIN, TodoReturnToWorkGitRef.REMOTE_MAIN):
        try:
            main = repository.commit(ref_name.value)
        except (BadName, GitCommandError, ValueError):
            continue
        resolved_main_refs += 1
        if repository.is_ancestor(candidate, main):
            raise CodeConformanceReturnRefused(_COMMITTED)
    if not resolved_main_refs:
        raise CodeConformanceReturnRefused(_MAIN_UNRESOLVED)


__all__ = ["CodeConformanceReturnRefused", "return_to_work_for_code_conformance"]
