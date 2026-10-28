"""Create-door guard that refuses a driver start duplicating a live driver."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from teleclaude.api.auth import CallerIdentity
from teleclaude.api.run_session_refusals import RunSessionRefusal
from teleclaude.caller_identity import PersonCliCaller, caller_from_principal, human_principal_for_email
from teleclaude.constants import SYSTEM_DAEMON_PRINCIPAL, DriverLaunchClass
from teleclaude.core.agent_dispatch import AgentDispatchReason
from teleclaude.core.db import get_db
from teleclaude.core.next_machine.driver_admission import (
    AdmissionCaller,
    StartRequest,
    admission_conflict_detail,
    admitted_start,
)
from teleclaude.core.next_machine.lanes import classify_driver_launch
from teleclaude.core.next_machine.manual_start import DriverStartGuardResult, guard_driver_start, lane_of_role
from teleclaude.core.next_machine.runner_types import RunnerLane
from teleclaude.core.next_machine.runtime.driver_starts import driver_start_section
from teleclaude.core.next_machine.runtime.sessions import is_github_backed, recheck_slug_holder
from teleclaude.core.project_state import resolve_project_state_root
from teleclaude.core.todos_db._exceptions import (
    AdmissionUnavailable,
    ClaimConflict,
    DriverStartBusy,
    ReviewerConflict,
    ReviewerIdentityUnresolved,
)
from teleclaude.core.workflow_store.store import get_workflow_store


def terminal_driver_email(identity: CallerIdentity) -> str | None:
    """Return the email keying a session-less caller as a terminal driver, or ``None``.

    A terminal driver is a caller with no session whose carried principal is the
    human principal of its own email and names a registered person. Requiring the
    registered person is what keeps a reviewer it starts findable: creation records
    the reviewer's ``human_email`` from the roster, so an unregistered email would
    record none. A caller with a session is never a terminal driver; its session
    is the key.
    """
    if identity.session_id or not identity.email or not identity.principal:
        return None
    if identity.principal != human_principal_for_email(identity.email):
        return None
    caller = caller_from_principal(identity.principal)
    if isinstance(caller, PersonCliCaller) and caller.person_slug:
        return identity.email
    return None


def admission_caller_for(identity: CallerIdentity) -> AdmissionCaller:
    """The principal a start's relayed requests are cleared as on the active computer: the caller's own, else the daemon's."""
    return AdmissionCaller(
        principal=identity.principal or SYSTEM_DAEMON_PRINCIPAL,
        cleared_command=identity.command,
        session_id=identity.session_id or None,
    )


async def _admit_driver_start(
    held: AsyncExitStack,
    *,
    project_path: str,
    working_slug: str | None,
    procedure_id: str | None,
    role: str | None,
    caller_session_id: str | None,
    caller_human_email: str | None,
    thinking_mode: str,
    starting_session_id: str | None,
    local_target: bool,
    admission_caller: AdmissionCaller,
    manually_started: bool,
) -> DriverStartGuardResult:
    """Run the dedup guard and, for a local orchestrator start, enter the todo's section on ``held``.

    A todo on the GitHub store is admitted by the project's active computer first, and the section is held across
    that admission (:func:`admitted_start`); any other todo holds the section around this computer's own
    holder re-check.
    """
    launch_class = classify_driver_launch(role)
    if launch_class is not DriverLaunchClass.REVIEWER and not working_slug:
        return DriverStartGuardResult()
    guard_result = await guard_driver_start(
        project_path,
        working_slug,
        launch_class=launch_class,
        caller_session_id=caller_session_id,
        caller_human_email=caller_human_email,
        command=procedure_id,
        thinking_mode=thinking_mode,
    )
    if (
        launch_class is not DriverLaunchClass.ORCHESTRATOR
        or not working_slug
        or not local_target
        or not starting_session_id
    ):
        return guard_result
    if is_github_backed(project_path):
        start = StartRequest(
            project_root=resolve_project_state_root(project_path),
            slug=working_slug,
            session_id=starting_session_id,
            lane=lane_of_role(role) or RunnerLane.PREPARE,
            manually_started=manually_started,
            release_hold=manually_started,
            caller=admission_caller,
        )
        await held.enter_async_context(admitted_start(start))
        return guard_result
    await held.enter_async_context(
        driver_start_section(project_path, working_slug, starting_session_id=starting_session_id)
    )
    holder = await recheck_slug_holder(
        await get_db(),
        await get_workflow_store(resolve_project_state_root(project_path)),
        project_path,
        working_slug,
        exempt_session_id=None,
    )
    if holder is not None:
        raise ClaimConflict(slug=working_slug, holder=holder)
    return guard_result


