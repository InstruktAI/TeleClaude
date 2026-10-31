"""Session management command handlers."""

import asyncio
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, cast

import psutil
from instrukt_ai_logging import get_logger

from teleclaude import __version__
from teleclaude.agent_registry import LaunchProfile
from teleclaude.api_models import TodoDTO
from teleclaude.config.machine import config
from teleclaude.config.subject_resolution import SubjectResolutionError, resolve_config_subject
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.constants import SYSTEM_DAEMON_PRINCIPAL, SYSTEM_OPERATOR_PRINCIPAL
from teleclaude.core import tmux_bridge
from teleclaude.core.agent_availability import launch_ownership
from teleclaude.core.agent_dispatch import (
    AgentDispatchDecision,
    AgentDispatchFailure,
    AgentDispatchKindSource,
    AgentDispatchMode,
    AgentDispatchOutcome,
    AgentDispatchReason,
    AgentDispatchStage,
    DispatchSessionKind,
    decision_basis_digest,
    desk_session_kind,
    emit_agent_dispatch_decision,
    resolve_agent_dispatch,
    resolve_launch_model,
)
from teleclaude.core.agents import AgentName
from teleclaude.core.codex_transcript import discover_codex_transcript_path
from teleclaude.core.command_dispatch import forward_command_to_peer
from teleclaude.core.conversation_messages import format_identity_conversation
from teleclaude.core.db import db
from teleclaude.core.inbound.fleet import local_conversation_adapters
from teleclaude.core.integration.session_address import SessionAddressResolved, resolve_session_conversation_url
from teleclaude.core.models import (
    CONFINEMENT_PROFILE_KEY,
    CONFINEMENT_SECTION,
    ENDPOINT_SECTION,
    ComputerInfo,
    JsonDict,
    ProjectInfo,
    Session,
    SessionLaunchKind,
    SessionSnapshot,
)
from teleclaude.core.models._adapter import UNATTENDED_SECTION, unattended_stamp
from teleclaude.core.reconciliation import DEFAULT_FEATURE_ID_REGISTRY
from teleclaude.core.roles import RoleName
from teleclaude.core.runtime_events import publish_runtime_error, publish_session_source_change
from teleclaude.core.session_cleanup import (
    has_pending_channel_cleanup,
    host_pane_name,
    recover_failed_close,
    terminate_session,
)
from teleclaude.core.session_company import record_session_company_resolved
from teleclaude.core.session_listeners import establish_supervision
from teleclaude.core.session_listing import SessionListingSelection
from teleclaude.core.session_snapshot import project_session_snapshot
from teleclaude.core.session_title import compose_command_session_title
from teleclaude.core.session_utils import WorkingDirectoryUnavailableError, resolve_working_dir
from teleclaude.core.todo import assemble_todo_from_db, recently_delivered_cutoff
from teleclaude.core.workflow_store.store import get_workflow_store
from teleclaude.events.envelope import EventHomeMarker
from teleclaude.events.home_owner import EventHomeOwnerMarker
from teleclaude.events.schemas.system import RuntimeSessionChange
from teleclaude.project_root import is_project_checkout
from teleclaude.services.project_catalog import get_project_catalog_service
from teleclaude.services.project_catalog.ownership import load_project_ownership_index
from teleclaude.types import CpuStats, DiskStats, MemoryStats, SystemStats
from teleclaude.types.commands import CloseSessionCommand, CreateSessionCommand, GetSessionDataCommand
from teleclaude.types.todo_kind import ALL_DUMP_KINDS
from teleclaude.utils import strip_ansi_codes
from teleclaude.utils.transcript import TRANSCRIPT_READERS, parse_session_transcript

from ._session_identity import read_todo_owner_principal, resolve_session_creation_identity
from ._utils import EndSessionHandlerResult, SessionDataPayload, with_session

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)
_UNBOUND_TMUX_NAME = ""
_NO_TITLE_ARGUMENTS = ""
_NO_ASSIGNMENT_TITLE = ""
_SESSION_CLOSE_FAILED_EVENT = "Failed to close session %s: %s"

_WORKING_DIR_NOT_ABSOLUTE_TEMPLATE = "Working directory must be an absolute path: {working_dir}"
_WORKING_DIR_MISSING_TEMPLATE = "Working directory does not exist: {working_dir}"
_WORKING_DIR_NOT_A_DIRECTORY_TEMPLATE = "Working directory is not a directory: {working_dir}"

_LISTENER_REGISTRATION_SKIPPED_EVENT = "session_listener_registration_skipped"
_LISTENER_REGISTRATION_FAILED_EVENT = "session_listener_registration_failed"
_LISTENER_SKIP_REASON_STANDING_ROLE = "standing_role"
_SESSION_SUBJECT_RESOLUTION_FAILED_EVENT = "session_config_subject_resolution_failed"


