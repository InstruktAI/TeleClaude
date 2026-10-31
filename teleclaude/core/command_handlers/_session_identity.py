"""Resolve identity and placement for a newly created session."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.caller_identity import (
    PersonCliCaller,
    RoleResolver,
    SessionOf,
    caller_from_principal,
    human_principal_for_email,
    identity_for_session,
    is_desk_role,
)
from teleclaude.config.machine import config
from teleclaude.constants import (
    HUMAN_ROLE_CUSTOMER,
    HUMAN_ROLES,
    SYSTEM_DAEMON_PRINCIPAL,
    SYSTEM_OPERATOR_PRINCIPAL,
    WORKTREE_DIR,
)
from teleclaude.core.command_input import ResolvedCommandInput, admit_command_input
from teleclaude.core.endpoints import desk_endpoint_for_stamp, desk_for_folder
from teleclaude.core.identity import IdentityContext, get_identity_resolver
from teleclaude.core.interactive_procedure_input import resolve_interactive_input
from teleclaude.core.models import Session, SessionEntryPoint
from teleclaude.core.next_machine.lanes import WORKTREE_BOUND_PROCEDURES
from teleclaude.core.procedure_entry import EntryContext, EntryRefusal, resolve_entry
from teleclaude.core.roles import is_standing_session
from teleclaude.core.session_company import resolve_session_creation_company
from teleclaude.core.session_utils import resolve_working_dir
from teleclaude.core.workflow_store.store import get_workflow_store
from teleclaude.helpers.agent_types import ThinkingMode
from teleclaude.paths import REPO_ROOT
from teleclaude.types.commands import CreateSessionCommand
from teleclaude.types.creation_record import Lineage

logger = get_logger(__name__)

_LISTENER_REGISTRATION_SKIPPED_EVENT = "session_listener_registration_skipped"
_LISTENER_SKIP_REASON_STANDING_ROLE = "standing_role"
_RESTRICTED_SESSION_REFUSED_EVENT = "restricted_session_refused"
_RESTRICTED_SESSION_REFUSED_TEMPLATE = (
    "Session creation refused: a {role} session runs only inside an enabled help desk"
)
_NO_SESSION_IDENTITY_REFUSED_TEMPLATE = "Session creation failed: no identity resolved and no role (origin={origin})"
_NO_PROJECT_REFUSED_EVENT = "session_creation_no_project_refused"
_NO_PROJECT_REFUSED_TEMPLATE = "Session creation refused: no project was given"
_DESK_NOT_HOSTED_TEMPLATE = "Session creation refused: the requested help desk is not enabled on this computer"
_WORKTREE_SUBDIR_TEMPLATE = "{worktree_dir}/{slug}"
_WORKTREE_DIRECTORY_MISSING_TEMPLATE = "required worktree directory does not exist: {worktree_dir}"


@dataclass(frozen=True)
class SessionCreationIdentity:
    """Identity and placement resolved for one new session."""

    human_email: str | None
    principal: str | None
    human_role: str | None
    project_path: str
    subfolder: str | None
    working_slug: str | None
    company: str | None
    company_source: str
    initiator_session_id: str | None
    initiator_computer: str | None


class SessionCreationRefused(ValueError):
    """Session creation was refused by identity or placement policy."""


def _lower_creation_role(role: str, supplied_role: str | None) -> str:
    """Let a supplied role restrict, but never elevate, the project-effective role."""
    effective_role = role if role in HUMAN_ROLES else HUMAN_ROLE_CUSTOMER
    if supplied_role is None:
        return effective_role
    restricted_role = supplied_role if supplied_role in HUMAN_ROLES else HUMAN_ROLE_CUSTOMER
    return max((effective_role, restricted_role), key=HUMAN_ROLES.index)


def _creation_human_role(
    cmd: CreateSessionCommand,
    identity: IdentityContext | None,
    human_email: str | None,
    principal: str | None,
) -> str | None:
    """Resolve a registered person's role for the requested project before admission."""
    identified_origin = identity is not None and bool(
        identity.person_slug or identity.person_email or identity.platform_user_id
    )
    if identified_origin and identity is not None:
        if identity.person_email:
            caller = caller_from_principal(human_principal_for_email(identity.person_email))
        elif identity.person_slug:
            caller = PersonCliCaller(
                person_slug=identity.person_slug,
                human_role=identity.person_role,
            )
        else:
            return HUMAN_ROLE_CUSTOMER
    else:
        carried_principal = principal or (human_principal_for_email(human_email) if human_email else None)
        caller = caller_from_principal(carried_principal)

    if isinstance(caller, PersonCliCaller):
        if not caller.person_slug:
            return HUMAN_ROLE_CUSTOMER
        role = RoleResolver().role_for(caller, SessionOf(cmd.project_path))
        return _lower_creation_role(role, cmd.human_role)
    if identified_origin or cmd.human_role is not None:
        return HUMAN_ROLE_CUSTOMER
    return None