@asynccontextmanager
async def enforce_driver_start_guard(
    *,
    project_path: str,
    working_slug: str | None,
    procedure_id: str | None,
    role: str | None,
    caller_session_id: str | None,
    caller_human_email: str | None,
    thinking_mode: str,
    starting_session_id: str | None = None,
    local_target: bool = True,
    admission_caller: AdmissionCaller = AdmissionCaller(),
    manually_started: bool = False,
) -> AsyncIterator[DriverStartGuardResult]:
    """Refuse a create-door driver start that would duplicate a live driver.

    Shared by both create doors (run-session and generic create): it classifies
    the requested launch and runs the two-signal dedup guard, mapping a conflict
    to HTTP 409 naming the holder. A non-driver launch or an unclaimed slug passes
    through silently — except a reviewer launch, which is checked even with no
    slug (commit review carries no todo slug at all).

    An orchestrator launch for a todo that is created on this computer
    (``local_target`` and a ``starting_session_id``) also holds the todo's driver-start
    section from the holder re-check until the caller leaves the context, so the
    caller creates the session row inside it and the next start finds it. A start
    that finds the section held is refused at once with HTTP 423 naming the session
    the holding start is creating. Every other launch class holds nothing.

    For a todo on the GitHub store the active computer admits the start first and records its claim before the
    session exists. A todo held by a session on another computer is refused with HTTP 409 whose detail
    declares its own kind and names the holding session and its computer (or the computers that did not
    answer for it); a start the active computer cannot decide, or one made on another computer, the start is refused with HTTP 503 and nothing is created.
    ``admission_caller`` is the principal the start's relayed requests are cleared as, and
    ``manually_started`` marks a start a person asked for.
    """
    async with AsyncExitStack() as held:
        try:
            guard_result = await _admit_driver_start(
                held,
                project_path=project_path,
                working_slug=working_slug,
                procedure_id=procedure_id,
                role=role,
                caller_session_id=caller_session_id,
                caller_human_email=caller_human_email,
                thinking_mode=thinking_mode,
                starting_session_id=starting_session_id,
                local_target=local_target,
                admission_caller=admission_caller,
                manually_started=manually_started,
            )
        except ReviewerConflict as conflict:
            raise RunSessionRefusal(
                status_code=409, detail=conflict.summary(), reason=AgentDispatchReason.REVIEWER_CONFLICT
            ) from conflict
        except ClaimConflict as conflict:
            detail = (
                admission_conflict_detail(conflict) if conflict.computer or conflict.unanswered else conflict.summary()
            )
            raise RunSessionRefusal(
                status_code=409, detail=detail, reason=AgentDispatchReason.RUN_REQUEST_REJECTED
            ) from conflict
        except ReviewerIdentityUnresolved as conflict:
            raise RunSessionRefusal(
                status_code=409, detail=conflict.summary(), reason=AgentDispatchReason.RUN_REQUEST_REJECTED
            ) from conflict
        except AdmissionUnavailable as unavailable:
            raise RunSessionRefusal(
                status_code=503, detail=unavailable.summary(), reason=AgentDispatchReason.RUN_REQUEST_REJECTED
            ) from unavailable
        except DriverStartBusy as busy:
            raise RunSessionRefusal(
                status_code=423, detail=busy.summary(), reason=AgentDispatchReason.RUN_REQUEST_REJECTED
            ) from busy
        yield guard_result