async def _resolve_prepare_todo_kind(project_path: str, slug: str) -> str:
    """Read the authoritative prepare kind on the target machine."""
    state = await (await get_workflow_store(project_path)).read_state(slug)
    kind = state.get("kind") if state else None
    if not isinstance(kind, str) or kind not in ALL_DUMP_KINDS:
        raise ValueError(f"Prepare routing requires canonical todo kind for '{slug}'")
    return kind


async def _resolve_launch_intent(
    cmd: CreateSessionCommand,
    project_path: str,
    working_slug: str | None,
    session_kind: DispatchSessionKind | None,
) -> AgentDispatchDecision | None:
    intent = cmd.launch_intent
    if cmd.headless or intent is None or intent.kind == SessionLaunchKind.EMPTY:
        return None
    mode = intent.dispatch_mode or (AgentDispatchMode.FIXED if intent.agent else AgentDispatchMode.AUTOMATIC)
    command_kind = cmd.initial_input.lstrip("/").split(maxsplit=1)[0] if cmd.initial_input else None
    agent_supplied = intent.agent is not None
    preferred_agent = intent.preferred_agent
    if preferred_agent is None and mode is AgentDispatchMode.MANUAL_PREFERENCE:
        preferred_agent = intent.agent
    fixed_agent = intent.agent if mode is AgentDispatchMode.FIXED else None
    todo_kind = None
    if cmd.role == RoleName.PREPARE_ORCHESTRATOR.value and working_slug:
        todo_kind = await _resolve_prepare_todo_kind(project_path, working_slug)
    kind_source = (
        AgentDispatchKindSource.TARGET_TODO_RECORD if todo_kind is not None else AgentDispatchKindSource.NOT_APPLICABLE
    )
    basis_digest = decision_basis_digest(
        mode=mode,
        role=cmd.role,
        # ACCEPTED may be emitted at an API origin before target kind lookup.
        # Keep the digest safe and stage-consistent; RESOLVED retains the
        # authoritative target kind in its explicit field.
        todo_kind=None,
        preferred_agent=preferred_agent,
        fixed_agent=fixed_agent,
        candidate_order=intent.candidate_order,
    )
    if not intent.accepted_at_origin:
        emit_agent_dispatch_decision(
            stage=AgentDispatchStage.ACCEPTED,
            outcome=AgentDispatchOutcome.PREPARED,
            reason=AgentDispatchReason.RECEIVED,
            request_id=cmd.request_id,
            dispatch_mode=mode,
            entry_point=cmd.entry_point,
            job_role=cmd.role,
            todo_kind=todo_kind,
            agent_supplied=agent_supplied,
            working_slug_present=working_slug is not None,
            kind_source=kind_source,
            decision_basis_digest=basis_digest,
            preferred_agent=preferred_agent,
            fixed_agent=fixed_agent,
            command_kind=command_kind,
            thinking_mode=intent.thinking_mode,
        )
    try:
        decision = await resolve_agent_dispatch(
            mode=mode,
            role=cmd.role,
            preferred_agent=preferred_agent,
            fixed_agent=fixed_agent,
            candidate_order=intent.candidate_order,
            entry_point=cmd.entry_point,
            session_kind=session_kind,
        )
    except AgentDispatchFailure as exc:
        emit_agent_dispatch_decision(
            stage=AgentDispatchStage.RESOLVED,
            outcome=AgentDispatchOutcome.REFUSED,
            reason=exc.reason,
            request_id=cmd.request_id,
            dispatch_mode=mode,
            entry_point=cmd.entry_point,
            job_role=cmd.role,
            todo_kind=todo_kind,
            agent_supplied=agent_supplied,
            working_slug_present=working_slug is not None,
            kind_source=kind_source,
            decision_basis_digest=basis_digest,
            preferred_agent=preferred_agent,
            fixed_agent=fixed_agent,
            command_kind=command_kind,
            thinking_mode=intent.thinking_mode,
        )
        raise
    intent.agent = decision.agent
    intent.dispatch_mode = mode
    intent.request_id = cmd.request_id
    intent.entry_point = cmd.entry_point
    intent.job_role = cmd.job
    intent.preferred_agent = preferred_agent
    intent.fixed_agent = fixed_agent
    intent.decision_basis_digest = basis_digest
    if intent.kind == SessionLaunchKind.AGENT_THEN_MESSAGE and intent.message is not None:
        startup_reason = (
            AgentDispatchReason.CODEX_LOADER
            if intent.invocation is not None
            else AgentDispatchReason.STARTUP_UNCHANGED_FOR_AGENT
        )
        if intent.invocation is None and intent.caller_header:
            intent.message, _, _ = format_identity_conversation(header=intent.caller_header, body=intent.message)
    else:
        startup_reason = AgentDispatchReason.STARTUP_UNCHANGED_FOR_AGENT
    emit_agent_dispatch_decision(
        stage=AgentDispatchStage.RESOLVED,
        outcome=(AgentDispatchOutcome.FALLBACK if decision.fallback_reason else AgentDispatchOutcome.SELECTED),
        reason=decision.reason,
        selected_agent=decision.agent,
        request_id=cmd.request_id,
        dispatch_mode=mode,
        entry_point=cmd.entry_point,
        job_role=cmd.role,
        todo_kind=todo_kind,
        fallback_reason=decision.fallback_reason,
        agent_supplied=agent_supplied,
        working_slug_present=working_slug is not None,
        kind_source=kind_source,
        decision_basis_digest=basis_digest,
        preferred_agent=preferred_agent,
        fixed_agent=fixed_agent,
        command_kind=command_kind,
        thinking_mode=intent.thinking_mode,
        candidate_order=decision.candidate_order,
        order_branch=decision.order_branch,
    )
    emit_agent_dispatch_decision(
        stage=AgentDispatchStage.STARTUP_PREPARED,
        outcome=AgentDispatchOutcome.PREPARED,
        reason=startup_reason,
        selected_agent=decision.agent,
        request_id=cmd.request_id,
        dispatch_mode=mode,
        entry_point=cmd.entry_point,
        job_role=cmd.role,
        todo_kind=todo_kind,
        agent_supplied=agent_supplied,
        working_slug_present=working_slug is not None,
        kind_source=kind_source,
        decision_basis_digest=basis_digest,
        preferred_agent=preferred_agent,
        fixed_agent=fixed_agent,
        command_kind=command_kind,
        thinking_mode=intent.thinking_mode,
        routing_explanation_included=False,
    )
    return decision


