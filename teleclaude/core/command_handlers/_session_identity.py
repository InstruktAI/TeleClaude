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
    is_desk_role,
)
from teleclaude.config import WORKING_DIR, config
from teleclaude.constants import (
    HUMAN_ROLE_CUSTOMER,
    HUMAN_ROLES,
    WORKTREE_DIR,
    SlashCommand,
    is_standing_role,
)
from teleclaude.core.command_input import (
    WORKTREE_BOUND_WORKER_COMMANDS,
    RefusedCommandInput,
    ResolvedCommandInput,
    admit_command_input,
)
from teleclaude.core.identity import IdentityContext, get_identity_resolver
from teleclaude.core.models import Session
from teleclaude.core.session_company import resolve_session_creation_company
from teleclaude.core.session_startup_message import resolve_command_input
from teleclaude.core.session_utils import resolve_working_dir
from teleclaude.types.commands import CreateSessionCommand

logger = get_logger(__name__)

_LISTENER_REGISTRATION_SKIPPED_EVENT = "session_listener_registration_skipped"
_LISTENER_SKIP_REASON_STANDING_ROLE = "standing_role"
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


def prepare_interactive_create_command(cmd: CreateSessionCommand, human_role: str | None) -> None:
    """Resolve one target-local command input before session creation observes it."""
    source_text = cmd.command_input_source_text or cmd.initial_input
    result = resolve_command_input(cmd.initial_input, cmd.command_input_mode)
    if isinstance(result, RefusedCommandInput):
        raise ValueError(result.detail)
    if not isinstance(result, ResolvedCommandInput):
        return
    metadata = admit_command_input(result.command, result.args, human_role)
    try:
        slash_command = SlashCommand(result.command)
    except ValueError:
        slash_command = None
    if slash_command in WORKTREE_BOUND_WORKER_COMMANDS:
        subdir = _WORKTREE_SUBDIR_TEMPLATE.format(worktree_dir=WORKTREE_DIR, slug=metadata.working_slug)
        worktree_dir = Path(resolve_working_dir(cmd.project_path, subdir))
        if not worktree_dir.is_dir():
            raise ValueError(_WORKTREE_DIRECTORY_MISSING_TEMPLATE.format(worktree_dir=worktree_dir))
        cmd.subdir = subdir
    cmd.initial_input = result.normalized_message
    cmd.command = result.command
    cmd.system_role = metadata.system_role
    cmd.job = metadata.job
    cmd.working_slug = metadata.working_slug
    if cmd.launch_intent is not None and cmd.launch_intent.message is not None:
        cmd.launch_intent.message = result.normalized_message
        cmd.launch_intent.command_input_source_text = source_text


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

    principal: str | None = None
    if parent_session:
        human_email = human_email or parent_session.human_email
        principal = parent_session.principal

    parent_company = parent_session.company if parent_session else None
    company, company_source = resolve_session_creation_company(cmd.request_id, cmd.company, human_email, parent_company)
    human_role = _creation_human_role(cmd, identity, human_email, principal)
    prepare_interactive_create_command(cmd, human_role)
    subfolder = cmd.subdir
    working_slug = resolve_working_slug_from_subdir(subfolder) or cmd.working_slug
    cmd_system_role, cmd_job = cmd.system_role, cmd.job
    initiator_session_id, initiator_computer = cmd.initiator_session_id, cmd.initiator_computer
    if is_standing_role(cmd_system_role, cmd_job):
        if initiator_session_id:
            logger.info(
                _LISTENER_REGISTRATION_SKIPPED_EVENT,
                caller_session_id=initiator_session_id,
                target_session_id=session_id,
                reason=_LISTENER_SKIP_REASON_STANDING_ROLE,
            )
        initiator_session_id = initiator_computer = None
        human_email = human_role = principal = None

    if not human_role and not cmd_system_role:
        raise ValueError(f"Session creation failed: no identity resolved and no system_role (origin={origin})")

    system_role = cmd_system_role
    raw_help_desk_path = getattr(config.computer, "help_desk_dir", None)
    configured_help_desk_path = (
        raw_help_desk_path
        if isinstance(raw_help_desk_path, str) and raw_help_desk_path.strip()
        else os.path.join(WORKING_DIR, "help-desk")
    )
    if is_desk_role(system_role or None, human_role):
        logger.info("Restricted session placed at the help desk: origin=%s role=%s", origin, human_role)
        project_path = configured_help_desk_path
        Path(project_path).mkdir(parents=True, exist_ok=True)
        subfolder = working_slug = None
    else:
        project_path = cmd.project_path or configured_help_desk_path
        if not cmd.project_path:
            logger.info("Session creation missing project_path from origin=%s; defaulting to help-desk.", origin)
            Path(project_path).mkdir(parents=True, exist_ok=True)
            subfolder = working_slug = None
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
