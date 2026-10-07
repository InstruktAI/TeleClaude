"""Small support helpers shared by prepare step handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING, NotRequired, TypedDict

from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.next_machine._types import StateValue
from teleclaude.core.next_machine.lifecycle import plan_review_current
from teleclaude.core.next_machine.output_formatting import format_prepared
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.next_machine.unclaim import ClaimReleaseOutcome, unclaim_todo_for_caller
from teleclaude.session_identity import get_session_id
from teleclaude.types.todos import TodoState

logger = get_logger(__name__)

_PREPARE_COMPLETED_EVENT = "todo_prepare_completed"
_PREPARE_COMPLETED_MESSAGE = "todo prepare completed"
_PREPARE_TERMINAL_OUTCOME = "terminal_prepare"
_BUILD_RESIDUE_REASON = "build_residue"
_NO_BUILD_RESIDUE_REASON = "no_build_residue"
_DEPENDENCY_GATE_OPEN = "open"
_EMPTY_TEXT = ""


class _PrepareCompletionLogFields(TypedDict):
    event: str
    outcome: str
    reason: str
    slug: str
    caller_session_id: str
    prepared_session_id: str
    build_start_base_present: bool
    old_plan_digest: str
    current_plan_digest: str
    dependency_gate: NotRequired[str]
    claim_release_status: str
    claim_release_reason: str
    claim_active_runner_cleared: bool
    claim_working_slug_cleared: bool


if TYPE_CHECKING:
    from teleclaude.core.db import Db
    from teleclaude.core.todos_db import TodosDb


def worker_idle_post_block(slug: str) -> str:
    """Post-block emitted after dispatching a worker."""
    return f"WHEN WORKER IDLES:\nCall telec todo prepare {slug}. The state machine emits the next action."


def reviewer_idle_post_block(slug: str) -> str:
    """Post-block emitted after dispatching a reviewer."""
    return (
        f"WHEN REVIEWER IDLES:\n"
        f"Call telec todo prepare {slug}. The state machine will read the verdict and emit the next action."
    )


def derive_project_root(cwd: str, slug: str) -> str:
    """Extract canonical project root from an effective cwd that may be a worktree."""
    suffix = f"/{WORKTREE_DIR}/{slug}"
    if cwd.endswith(suffix):
        return cwd[: -len(suffix)]
    return cwd


async def commit_writer(
    writer: StateWriter,
    todos_db: TodosDb,
    slug: str,
    state: dict[str, StateValue],
) -> None:
    """Commit the writer and sync the validated payload back to *state*."""
    payload = await writer.commit(todos_db, slug)
    state.clear()
    state.update(payload)


async def prepare_step_prepared(db: Db, todos_db: TodosDb, slug: str, *, project_root: str) -> tuple[bool, str]:
    """PREPARED: release the claim; the lifecycle runner dispatches the next lane's orchestrator."""
    state = await todos_db.read_state(slug)
    if state is None:
        raise RuntimeError(f"prepared todo state is missing for {slug}")
    model = TodoState.model_validate(state)
    claim_release_outcome = await unclaim_todo_for_caller(
        db,
        slug=slug,
        cwd=project_root,
        caller_session_id=get_session_id(),
    )
    _log_prepare_completed(model, slug=slug, claim_release_outcome=claim_release_outcome)
    return False, format_prepared(slug)


def _log_prepare_completed(
    model: TodoState,
    *,
    slug: str,
    claim_release_outcome: ClaimReleaseOutcome,
) -> None:
    build_residue_present = bool(model.build_start_base_sha)
    log_fields: _PrepareCompletionLogFields = {
        "event": _PREPARE_COMPLETED_EVENT,
        "outcome": _PREPARE_TERMINAL_OUTCOME,
        "reason": _BUILD_RESIDUE_REASON if build_residue_present else _NO_BUILD_RESIDUE_REASON,
        "slug": slug,
        "caller_session_id": get_session_id() or _EMPTY_TEXT,
        "prepared_session_id": model.prepared_session_id or _EMPTY_TEXT,
        "build_start_base_present": build_residue_present,
        "old_plan_digest": model.build_plan_digest,
        "current_plan_digest": model.artifacts.implementation_plan.digest,
        "claim_release_status": claim_release_outcome.status.value,
        "claim_release_reason": (
            claim_release_outcome.refusal_reason.value if claim_release_outcome.refusal_reason else _EMPTY_TEXT
        ),
        "claim_active_runner_cleared": claim_release_outcome.cleared_active_runner,
        "claim_working_slug_cleared": claim_release_outcome.cleared_working_slug,
    }
    if plan_review_current(model):
        log_fields["dependency_gate"] = _DEPENDENCY_GATE_OPEN
    logger.info(_PREPARE_COMPLETED_MESSAGE, **log_fields)