async def create_session(  # noqa: C901 # TODO: refactor to reduce complexity
    cmd: CreateSessionCommand,
    client: "AdapterClient",
) -> dict[str, str]:
    """Create a new tmux session.

    Args:
        cmd: CreateSessionCommand model
        client: AdapterClient

    Returns:
        Minimal session payload with session_id
    """
    del client

    # Get origin from command
    origin = cmd.origin
    if not origin:
        raise ValueError("Command missing origin")

    logger.info(
        "CreateSession: origin=%s launch_intent=%s",
        origin,
        cmd.launch_intent.kind.value if cmd.launch_intent else None,
    )

    # Origin provenance must reflect the actual source of this session creation.
    # Do not inherit origin from parent sessions.
    last_input_origin = origin
    initiator_session_id = cmd.initiator_session_id
    parent_session = None
    if initiator_session_id:
        parent_session = await db.get_session(initiator_session_id)

    computer_name = config.computer.name
    session_id = cmd.session_id or str(uuid.uuid4())
    tmux_name = "" if cmd.headless else host_pane_name(session_id)
    resolved = await resolve_session_creation_identity(cmd, parent_session, session_id)
    human_email = resolved.human_email
    human_role = resolved.human_role
    principal = resolved.principal
    project_path = resolved.project_path
    subfolder = resolved.subfolder
    working_slug = resolved.working_slug
    company = resolved.company
    company_source = resolved.company_source
    initiator_session_id = resolved.initiator_session_id
    initiator_computer = resolved.initiator_computer
    cmd_role, cmd_job = cmd.role, cmd.job
    session_kind = desk_session_kind(cmd_role, human_role, cmd.endpoint)

    decision = await _resolve_launch_intent(cmd, project_path, working_slug, session_kind)
    launch = cmd.launch_intent
    if not cmd.headless and launch and launch.kind in {SessionLaunchKind.AGENT, SessionLaunchKind.AGENT_THEN_MESSAGE}:
        if not launch.agent or not launch.thinking_mode:
            raise ValueError("Agent launch intent requires agent and thinking_mode")
        launch.resolved_model_flags = (
            await resolve_launch_model(launch.agent, launch.thinking_mode, ownership=launch_ownership(cmd.role))
        ).flags

    # tmux silently falls back to its own cwd if -c points at a non-existent directory.
    # This shows up as sessions "starting in /tmp" (or similar) even though we asked for a project dir.
    working_dir = resolve_working_dir(project_path, subfolder)
    working_dir_path = Path(working_dir)
    if not working_dir_path.is_absolute():
        raise WorkingDirectoryUnavailableError(_WORKING_DIR_NOT_ABSOLUTE_TEMPLATE.format(working_dir=working_dir))
    if not working_dir_path.exists():
        raise WorkingDirectoryUnavailableError(_WORKING_DIR_MISSING_TEMPLATE.format(working_dir=working_dir))
    if not working_dir_path.is_dir():
        raise WorkingDirectoryUnavailableError(_WORKING_DIR_NOT_A_DIRECTORY_TEMPLATE.format(working_dir=working_dir))
    working_dir = str(working_dir_path)

    if subfolder:
        if Path(subfolder).is_absolute():
            raise ValueError(f"subdir must be relative: {subfolder}")
        subfolder = subfolder.strip("/")

    # Derive working_dir from raw inputs (project_path + subfolder)
    # project_path is the base project, subfolder is the optional worktree/branch path
    if subfolder:
        working_dir = resolve_working_dir(project_path, subfolder)
        working_dir_path = Path(working_dir)
        if not working_dir_path.exists():
            working_dir_path.mkdir(parents=True, exist_ok=True)
        working_dir = str(working_dir_path)

    config_subject: str | None = None
    subject_owner: str | None = None
    try:
        subject = resolve_config_subject(working_dir_path)
        config_subject = subject.to_token() if subject is not None else None
        if subject is not None and subject.kind is ConfigSubjectKind.PROJECT:
            ownership = load_project_ownership_index().for_path(working_dir_path)
            if ownership is not None:
                owner_identity = ownership.owner_identity()
                if owner_identity is not None:
                    owner_kind, owner_slug = owner_identity
                    subject_owner = SubjectRef(ConfigSubjectKind(owner_kind.value), owner_slug).to_token()
                else:
                    subject_owner = EventHomeOwnerMarker.OWNERLESS.value
    except SubjectResolutionError as error:
        # A malformed user declaration must not refuse session creation; no subject keeps visibility at platform scope.
        logger.warning(
            _SESSION_SUBJECT_RESOLUTION_FAILED_EVENT,
            working_folder=working_dir,
            error=str(error),
        )

    # Runner-dispatched lifecycle sessions have no human caller and may inherit
    # the daemon's system principal. Establish the chain-root human from the
    # todo's persisted owner so the resolved principal is the owning human, not
    # the daemon principal. Audit-only: role (the authorization band) is left
    # untouched, and a manual start (human_email already set) is never overridden.
    if not human_email and working_slug and principal != SYSTEM_OPERATOR_PRINCIPAL:
        owner_principal = await read_todo_owner_principal(project_path, working_slug)
        if owner_principal and owner_principal.startswith("human:"):
            principal = owner_principal
            human_email = owner_principal.removeprefix("human:")

    # The title's subject is what the caller supplied, as the persisted invocation records it: never the
    # job, the activation home or the transport line, which keep their own fields.
    title_args = (
        launch.invocation.arguments if launch is not None and launch.invocation is not None else _NO_TITLE_ARGUMENTS
    )
    title = cmd.title or (
        compose_command_session_title(cmd.command, title_args, role=cmd.role)
        if cmd.command is not None
        else _NO_ASSIGNMENT_TITLE
    )

    # A desk session records its confinement in the creating write, so no
    # delivery or bootstrap ever observes it without the stamp.
    creation_metadata = cast(JsonDict, dict(cmd.origin_metadata or {}))
    if session_kind is DispatchSessionKind.HELP_DESK:
        creation_metadata[CONFINEMENT_SECTION] = {CONFINEMENT_PROFILE_KEY: LaunchProfile.HELP_DESK.value}
    # The endpoint is a root section beside the adapter sections, written with
    # the row, so every reader finds it through `EndpointStamp.from_session`.
    if cmd.endpoint is not None:
        creation_metadata[ENDPOINT_SECTION] = cmd.endpoint.to_dict()
    # An unattended procedure agent is stamped in the same write, so no listing,
    # snapshot or adapter ever observes the session without it.
    if cmd.unattended:
        creation_metadata[UNATTENDED_SECTION] = unattended_stamp()

    # Create session atomically with all known fields — the SESSION_STARTED
    # event must carry complete data so downstream consumers never see partial state.
    session = await db.create_session(
        computer_name=computer_name,
        tmux_session_name=_UNBOUND_TMUX_NAME,
        last_input_origin=last_input_origin,
        title=title,
        project_path=project_path,
        subdir=subfolder,
        config_subject=config_subject,
        subject_owner=subject_owner,
        session_id=session_id,
        command=cmd.command,
        working_slug=working_slug,
        initiator_session_id=initiator_session_id,
        initiator_computer=initiator_computer,
        detached=cmd.skip_listener_registration,
        human_email=human_email,
        human_role=human_role,
        principal=principal,
        lifecycle_status="headless" if cmd.headless else "initializing",
        role=cmd_role,
        job=cmd_job,
        company=company,
        active_agent=launch.agent if launch else None,
        thinking_mode=launch.thinking_mode if launch else None,
        native_session_id=cmd.native_session_id or (launch.native_session_id if launch else None),
        native_log_file=cmd.native_log_file,
        origin_metadata=creation_metadata,
        startup_intent=None if cmd.headless else launch,
        procedure_delivery=cmd.procedure_delivery,
        emit_session_started=False,
    )

    record_session_company_resolved(cmd.request_id, session.session_id, company, company_source, initiator_session_id)
    # An undetached AI-to-AI start establishes persistent supervision.
    if initiator_session_id and initiator_session_id != session_id and not cmd.skip_listener_registration:
        caller_tmux = parent_session.tmux_session_name if parent_session else None
        caller_computer = initiator_computer or config.computer.name
        if (parent_session is not None and parent_session.receives_hook_delivery) or (
            caller_computer != config.computer.name
        ):
            try:
                established = await establish_supervision(
                    target_session_id=session_id,
                    caller_session_id=initiator_session_id,
                    caller_tmux_session=caller_tmux or "",
                    caller_computer=caller_computer,
                    startup_work_expected=bool(cmd.initial_input or cmd.startup_work_expected),
                )
                if not established:
                    logger.debug(
                        _LISTENER_REGISTRATION_SKIPPED_EVENT,
                        caller_session_id=initiator_session_id,
                        target_session_id=session_id,
                        reason="caller_unavailable",
                    )
            except RuntimeError:
                logger.debug(
                    _LISTENER_REGISTRATION_SKIPPED_EVENT,
                    caller_session_id=initiator_session_id,
                    target_session_id=session_id,
                    reason="db_unavailable",
                )
            except Exception as exc:
                logger.warning(
                    _LISTENER_REGISTRATION_FAILED_EVENT,
                    caller_session_id=initiator_session_id,
                    target_session_id=session_id,
                    error=str(exc),
                )
        else:
            logger.debug(
                _LISTENER_REGISTRATION_SKIPPED_EVENT,
                caller_session_id=initiator_session_id,
                target_session_id=session_id,
                reason="initiator_missing_or_no_tmux",
            )
    elif initiator_session_id and initiator_session_id != session_id and cmd.skip_listener_registration:
        logger.debug(
            _LISTENER_REGISTRATION_SKIPPED_EVENT,
            caller_session_id=initiator_session_id,
            target_session_id=session_id,
            reason="command_flag",
        )

    # Merge typed origin metadata into session's origin_metadata
    if cmd.origin_metadata:
        await db.update_origin_metadata(session.session_id, last_input_origin, dict(cmd.origin_metadata))

    # NOTE: tmux creation + launch execution are handled asynchronously
    # by the daemon bootstrap task. Channel creation is deferred to UI lanes
    # on first output.

    logger.info("Created session: %s (headless=%s)", session.session_id, cmd.headless)
    result = {
        "session_id": session_id,
        "tmux_session_name": tmux_name,
    }
    if launch and launch.agent:
        result["agent"] = launch.agent
    if decision:
        result["routing_reason"] = decision.fallback_reason.value if decision.fallback_reason else decision.reason.value
    if decision:
        emit_agent_dispatch_decision(
            stage=AgentDispatchStage.SESSION_COMMITTED,
            outcome=AgentDispatchOutcome.COMMITTED,
            reason=AgentDispatchReason.SESSION_COMMITTED,
            selected_agent=decision.agent,
            request_id=cmd.request_id,
            session_id=session_id,
            dispatch_mode=launch.dispatch_mode if launch else None,
            entry_point=cmd.entry_point,
            job_role=cmd.role,
            preferred_agent=launch.preferred_agent if launch else None,
            fixed_agent=launch.fixed_agent if launch else None,
            decision_basis_digest=launch.decision_basis_digest if launch else None,
            command_kind=cmd.initial_input.lstrip("/").split(maxsplit=1)[0] if cmd.initial_input else None,
            thinking_mode=launch.thinking_mode if launch else None,
        )
    return result