def resolve_working_slug_from_subdir(subdir: str | None) -> str | None:
    """Derive a todo slug from a direct ``<worktrees>/<slug>`` subdirectory."""
    if not subdir:
        return None
    prefix = f"{WORKTREE_DIR}/"
    if not subdir.startswith(prefix):
        return None
    return subdir[len(prefix) :].strip("/") or None


def prepare_interactive_create_command(cmd: CreateSessionCommand, human_role: str | None, session_id: str) -> None:
    """Resolve one target-local command input through the procedure entry before session creation observes it.

    A leading token naming a published entry procedure creates the session with that procedure's role and the
    loader naming its published closure; any other text stays ordinary conversation. A recognized invocation
    that violates an argument or authorization rule is refused visibly.
    """
    project_root = Path(cmd.project_path) if cmd.project_path else REPO_ROOT
    result = resolve_interactive_input(cmd.initial_input, cmd.command_input_mode, project_root)
    if not isinstance(result, ResolvedCommandInput):
        return
    source_text = cmd.command_input_source_text or cmd.initial_input
    admit_command_input(human_role)
    launch = cmd.launch_intent
    caller_mode = ThinkingMode(launch.thinking_mode) if launch is not None and launch.thinking_mode else None
    try:
        resolved = resolve_entry(
            procedure_token=result.command,
            arguments=result.args,
            project_root=project_root,
            caller=None,
            entry=EntryContext(),
            caller_mode=caller_mode,
        )
    except EntryRefusal as exc:
        raise ValueError(exc.detail) from exc
    if resolved.procedure_id in WORKTREE_BOUND_PROCEDURES and resolved.working_slug:
        subdir = _WORKTREE_SUBDIR_TEMPLATE.format(worktree_dir=WORKTREE_DIR, slug=resolved.working_slug)
        worktree_dir = Path(resolve_working_dir(cmd.project_path, subdir))
        if not worktree_dir.is_dir():
            raise ValueError(_WORKTREE_DIRECTORY_MISSING_TEMPLATE.format(worktree_dir=worktree_dir))
        cmd.subdir = subdir
    cmd.initial_input = f"{resolved.procedure_id} {resolved.arguments}".strip()
    cmd.command = resolved.procedure_id
    cmd.role = resolved.role.name.value
    cmd.job = None
    cmd.working_slug = resolved.working_slug
    if launch is not None and launch.message is not None:
        launch.message = resolved.loader
        launch.command_input_source_text = source_text
        launch.invocation = resolved.record
        launch.candidate_order = launch.candidate_order or resolved.agents
        launch.thinking_mode = launch.thinking_mode or resolved.thinking_mode.value


