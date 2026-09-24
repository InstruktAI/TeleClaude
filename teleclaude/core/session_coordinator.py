"""Atomic adoption of the single coordinator role for a project instance."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.constants import ROLE_ORCHESTRATOR, JobRole, SlashCommand
from teleclaude.core.db import Db, get_db
from teleclaude.core.session_bootstrap import reconcile_session_identity_document
from teleclaude.core.session_listeners import unregister_listener
from teleclaude.core.session_status import is_session_terminal
from teleclaude.core.session_title import compose_command_session_title

_COORDINATOR_COMMAND = SlashCommand.NEXT_COORDINATE.value
_IDENTITY_RECONCILIATION_ERROR = "Adopted coordinator identity document could not be reconciled"
ADOPTION_REASON_NO_LIVE_HOLDER = "no_live_holder"
ADOPTION_REASON_CALLER_ALREADY_HOLDER = "caller_already_holder"
ADOPTION_REASON_LIVE_HOLDER = "live_holder"
NOT_BOUND_MESSAGE = "The calling session is not bound to a project instance."
REFUSED_MESSAGE = (
    "A live coordinator already holds this project. The incumbent is never touched, messaged, or assessed. "
    "A session started solely to coordinate ends itself now: emit only a brief farewell, then arm "
    "`telec reminders set session-departure`. Arming it is your final action — nothing comes after it."
)
ADOPTED_MESSAGE = (
    "This session is now the project's coordinator. Fetch "
    "`software-development/procedure/lifecycle/coordinate` with `telec docs get`, read every required read "
    "it lists in full, then follow the procedure."
)

logger = get_logger(__name__)
_adoption_lock = asyncio.Lock()


class CoordinatorAdoptionStatus(StrEnum):
    """Outcomes of one session's coordinator-adoption request."""

    ADOPTED = "adopted"
    REFUSED = "refused"
    NOT_BOUND = "not_bound"


@dataclass(frozen=True)
class CoordinatorAdoptionResult:
    """The sealed outcome returned to an acquisition caller."""

    status: CoordinatorAdoptionStatus
    holder_session_id: str | None
    message: str


def _same_project_root(session_project_path: str | None, project_root: Path) -> bool:
    """Return whether a session belongs to the caller's resolved project root."""
    if not session_project_path:
        return False
    try:
        return Path(session_project_path).resolve() == project_root
    except (OSError, ValueError):
        return False


async def adopt_coordinator(
    caller_session_id: str,
    *,
    db: Db | None = None,
) -> CoordinatorAdoptionResult:
    """Adopt a caller as coordinator unless another live session already holds it."""
    runtime_db = db or await get_db()
    async with _adoption_lock:
        caller = await runtime_db.get_session(caller_session_id)
        if caller is None or not caller.project_path:
            return CoordinatorAdoptionResult(
                status=CoordinatorAdoptionStatus.NOT_BOUND,
                holder_session_id=None,
                message=NOT_BOUND_MESSAGE,
            )

        project_root = Path(caller.project_path).resolve()
        logger.info(
            "coordinator_adoption_requested",
            session_id=caller.session_id,
            project_path=str(project_root),
        )
        sessions = await runtime_db.list_sessions(
            computer_name=caller.computer_name,
            include_closed=False,
            all_open=True,
        )
        holder = next(
            (
                session
                for session in sessions
                if _same_project_root(session.project_path, project_root)
                and session.job == JobRole.COORDINATOR.value
                and not is_session_terminal(
                    lifecycle_status=session.lifecycle_status,
                    closed_at=session.closed_at,
                )
            ),
            None,
        )
        if holder is not None and holder.session_id != caller.session_id:
            logger.info(
                "coordinator_adoption_refused",
                outcome=CoordinatorAdoptionStatus.REFUSED.value,
                reason=ADOPTION_REASON_LIVE_HOLDER,
                session_id=caller.session_id,
                holder_session_id=holder.session_id,
                project_path=str(project_root),
            )
            return CoordinatorAdoptionResult(
                status=CoordinatorAdoptionStatus.REFUSED,
                holder_session_id=holder.session_id,
                message=REFUSED_MESSAGE,
            )

        reason = ADOPTION_REASON_CALLER_ALREADY_HOLDER if holder is not None else ADOPTION_REASON_NO_LIVE_HOLDER

        # Snapshot the current contract so a failed identity-file reconciliation
        # can restore the durable session before the listener is retired.
        former_spawner = caller.initiator_session_id
        previous_title = caller.title
        previous_command = caller.command
        previous_system_role = caller.system_role
        previous_job = caller.job
        previous_initiator_computer = caller.initiator_computer
        previous_human_email = caller.human_email
        previous_human_role = caller.human_role
        previous_principal = caller.principal
        await runtime_db.update_session(
            caller.session_id,
            title=compose_command_session_title(_COORDINATOR_COMMAND, ""),
            command=_COORDINATOR_COMMAND,
            system_role=ROLE_ORCHESTRATOR,
            job=JobRole.COORDINATOR.value,
            initiator_session_id=None,
            initiator_computer=None,
            human_email=None,
            human_role=None,
            principal=None,
        )
        identity_reconciled = False
        try:
            if not await reconcile_session_identity_document(caller.session_id):
                raise RuntimeError(_IDENTITY_RECONCILIATION_ERROR)
            identity_reconciled = True
            if former_spawner:
                await unregister_listener(caller.session_id, former_spawner)
        except Exception as exc:
            await runtime_db.update_session(
                caller.session_id,
                title=previous_title,
                command=previous_command,
                system_role=previous_system_role,
                job=previous_job,
                initiator_session_id=former_spawner,
                initiator_computer=previous_initiator_computer,
                human_email=previous_human_email,
                human_role=previous_human_role,
                principal=previous_principal,
            )
            if identity_reconciled and not await reconcile_session_identity_document(caller.session_id):
                raise RuntimeError(_IDENTITY_RECONCILIATION_ERROR) from exc
            raise
        logger.info(
            "coordinator_adopted",
            outcome=CoordinatorAdoptionStatus.ADOPTED.value,
            reason=reason,
            session_id=caller.session_id,
            project_path=str(project_root),
        )
        return CoordinatorAdoptionResult(
            status=CoordinatorAdoptionStatus.ADOPTED,
            holder_session_id=None,
            message=ADOPTED_MESSAGE,
        )