async def list_sessions(*, selection: SessionListingSelection) -> list[SessionSnapshot]:
    """List sessions from local database.

    Ephemeral request/response for tool/API callers only - no DB session required.
    UI adapters (Telegram) should not have access to this command.
    """
    sessions = await db.select_sessions_for_listing(
        selection.reach,
        selection.closed_since,
        selection.session_ids,
    )

    local_name = config.computer.name
    snapshots = [await project_session_snapshot(db, session, computer=local_name) for session in sessions]
    for session, snapshot in zip(sessions, snapshots, strict=True):
        address = resolve_session_conversation_url(session)
        snapshot.conversation_url = address.url if isinstance(address, SessionAddressResolved) else None
        if not snapshot.thinking_mode:
            snapshot.thinking_mode = "slow"
        if not snapshot.status:
            snapshot.status = "active"
    return snapshots


async def list_projects() -> list[ProjectInfo]:
    """List every present session-placement entry in registry order.

    Ephemeral request/response - no DB session required.

    Returns:
        List of project info objects.
    """
    catalog = get_project_catalog_service()
    catalog.refresh()
    return [
        ProjectInfo(
            name=entry.display_name,
            description=entry.description,
            path=str(entry.root),
            subject=(
                SubjectRef(ConfigSubjectKind(entry.kind.value), entry.identity).to_token()
                if entry.identity is not None
                else EventHomeMarker.UNKNOWN.value
            ),
            owner=entry.owner,
        )
        for entry in catalog.list_entries()
    ]