async def resolve_session_creation_identity(
    cmd: CreateSessionCommand,
    parent_session: Session | None,
    session_id: str,
) -> SessionCreationIdentity:
    """Resolve origin, inherited identity, company, and confined project placement."""
    origin = cmd.origin
    if not origin:
        raise ValueError("Command missing origin")

    identity: IdentityContext | None = None
    human_email = cmd.human_email
    if cmd.origin_metadata:
        identity = get_identity_resolver().resolve(origin, cmd.origin_metadata)
        human_email = human_email or identity.person_email

    principal: str | None = SYSTEM_OPERATOR_PRINCIPAL if cmd.operator else None
    if parent_session:
        human_email = human_email or parent_session.human_email
        principal = identity_for_session(parent_session).principal

    parent_company = parent_session.company if parent_session else None
    company, company_source = resolve_session_creation_company(cmd.request_id, cmd.company, human_email, parent_company)
    human_role = _creation_human_role(cmd, identity, human_email, principal)
    prepare_interactive_create_command(cmd, human_role, session_id)
    subfolder = cmd.subdir
    working_slug = resolve_working_slug_from_subdir(subfolder) or cmd.working_slug
    cmd_role = cmd.role
    initiator_session_id, initiator_computer = cmd.initiator_session_id, cmd.initiator_computer
    if is_standing_session(cmd_role, scheduled=cmd.entry_point is SessionEntryPoint.CRON):
        if initiator_session_id:
            logger.info(
                _LISTENER_REGISTRATION_SKIPPED_EVENT,
                caller_session_id=initiator_session_id,
                target_session_id=session_id,
                reason=_LISTENER_SKIP_REASON_STANDING_ROLE,
            )
        initiator_session_id = initiator_computer = None
        human_email = human_role = principal = None

    if not human_role and not cmd_role and principal not in (SYSTEM_DAEMON_PRINCIPAL, SYSTEM_OPERATOR_PRINCIPAL):
        raise SessionCreationRefused(_NO_SESSION_IDENTITY_REFUSED_TEMPLATE.format(origin=origin))

    if cmd.endpoint is not None and cmd.endpoint.is_help_desk:
        # A request naming a desk endpoint is placed in the folder of a desk this
        # computer hosts (desks run only on the master); any role runs there confined.
        desk = desk_endpoint_for_stamp(cmd.endpoint, config.computer.name, bool(config.computer.is_master))
        if desk is None:
            logger.warning(_RESTRICTED_SESSION_REFUSED_EVENT, origin=origin, role=human_role)
            raise SessionCreationRefused(_DESK_NOT_HOSTED_TEMPLATE)
        project_path = str(desk.folder)
        Path(project_path).mkdir(parents=True, exist_ok=True)
        subfolder = working_slug = None
    elif is_desk_role(cmd_role or None, human_role):
        # A role below member runs only inside an enabled help desk, and only the
        # one its request names: nothing is redirected to a desk of the jail's choosing.
        desk = (
            desk_for_folder(cmd.project_path, config.computer.name, bool(config.computer.is_master))
            if cmd.project_path
            else None
        )
        if desk is None:
            logger.warning(_RESTRICTED_SESSION_REFUSED_EVENT, origin=origin, role=human_role)
            raise SessionCreationRefused(_RESTRICTED_SESSION_REFUSED_TEMPLATE.format(role=human_role))
        project_path = str(desk.folder)
        Path(project_path).mkdir(parents=True, exist_ok=True)
        subfolder = working_slug = None
    elif cmd.project_path:
        project_path = cmd.project_path
    else:
        logger.warning(_NO_PROJECT_REFUSED_EVENT, origin=origin, role=human_role)
        raise SessionCreationRefused(_NO_PROJECT_REFUSED_TEMPLATE)
    project_path = os.path.expanduser(os.path.expandvars(project_path))
    return SessionCreationIdentity(
        human_email=human_email,
        principal=principal,
        human_role=human_role,
        project_path=project_path,
        subfolder=subfolder,
        working_slug=working_slug,
        company=company,
        company_source=company_source,
        initiator_session_id=initiator_session_id,
        initiator_computer=initiator_computer,
    )


async def read_todo_owner_principal(project_path: str, slug: str) -> str | None:
    """Read a todo's persisted lineage root for the resolved project.

    Returns the chain-root authority (``human:<email>`` or ``system:<id>``), or
    ``None`` only when a successful read proves the todo has no recorded
    lineage. Read failures are NOT swallowed: lineage is a required invariant
    for a slug-bound runner session, so a failed lookup must surface and stop
    session creation rather than silently degrade to the daemon identity.
    The caller establishes the human root only from a proven owner; an
    unreadable owner is an error, never a license to fall back.
    """
    todos_db = await get_workflow_store(project_path)
    return Lineage.root_of(await todos_db.read_lineage(slug))
