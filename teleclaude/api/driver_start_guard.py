"""Create-door guard that refuses a driver start duplicating a live driver."""

from __future__ import annotations

from teleclaude.api.auth import CallerIdentity
from teleclaude.api.run_session_refusals import RunSessionRefusal
from teleclaude.caller_identity import PersonCliCaller, caller_from_principal, human_principal_for_email
from teleclaude.constants import DriverLaunchClass
from teleclaude.core.agent_dispatch import AgentDispatchReason
from teleclaude.core.command_service import classify_driver_launch
from teleclaude.core.next_machine.manual_start import DriverStartGuardResult, guard_driver_start
from teleclaude.core.session_startup_message import resolve_slash_command
from teleclaude.core.todos_db._exceptions import ClaimConflict, ReviewerConflict, ReviewerIdentityUnresolved


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


async def enforce_driver_start_guard(
    *,
    project_path: str,
    working_slug: str | None,
    command: str | None,
    caller_session_id: str | None,
    caller_human_email: str | None,
    thinking_mode: str,
) -> DriverStartGuardResult:
    """Refuse a create-door driver start that would duplicate a live driver.

    Shared by both create doors (run-session and generic create): it classifies
    the requested launch and runs the two-signal dedup guard, mapping a conflict
    to HTTP 409 naming the holder. A non-driver launch or an unclaimed slug passes
    through silently — except a reviewer launch, which is checked even with no
    slug (commit review carries no todo slug at all).
    """
    normalized_command = resolve_slash_command(command)
    launch_class = classify_driver_launch(normalized_command)
    if launch_class is not DriverLaunchClass.REVIEWER and not working_slug:
        return DriverStartGuardResult()
    try:
        return await guard_driver_start(
            project_path,
            working_slug,
            launch_class=launch_class,
            caller_session_id=caller_session_id,
            caller_human_email=caller_human_email,
            command=normalized_command,
            thinking_mode=thinking_mode,
        )
    except ReviewerConflict as conflict:
        raise RunSessionRefusal(
            status_code=409, detail=conflict.summary(), reason=AgentDispatchReason.REVIEWER_CONFLICT
        ) from conflict
    except (ClaimConflict, ReviewerIdentityUnresolved) as conflict:
        raise RunSessionRefusal(
            status_code=409, detail=conflict.summary(), reason=AgentDispatchReason.RUN_REQUEST_REJECTED
        ) from conflict