async def list_projects_with_todos() -> list[ProjectInfo]:
    """List projects with their todos included (local only)."""
    raw_projects = await list_projects()
    projects_with_todos: list[ProjectInfo] = []

    for project in raw_projects:
        todos: list[TodoDTO] = []
        if project.path and is_project_checkout(project.path):
            todos = await list_todos(project.path)

        project.todos = todos
        projects_with_todos.append(project)

    return projects_with_todos


async def list_todos(project_path: str) -> list[TodoDTO]:
    """List todos for a project.

    Runs the synchronous todo assembly on a worker so store resolution cannot
    block the daemon event loop. Ephemeral request/response - no DB session
    required.

    Args:
        project_path: Absolute path to project directory

    Returns:
        List of todo objects.
    """
    return await asyncio.to_thread(
        assemble_todo_from_db,
        project_path,
        include_icebox=True,
        include_delivered=True,
        delivered_since=recently_delivered_cutoff(),
        include_removed=True,
    )


async def get_computer_info() -> ComputerInfo:
    """Return computer info including system stats.

    Ephemeral request/response - no DB session required.

    Returns:
        ComputerInfo object.
    """
    logger.debug("get_computer_info() called")

    # Build info from config - design by contract: these fields are required
    if not config.computer.user or not config.computer.role or not config.computer.host:
        raise ValueError("Computer configuration is incomplete - user, role, and host are required")

    # Gather system stats (parallel, non-blocking cpu_percent)
    memory, disk, cpu_percent = await asyncio.gather(
        asyncio.to_thread(psutil.virtual_memory),
        asyncio.to_thread(psutil.disk_usage, "/"),
        asyncio.to_thread(psutil.cpu_percent, None),
    )

    # Build typed system stats
    memory_stats: MemoryStats = {
        "total_gb": round(memory.total / (1024**3), 1),
        "available_gb": round(memory.available / (1024**3), 1),
        "percent_used": memory.percent,
    }
    disk_stats: DiskStats = {
        "total_gb": round(disk.total / (1024**3), 1),
        "free_gb": round(disk.free / (1024**3), 1),
        "percent_used": disk.percent,
    }
    cpu_stats: CpuStats = {
        "percent_used": cpu_percent,
    }
    system_stats: SystemStats = {
        "memory": memory_stats,
        "disk": disk_stats,
        "cpu": cpu_stats,
    }
    info = ComputerInfo(
        name=config.computer.name,
        status="online",
        user=config.computer.user,
        role=config.computer.role,
        host=config.computer.host,
        is_local=True,
        system_stats=system_stats,
        version=__version__,
        channel=config.deployment.channel,
        capability_set=sorted(DEFAULT_FEATURE_ID_REGISTRY.carried_set()),
        is_master=config.computer.is_master,
        conversation_adapters=sorted(local_conversation_adapters()),
    )

    logger.debug("get_computer_info() returning info: %s", info)
    return info


async def _publish_transcript_format_mismatches(mismatches: list[tuple[str, str]]) -> None:
    """Publish collected parser diagnostics without changing transcript results."""
    for agent, filename in mismatches:
        try:
            await publish_runtime_error(
                source="transcript_reader",
                message=(
                    f"Transcript parser can't read {agent} session file {filename} — file shape may have changed "
                    "in the agent CLI. Output/summary/title for this session will be empty until the parser is updated."
                ),
                severity="warning",
            )
        except Exception:
            logger.warning("Transcript format error publication failed", exc_info=True)


async def get_session_data(
    cmd: GetSessionDataCommand,
) -> SessionDataPayload:
    """Get session data from native_log_file.

    Reads the Agent session file (JSONL format) and parses to markdown.
    Uses same parsing as download functionality for consistent formatting.
    Supports timestamp filtering and character limit.

    Args:
        cmd: GetSessionDataCommand payload

    Returns:
        Dict with session data and markdown-formatted messages
    """

    # Get session from database
    session_id = cmd.session_id
    session = await db.get_session(session_id)
    if not session:
        logger.error("Session %s not found", session_id)
        return {"status": "error", "error": "Session not found"}

    def _pending_transcript_payload(reason: str) -> SessionDataPayload:
        logger.debug(
            "Transcript pending for session %s (%s)",
            session_id,
            reason,
        )
        agent_label = str(session.active_agent or "session")
        return {
            "status": "success",
            "session_id": session_id,
            "project_path": session.project_path,
            "subdir": session.subdir,
            "messages": (
                f"Transcript is not available yet for this {agent_label} session. "
                "Wait for the first completed turn (`agent_stop`) and retry."
            ),
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "last_activity": (session.last_activity.isoformat() if session.last_activity else None),
            "transcript": None,
        }

    async def _tmux_fallback_payload(reason: str) -> SessionDataPayload | None:
        tmux_session_name = getattr(session, "tmux_session_name", None)
        if not isinstance(tmux_session_name, str) or not tmux_session_name.strip():
            return None

        tail = cmd.tail_chars if cmd.tail_chars > 0 else 2000
        try:
            pane_output = await tmux_bridge.capture_pane(
                tmux_session_name,
                capture_lines=tmux_bridge.FALLBACK_CAPTURE_LINES,
            )
        except (OSError, ValueError, tmux_bridge.SubprocessTimeoutError) as exc:
            logger.warning(
                "Tmux fallback capture failed for session %s (%s): %s",
                session_id,
                reason,
                exc,
            )
            return None

        # Strip ANSI before truncation so tail slicing cannot split escape codes.
        sanitized_output = strip_ansi_codes(pane_output)
        messages = sanitized_output[-tail:] if len(sanitized_output) > tail else sanitized_output
        logger.debug(
            "Returning tmux fallback output for session %s (%s)",
            session_id,
            reason,
        )
        return {
            "status": "success",
            "session_id": session_id,
            "project_path": session.project_path,
            "subdir": session.subdir,
            "messages": messages,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "last_activity": (session.last_activity.isoformat() if session.last_activity else None),
        }

    raw_agent_name = session.active_agent or ""
    normalized_agent_name = raw_agent_name.strip().lower()
    lifecycle_status = session.lifecycle_status or ""
    closed_at_raw = session.closed_at
    session_closed = closed_at_raw is not None or lifecycle_status == "closed"
    feedback_at_raw = session.last_output_at
    has_completed_turn = feedback_at_raw is not None

    # Get native_log_file from session, or discover it if not set
    native_log_file_str = session.native_log_file

    # For Codex sessions, try to discover transcript if not yet bound
    if not native_log_file_str and normalized_agent_name == "codex" and session.native_session_id:
        logger.debug(
            "Attempting to discover Codex transcript for session %s (native_id=%s)",
            session_id,
            session.native_session_id,
        )
        discovered_path = discover_codex_transcript_path(session.native_session_id)
        if discovered_path:
            native_log_file_str = discovered_path
            logger.info(
                "Discovered Codex transcript path for session %s: %s",
                session_id,
                discovered_path,
            )
            # Update database for future queries
            await db.update_session(session_id, native_log_file=discovered_path)

    if not native_log_file_str:
        tmux_payload = await _tmux_fallback_payload("no_native_log_file")
        if tmux_payload:
            return tmux_payload
        if normalized_agent_name == "codex":
            return _pending_transcript_payload("no_native_log_file_codex")
        if not has_completed_turn and not session_closed:
            return _pending_transcript_payload("no_native_log_file_pre_stop")
        logger.error("No native_log_file for session %s", session_id)
        return {"status": "error", "error": "Session file not found"}

    native_log_file = Path(native_log_file_str)
    if not native_log_file.exists():
        tmux_payload = await _tmux_fallback_payload("native_log_file_missing")
        if tmux_payload:
            return tmux_payload
        if normalized_agent_name == "codex":
            return _pending_transcript_payload("native_log_file_missing_on_disk_codex")
        if not has_completed_turn and not session_closed:
            return _pending_transcript_payload("native_log_file_missing_pre_stop")
        logger.error("Native session file does not exist: %s", native_log_file)
        return {"status": "error", "error": "Session file does not exist"}

    if not raw_agent_name:
        logger.error("Session %s missing active_agent metadata", session_id)
        return {"status": "error", "error": "Active agent unknown"}

    try:
        agent_name = AgentName.from_str(raw_agent_name)
    except ValueError as exc:
        logger.error("Unknown agent for session %s: %s", session_id, exc)
        return {"status": "error", "error": str(exc)}

    transcript_reader = TRANSCRIPT_READERS[agent_name]

    # Parse session transcript to markdown with filtering
    try:
        transcript_mismatches: list[tuple[str, str]] = []
        markdown_content = parse_session_transcript(
            str(native_log_file),
            session.title,
            agent_name=agent_name,
            since_timestamp=cmd.since_timestamp,
            until_timestamp=cmd.until_timestamp,
            tail_chars=cmd.tail_chars if cmd.tail_chars > 0 else 2000,
            on_format_mismatch=lambda agent, path, _error: transcript_mismatches.append((agent, path.name)),
        )
        await _publish_transcript_format_mismatches(transcript_mismatches)
        logger.info(
            "Parsed %s transcript (%d bytes) for session %s",
            transcript_reader.display_name,
            len(markdown_content),
            session_id,
        )
    except Exception as e:
        logger.error("Failed to parse session file %s: %s", native_log_file, e)
        return {"status": "error", "error": f"Failed to parse session file: {e}"}

    return {
        "status": "success",
        "session_id": session_id,
        "project_path": session.project_path,
        "subdir": session.subdir,
        "messages": markdown_content,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "last_activity": (session.last_activity.isoformat() if session.last_activity else None),
    }


@with_session
async def close_session(
    session: Session,
    _cmd: CloseSessionCommand,
    client: "AdapterClient",
) -> None:
    """Close session - kill tmux, delete DB record, clean up resources.

    Routing: when the stored computer_name names a different host, the command is
    forwarded to that remote peer — but only if the session is not actually present
    locally. A live local tmux session means it is local (computer_name may have
    drifted via a host/config rename), so it is closed here regardless of the name.
    """
    # Route to a remote peer only when the stored name says remote AND the session is
    # not actually present on this host. computer_name is frozen at creation and can
    # drift (host rename / config-name correction), so trusting it alone would forward a
    # locally-running session to a phantom peer and leave it un-closable. Local tmux
    # presence is the ground truth for locality.
    local_computer = config.computer.name
    if session.computer_name and session.computer_name != local_computer:
        # Stored name says remote — but verify against ground truth before forwarding.
        # computer_name is frozen at creation and can drift (host rename / config-name
        # correction); forwarding a locally-running session to a phantom peer leaves it
        # un-closable. A live local tmux session means it is local, regardless of the name.
        locally_present = bool(session.tmux_session_name) and await tmux_bridge.session_exists(
            session.tmux_session_name, log_missing=False
        )
        if not locally_present:
            logger.info(
                "Forwarding close_session to remote computer %s for session %s",
                session.computer_name,
                session.session_id,
            )
            command = CloseSessionCommand(session_id=session.session_id, request_id=_cmd.request_id)
            command.computer = session.computer_name
            await forward_command_to_peer(client, command, principal=SYSTEM_DAEMON_PRINCIPAL)
            return

    # closed_at is the sole "finalized" signal. A session marked only
    # lifecycle_status="closing" with no closed_at is a stuck/in-flight close — NOT
    # terminal. It must fall through to terminate_session so closed_at actually gets
    # set; otherwise the row is hidden but never finalized and resurfaces from caches.
    if session.closed_at or session.lifecycle_status == "closed":
        if has_pending_channel_cleanup(session):
            await terminate_session(
                session.session_id,
                client,
                reason="close_session_cleanup_replay",
                session=session,
            )
            return
        logger.info("Session %s already terminal; nothing to close", session.session_id)
        return

    try:
        await terminate_session(
            session.session_id,
            client,
            reason="close_session",
            session=session,
        )
    except Exception as error:
        logger.error(_SESSION_CLOSE_FAILED_EVENT, session.session_id, error, exc_info=True)
        await recover_failed_close(session.session_id)
        raise


async def end_session(
    cmd: CloseSessionCommand,
    client: "AdapterClient",
) -> EndSessionHandlerResult:
    """End a session via tool/API request.

    Similar to close_session but designed for direct command calls.
    Kills tmux, deletes the session, cleans up resources.

    Args:
        session_id: Session identifier
        client: AdapterClient for channel operations

    Returns:
        dict with status and message
    """
    # Get session from DB
    session = await db.get_session(cmd.session_id)
    if not session:
        return {"status": "error", "message": f"Session {cmd.session_id} not found"}

    # closed_at is the sole "finalized" signal. A session marked only
    # lifecycle_status="closing" with no closed_at is a stuck/in-flight close
    # (e.g. a prior close interrupted before finalize) — NOT terminal. It must
    # fall through to terminate_session so closed_at actually gets set; otherwise
    # the row is hidden but never finalized and resurfaces from cached snapshots.
    if session.closed_at or session.lifecycle_status == "closed":
        logger.info("Session %s already terminal; replaying session_closed", cmd.session_id)
        await publish_session_source_change(session.session_id, RuntimeSessionChange.CLOSED)
        return {
            "status": "success",
            "message": f"Session {cmd.session_id} already closed; session_closed replayed",
        }

    terminated = await terminate_session(
        cmd.session_id,
        client,
        reason="end_session",
        session=session,
    )
    if not terminated:
        # The session exists (fetched above); terminate_session returns False only
        # when a close is already in flight — benign, that close will finalize.
        return {"status": "success", "message": f"Session {cmd.session_id} close already in progress"}

    return {
        "status": "success",
        "message": f"Session {cmd.session_id} ended successfully",
    }
