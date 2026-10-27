"""Session action endpoints (keys, file, revive, run, result, escalate)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from instrukt_ai_logging import get_logger

from teleclaude.api.agent_dispatch_errors import (
    agent_dispatch_http_refusal,
    emit_run_accepted,
    emit_run_outcome,
    present_routing_explanation,
    read_routing_reason,
    run_dispatch_refusal_reason,
    run_refusal_outcome,
)
from teleclaude.api.auth import (
    CallerIdentity,
    caller_role_for_session,
    carried_caller,
    resolve_caller_provenance,
)
from teleclaude.api.driver_start_guard import enforce_driver_start_guard, terminal_driver_email
from teleclaude.api.run_session_job import normalize_job_run_request
from teleclaude.api.run_session_procedure import manual_activation
from teleclaude.api.run_session_refusals import RunSessionRefusal, resolve_run_session_agent
from teleclaude.api.run_session_shapes import RunSessionPlan
from teleclaude.api.session_authority import ACT_RESTART, ACT_UNSUBSCRIBE, refuse_act_on_dispatching_orchestrator
from teleclaude.api.session_messages_query import SessionMessagesQuery, parse_session_messages_query
from teleclaude.api.session_pane_routes import router as session_pane_router
from teleclaude.api.session_remote import is_remote_create_target
from teleclaude.api.session_result_routes import router as session_result_router
from teleclaude.api.session_route_helpers import dispatch_caller_command
from teleclaude.api.sessions_coordinate_routes import router as sessions_coordinate_router
from teleclaude.api.sessions_personal_assistant_routes import (
    configure as configure_personal_assistant_routes,
)
from teleclaude.api.sessions_personal_assistant_routes import (
    router as personal_assistant_router,
)
from teleclaude.api_models import (
    CreateSessionRequest,
    CreateSessionResponseDTO,
    FileUploadRequest,
    KeysRequest,
    RunSessionRequest,
    SessionMessagesDTO,
)
from teleclaude.api_session_actions_models import AgentRestartRequest, AgentRestartResponseDTO, EscalateRequest
from teleclaude.config.machine import config
from teleclaude.config.referents import ReferentKind, unregistered_referent
from teleclaude.config.registered_homes import project_folder
from teleclaude.constants import WORKTREE_DIR
from teleclaude.core import agents as agents_module
from teleclaude.core.agent_dispatch import (
    AgentDispatchFailure,
    AgentDispatchReason,
    classify_fresh_agent_preference,
    decision_basis_digest,
)
from teleclaude.core.agents import get_known_agents
from teleclaude.core.codex_transcript import discover_codex_transcript_path
from teleclaude.core.command_handlers import resolve_working_slug_from_subdir, select_handoff_successor
from teleclaude.core.command_mapper import KEY_COMMANDS, CommandMapper
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.command_service import UnsubscribeUnknownSessionError
from teleclaude.core.db import db
from teleclaude.core.models import (
    AgentDispatchMode,
    JsonDict,
    MessageMetadata,
    SessionEntryPoint,
    SessionLaunchIntent,
    SessionLaunchKind,
)
from teleclaude.core.models._adapter import TerminalOriginMetadata
from teleclaude.core.next_machine.lanes import WORKTREE_BOUND_PROCEDURES
from teleclaude.core.next_machine.manual_start import DriverStartGuardResult
from teleclaude.core.operations.service import get_operations_service
from teleclaude.core.origins import InputOrigin
from teleclaude.core.procedure_activation_runner import home_agent_guard, standing_home_agent
from teleclaude.core.procedure_entry import (
    EntryContext,
    EntryRefusal,
    job_entry,
    resolve_entry,
    with_additional_context,
)
from teleclaude.core.roles import resolve_session_role
from teleclaude.core.session_message_projection import (
    SessionMessageProjectionOptions,
    build_session_messages_dto,
)
from teleclaude.core.session_utils import split_project_path_and_subdir
from teleclaude.helpers.agent_types import ThinkingMode
from teleclaude.project_manifest_runtime import load_registered_entries
from teleclaude.types.activation_home import ActivationHome
from teleclaude.types.commands import (
    CreateSessionCommand,
    HandoffAgentCommand,
    InternalCommand,
    RestartAgentCommand,
    ReviveAgentCommand,
    UnsubscribeSessionCommand,
)
from teleclaude.utils.transcript_discovery import discover_transcripts, extract_session_id, recover_native_project

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
from teleclaude.types.commands import SystemCommand

logger = get_logger(__name__)
COMMAND_PREFIX = "/"
_ESCALATE_NOTIFIED_KEY = "notified"
_HOME_AGENT_STANDING_TEMPLATE = (
    "{procedure_id} already has its agent for {home}: session {session_id}; message it with telec sessions send"
)
_ESCALATE_WARNING_KEY = "warning"

_STATE = SimpleNamespace(client=None)
router = APIRouter()
router.include_router(sessions_coordinate_router)
router.include_router(session_pane_router)
router.include_router(session_result_router)
router.include_router(personal_assistant_router)


def configure(client: AdapterClient | None = None) -> None:
    """Wire client; called from APIServer at construction."""
    if client is not None:
        _STATE.client = client
        configure_personal_assistant_routes(client=client)


def _build_metadata(*, origin: str = InputOrigin.TERMINAL.value, **kwargs: object) -> MessageMetadata:
    """Build API boundary metadata with explicit origin."""
    return MessageMetadata(origin=origin, **kwargs)


def _native_session_exists_for_agent(native_session_id: str, agent: str) -> bool:
    """Return whether a native session ID resolves for the requested agent."""
    if not native_session_id:
        return False

    try:
        agent_name = agents_module.AgentName.from_str(agent)
    except ValueError:
        return False

    if agent_name is agents_module.AgentName.CODEX:
        return discover_codex_transcript_path(native_session_id) is not None

    for transcript in discover_transcripts([agent_name]):
        if extract_session_id(transcript.path, agent_name) == native_session_id:
            return True
    return False


async def _resolve_revive_session_id(
    http_request: Request,
    session_id: str,
    agent: str | None,
    identity: CallerIdentity,
) -> str:
    """Resolve a TeleClaude session id for revive requests.

    When an agent is specified and no existing DB mapping exists, validates that the
    native session ID resolves on the agent's filesystem before creating a new session.
    Raises HTTPException(404) if the native ID cannot be found.
    """
    if not agent:
        return session_id

    resolved = await db.get_session_by_field("native_session_id", session_id, include_initializing=True)
    if resolved:
        if resolved.active_agent and resolved.active_agent != agent:
            raise HTTPException(
                status_code=409,
                detail=f"Native session belongs to agent '{resolved.active_agent}', not '{agent}'",
            )
        return resolved.session_id

    if not _native_session_exists_for_agent(session_id, agent):
        raise HTTPException(status_code=404, detail=f"Native session ID is not valid for agent '{agent}'")

    new_session_id = str(uuid.uuid4())
    project_path: str | None = None
    subdir: str | None = None
    title: str | None = None
    origin_context = await db.get_origin_revival_context_for_native_session(session_id)
    if origin_context is not None:
        project_path, subdir, title = origin_context.project_path, origin_context.subdir, origin_context.title
    else:
        agent_name = agents_module.AgentName.from_str(agent)
        caller_cwd = http_request.query_params.get("project")
        recovered_project = recover_native_project(session_id, agent_name, caller_cwd)
        if recovered_project is None:
            raise HTTPException(
                status_code=422,
                detail="Cannot locate the native session's project; re-run revive from that project directory",
            )
        registry_roots = [str(entry.path) for entry in load_registered_entries() if entry.is_present]
        project_path, subdir = split_project_path_and_subdir(recovered_project, registry_roots)

    cmd = CreateSessionCommand(
        session_id=new_session_id,
        headless=True,
        native_session_id=session_id,
        native_log_file=None,
        project_path=project_path or "",
        subdir=subdir,
        title=title,
        origin=InputOrigin.TERMINAL.value,
        initiator_session_id=identity.session_id or None,
        initiator_computer=config.computer.name if identity.session_id else None,
        origin_metadata=TerminalOriginMetadata(email=identity.email) if identity.email else None,
        launch_intent=SessionLaunchIntent(
            kind=SessionLaunchKind.AGENT,
            agent=agent,
            native_session_id=session_id,
            dispatch_mode=AgentDispatchMode.FIXED,
        ),
        entry_point=SessionEntryPoint.SYSTEM,
    )
    await get_command_service().create_session(cmd)
    return new_session_id


@asynccontextmanager
async def guard_generic_create_session(
    request: CreateSessionRequest,
    cmd: object,
    identity: CallerIdentity,
) -> AsyncIterator[DriverStartGuardResult]:
    """Guard generic session creation against duplicate drivers, holding the todo's start section.

    An interactive procedure invocation arrives with the procedure and the role it declares; ordinary
    conversation carries neither and passes the guard unclassified. The caller creates the session
    inside the context (see :func:`enforce_driver_start_guard`); a create that stays on this computer
    gets its session id assigned here so a colliding start can name it.
    """
    if not isinstance(cmd, CreateSessionCommand):
        yield DriverStartGuardResult()
        return
    local_target = not is_remote_create_target(request.computer, config.computer.name)
    if local_target and cmd.session_id is None:
        cmd.session_id = str(uuid.uuid4())
    working_slug = resolve_working_slug_from_subdir(request.subdir) or cmd.working_slug
    async with enforce_driver_start_guard(
        project_path=request.project_path,
        working_slug=working_slug,
        procedure_id=cmd.command,
        role=cmd.role,
        caller_session_id=identity.session_id,
        caller_human_email=terminal_driver_email(identity),
        thinking_mode=cmd.launch_intent.thinking_mode if cmd.launch_intent else "",
        starting_session_id=cmd.session_id,
        local_target=local_target,
    ) as guard_result:
        yield guard_result


def _prepare_run_session(
    request: RunSessionRequest,
    identity: CallerIdentity,
    entry_point: SessionEntryPoint,
) -> RunSessionPlan:
    """Resolve a run-session request through the procedure entry into a create-session plan."""
    effective_agent = resolve_run_session_agent(request)
    dispatch_mode, preferred_agent = classify_fresh_agent_preference(effective_agent, caller_role=identity.role)
    caller_mode = ThinkingMode(request.thinking_mode) if request.thinking_mode is not None else None
    entry = EntryContext()
    company = request.company
    project_path = request.project
    subfolder: str | None = request.subfolder or None
    activation_home: ActivationHome | None = None
    if request.job is not None:
        agents, job_mode, job_name, procedure_token = normalize_job_run_request(request, identity)
        entry = job_entry(job_name, agents, ThinkingMode(job_mode.value))
        entry_point = SessionEntryPoint.CRON
    else:
        procedure_token = request.command
        activation = manual_activation(request, procedure_token)
        if activation is not None:
            entry, company, activation_home = activation.entry, activation.home.company, activation.home
            project_path, subfolder = str(activation.folder), None
            entry_point = SessionEntryPoint.PROCEDURE_ACTIVATION
    session_id = str(uuid.uuid4())
    try:
        resolved = resolve_entry(
            procedure_token=procedure_token,
            arguments=request.args,
            project_root=Path(project_path),
            caller=resolve_session_role(identity.role, identity.session_id),
            entry=entry,
            caller_mode=caller_mode,
            additional_context=request.additional_context,
        )
    except EntryRefusal as exc:
        raise RunSessionRefusal(status_code=exc.status_code, detail=exc.detail, reason=exc.reason) from exc
    full_command = f"{resolved.procedure_id} {resolved.arguments}" if resolved.arguments else resolved.procedure_id
    full_command = with_additional_context(full_command, request.additional_context)
    startup_message = resolved.loader
    if resolved.working_slug and resolved.procedure_id in WORKTREE_BOUND_PROCEDURES:
        expected_subfolder = f"{WORKTREE_DIR}/{resolved.working_slug}"
        if request.subfolder != expected_subfolder:
            actual_subfolder = request.subfolder or "<empty>"
            raise RunSessionRefusal(
                status_code=400,
                detail=(
                    f"{resolved.procedure_id} for slug '{resolved.working_slug}' requires subfolder "
                    f"'{expected_subfolder}', received '{actual_subfolder}'"
                ),
                reason=AgentDispatchReason.WORKTREE_MISMATCH,
            )
    # A hand-started procedure agent runs as an event-started one does: under the system principal,
    # with no dispatcher, so the runner and a later hand start both recognize it as the home's agent.
    origin_metadata: TerminalOriginMetadata | None = None
    if identity.email and activation_home is None:
        origin_metadata = TerminalOriginMetadata(email=identity.email)
    initiator_session_id = (identity.session_id or None) if activation_home is None else None
    return RunSessionPlan(
        effective_agent=effective_agent,
        full_command=full_command,
        launch_intent=SessionLaunchIntent(
            kind=SessionLaunchKind.AGENT_THEN_MESSAGE,
            agent=effective_agent,
            thinking_mode=resolved.thinking_mode.value,
            message=startup_message,
            dispatch_mode=dispatch_mode,
            preferred_agent=preferred_agent,
            candidate_order=resolved.agents,
            invocation=resolved.record,
        ),
        initiator_session_id=initiator_session_id,
        origin_metadata=origin_metadata,
        role=resolved.role.name.value,
        job=entry.job,
        company=company,
        command=resolved.procedure_id,
        working_slug=resolved.working_slug,
        entry_point=entry_point,
        session_id=session_id,
        project_path=project_path,
        subfolder=subfolder,
        activation_home=activation_home,
    )


@router.post("/sessions/{session_id}/keys")
async def send_keys_endpoint(
    session_id: str,
    request: KeysRequest,
    identity: CallerIdentity = Depends(carried_caller),
) -> dict[str, object]:  # guard: loose-dict - API boundary
    """Send key command to session."""
    try:
        args: list[str] = []
        if request.count:
            args = [str(request.count)]
        if request.key not in KEY_COMMANDS:
            raise HTTPException(status_code=400, detail=f"Unsupported key command: {request.key}")
        metadata = _build_metadata()
        cmd = CommandMapper.map_api_input(
            "keys",
            {"session_id": session_id, "key": request.key, "args": args},
            metadata,
        )
        await dispatch_caller_command(_STATE.client, cmd, identity)
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("send_keys failed (session=%s): %s", session_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send keys: {e}") from e


@router.post("/sessions/self/file")
async def send_file_endpoint(
    request: FileUploadRequest,
    identity: CallerIdentity = Depends(carried_caller),
) -> dict[str, object]:  # guard: loose-dict - API boundary
    """Send a file attachment to the session's user."""
    session_id = identity.session_id
    cmd = SystemCommand(
        command="deliver_file",
        session_id=session_id,
        data={
            "file_path": request.file_path,
            "filename": request.filename,
            "caption": request.caption,
            "file_size": request.file_size,
        },
    )
    try:
        return await get_command_service().deliver_file(cmd)  # type: ignore[return-value]
    except Exception as e:
        logger.error("send_file failed (session=%s): %s", session_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send file: {e}") from e


@router.post("/sessions/{session_id}/agent-restart", status_code=202)
async def agent_restart(
    session_id: str,
    restart_request: AgentRestartRequest | None = None,
    identity: CallerIdentity = Depends(carried_caller),
) -> AgentRestartResponseDTO:
    """Restart agent in session (preserves conversation via --resume), or hand off to a successor.

    Both branches are RECEIPT commands: this returns the operation's receipt
    immediately, and the terminal outcome is delivered to the caller and
    readable at ``telec operations get <operation_id>``.
    """
    try:
        await refuse_act_on_dispatching_orchestrator(identity, session_id, ACT_RESTART)
        logger.info("API agent_restart requested (session=%s, origin=api)", session_id)

        handoff = restart_request.handoff if restart_request else False
        session = await db.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        if not session.active_agent:
            raise HTTPException(status_code=409, detail="No active agent for this session")
        if not session.native_session_id and not handoff:
            raise HTTPException(status_code=409, detail="No native session ID - start agent first")

        self_restart = restart_request.self_restart if restart_request else False
        agent = restart_request.agent.value if restart_request and restart_request.agent else None
        request_id = str(uuid.uuid4())
        caller = await resolve_caller_provenance(identity)
        selected_agent: str | None = None

        cmd: HandoffAgentCommand | RestartAgentCommand
        if handoff:
            try:
                cmd = await select_handoff_successor(
                    session,
                    agent_name=agent,
                    caller_role=identity.role,
                    request_id=request_id,
                )
            except AgentDispatchFailure as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            selected_agent = cmd.agent_name
        else:
            cmd = RestartAgentCommand(session_id=session_id, self_restart=self_restart, request_id=request_id)
        cmd.caller = caller

        receipt = await get_operations_service().submit(cmd, caller=caller, client_request_id=request_id)
        return AgentRestartResponseDTO(**receipt, selected_agent=selected_agent)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("agent_restart failed for session %s: %s", session_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to restart agent: {e}") from e


@router.post("/sessions/{session_id}/revive")
async def revive_session(
    http_request: Request,
    session_id: str,
    agent: str | None = Query(None, description="When provided, session_id is a native agent session ID"),
    identity: CallerIdentity = Depends(carried_caller),
) -> CreateSessionResponseDTO:
    """Revive a session by TeleClaude or native session ID."""
    session_id = await _resolve_revive_session_id(http_request, session_id, agent, identity)
    try:
        session = await db.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        if not session.active_agent:
            raise HTTPException(status_code=409, detail="No active agent for this session")
        if not session.native_session_id:
            raise HTTPException(status_code=409, detail="No native session ID - start agent first")

        cmd = ReviveAgentCommand(session_id=session_id)
        cmd.caller = await resolve_caller_provenance(identity)
        result = await dispatch_caller_command(_STATE.client, cmd, identity)
        if isinstance(result, tuple | list) and len(result) >= 2:
            success = bool(result[0])
            error = str(result[1]) if result[1] else None
        else:
            success, error = (True, None)
        if not success:
            detail = error or "Failed to revive session"
            raise HTTPException(status_code=409, detail=detail)

        refreshed = await db.get_session(session_id)
        tmux_session_name = refreshed.tmux_session_name if refreshed and refreshed.tmux_session_name else ""
        return CreateSessionResponseDTO(
            status="success",
            session_id=session_id,
            tmux_session_name=tmux_session_name,
            agent=session.active_agent if session.active_agent in get_known_agents() else None,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("revive_session failed for session %s: %s", session_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to revive session: {e}") from e


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    query: SessionMessagesQuery = Depends(parse_session_messages_query),
    _identity: CallerIdentity = Depends(carried_caller),
) -> SessionMessagesDTO:
    """Get structured messages from a session's transcript files."""
    try:
        options = SessionMessageProjectionOptions(
            since=query.since,
            include_tools=query.include_tools,
            include_thinking=query.include_thinking,
            tail_chars=query.tail_chars,
            tail_scope=query.tail_scope,
        )
        target_session = await db.get_session(session_id)
        if target_session is None:
            raise LookupError("Session not found")
        recipient_role = caller_role_for_session(_identity, target_session)
        return await build_session_messages_dto(
            session_id,
            recipient_email=_identity.email,
            recipient_role=recipient_role,
            options=options,
            database=db,
            command_service=get_command_service(),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_session_messages failed (session=%s): %s", session_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get messages: {e}") from e


# =====================================================================
# Tool CLI endpoints receive caller identity resolved by the requesting client.
# =====================================================================


def _with_project_folder(request: RunSessionRequest) -> RunSessionRequest:
    """The request naming its project by path: a registered project identity is resolved to its folder here."""
    folder = project_folder(request.project)
    if folder is None:
        raise RunSessionRefusal(
            status_code=404,
            detail=str(unregistered_referent(ReferentKind.PROJECT, request.project)),
            reason=AgentDispatchReason.PROJECT_REQUIRED,
        )
    return request.model_copy(update={"project": str(folder)})


async def _run_session(
    request: RunSessionRequest,
    identity: CallerIdentity,
    *,
    entry_point: SessionEntryPoint,
) -> CreateSessionResponseDTO:
    """Run a published entry procedure on a new agent session."""
    request_id = str(uuid.uuid4())
    command_kind = request.command.lstrip(COMMAND_PREFIX) or None
    request_entry_point = SessionEntryPoint.CRON if request.job is not None else entry_point
    agent_supplied = "agent" in request.model_fields_set
    requested_agent = request.agent if agent_supplied else None
    dispatch_mode, preferred_agent = classify_fresh_agent_preference(
        requested_agent,
        caller_role=identity.role,
    )
    fixed_agent = None
    basis_digest = decision_basis_digest(
        mode=dispatch_mode,
        role=None,
        todo_kind=None,
        preferred_agent=preferred_agent,
        fixed_agent=fixed_agent,
    )
    emit_run_accepted(
        request_id=request_id,
        dispatch_mode=dispatch_mode,
        agent_supplied=agent_supplied,
        entry_point=request_entry_point,
        command_kind=command_kind,
        working_slug_present=False,
        caller_kind_present=False,
        preferred_agent=preferred_agent,
        fixed_agent=fixed_agent,
        decision_basis_digest=basis_digest,
    )
    try:
        if not request.project:
            raise RunSessionRefusal(
                status_code=400, detail="project required", reason=AgentDispatchReason.PROJECT_REQUIRED
            )
        request = _with_project_folder(request)
        plan = _prepare_run_session(request, identity, request_entry_point)
    except RunSessionRefusal as exc:
        emit_run_outcome(
            selected_agent=None,
            request_id=request_id,
            entry_point=request_entry_point,
            dispatch_mode=dispatch_mode,
            outcome=run_refusal_outcome(exc.reason),
            reason=exc.reason,
        )
        raise
    except AgentDispatchFailure as exc:
        refusal = agent_dispatch_http_refusal(exc)
        if refusal is None:
            raise
        emit_run_outcome(
            selected_agent=None,
            request_id=request_id,
            entry_point=request_entry_point,
            dispatch_mode=dispatch_mode,
            outcome=run_refusal_outcome(exc.reason),
            reason=exc.reason,
            error=True,
        )
        raise refusal from exc

    if plan.activation_home is None:
        return await _create_planned_session(request, identity, plan, dispatch_mode, request_id)
    async with home_agent_guard(plan.command, plan.activation_home):
        standing = await standing_home_agent(plan.command, plan.activation_home)
        if standing is not None:
            emit_run_outcome(
                selected_agent=None,
                request_id=request_id,
                entry_point=plan.entry_point,
                dispatch_mode=dispatch_mode,
                outcome=run_refusal_outcome(AgentDispatchReason.RUN_REQUEST_REJECTED),
                reason=AgentDispatchReason.RUN_REQUEST_REJECTED,
            )
            raise RunSessionRefusal(
                status_code=409,
                detail=_HOME_AGENT_STANDING_TEMPLATE.format(
                    procedure_id=plan.command,
                    home=plan.activation_home.to_token(),
                    session_id=standing.session_id,
                ),
                reason=AgentDispatchReason.RUN_REQUEST_REJECTED,
            )
        return await _create_planned_session(request, identity, plan, dispatch_mode, request_id)


async def _create_planned_session(
    request: RunSessionRequest,
    identity: CallerIdentity,
    plan: RunSessionPlan,
    dispatch_mode: AgentDispatchMode,
    request_id: str,
) -> CreateSessionResponseDTO:
    """Create the planned session and present its routing outcome."""
    metadata = _build_metadata(
        project_path=plan.project_path,
        subdir=plan.subfolder,
        origin_metadata=plan.origin_metadata,
        role=plan.role,
        job=plan.job,
        company=plan.company,
    )
    metadata.launch_intent = plan.launch_intent
    dispatch_mode = plan.launch_intent.dispatch_mode or dispatch_mode

    cmd = CommandMapper.map_api_input(
        "new_session",
        {
            "skip_listener_registration": request.detach,
            "initiator_session_id": plan.initiator_session_id,
            "initial_input": plan.full_command,
        },
        metadata,
    )
    if isinstance(cmd, CreateSessionCommand):
        cmd.session_id = plan.session_id
        cmd.command = plan.command
        cmd.working_slug = plan.working_slug
        cmd.entry_point = plan.entry_point
        cmd.request_id = request_id
        if cmd.launch_intent is not None:
            cmd.launch_intent.accepted_at_origin = True
    try:
        async with enforce_driver_start_guard(
            project_path=plan.project_path,
            working_slug=plan.working_slug,
            procedure_id=plan.command,
            role=plan.role,
            caller_session_id=plan.initiator_session_id,
            caller_human_email=terminal_driver_email(identity),
            thinking_mode=plan.launch_intent.thinking_mode if plan.launch_intent else "",
            starting_session_id=plan.session_id,
        ) as guard_result:
            data = await _dispatch_planned_session(cmd, identity, plan, dispatch_mode)
    except RunSessionRefusal as exc:
        emit_run_outcome(
            selected_agent=None,
            request_id=request_id,
            entry_point=plan.entry_point,
            dispatch_mode=dispatch_mode,
            outcome=run_refusal_outcome(exc.reason),
            reason=exc.reason,
        )
        raise
    success_reason = (
        AgentDispatchReason.HELD_WITHOUT_DRIVER
        if guard_result.held_without_driver
        else AgentDispatchReason.DISPATCH_PRIVILEGE_ALLOWED
        if plan.job and identity.role
        else AgentDispatchReason.WORKING_SLUG_INFERRED
        if plan.working_slug
        else None
    )
    session_id = data.get("session_id")
    tmux_session_name = data.get("tmux_session_name")
    if not session_id or not tmux_session_name:
        raise HTTPException(status_code=500, detail="Failed to create session")
    routing_explanation = present_routing_explanation(
        data,
        human_facing=not identity.role and bool(identity.email),
        request_id=cmd.request_id,
        session_id=str(session_id),
        entry_point=plan.entry_point,
    )
    emit_run_outcome(
        selected_agent=data.get("agent") if isinstance(data.get("agent"), str) else None,
        request_id=cmd.request_id,
        session_id=str(session_id),
        entry_point=plan.entry_point,
        dispatch_mode=dispatch_mode,
        reason=success_reason,
        working_slug_present=True if success_reason is AgentDispatchReason.WORKING_SLUG_INFERRED else None,
    )
    return CreateSessionResponseDTO(
        status="success",
        session_id=str(session_id),
        tmux_session_name=str(tmux_session_name),
        agent=data.get("agent") if isinstance(data.get("agent"), str) else None,
        routing_explanation=routing_explanation,
        routing_reason=read_routing_reason(data),
    )


async def _dispatch_planned_session(
    cmd: InternalCommand,
    identity: CallerIdentity,
    plan: RunSessionPlan,
    dispatch_mode: AgentDispatchMode,
) -> JsonDict:
    """Dispatch the create command and return its payload, mapping dispatch failures to API refusals."""
    try:
        data = await dispatch_caller_command(_STATE.client, cmd, identity)
        if not isinstance(data, dict):
            raise HTTPException(status_code=500, detail="Failed to create session")
        return data
    except HTTPException:
        raise
    except Exception as e:
        refusal = agent_dispatch_http_refusal(e)
        if refusal:
            reason = run_dispatch_refusal_reason(e)
            if reason is not None:
                emit_run_outcome(
                    selected_agent=None,
                    request_id=cmd.request_id,
                    entry_point=plan.entry_point,
                    dispatch_mode=dispatch_mode,
                    outcome=run_refusal_outcome(reason),
                    reason=reason,
                )
            raise refusal from e
        logger.error("run_session failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to run session: {e}") from e


@router.post("/sessions/run", response_model_exclude_none=True)
async def run_session(
    request: RunSessionRequest,
    identity: CallerIdentity = Depends(carried_caller),
) -> CreateSessionResponseDTO:
    """Run a public request with API-created provenance only."""
    return await _run_session(request, identity, entry_point=SessionEntryPoint.RUN_SESSION_API)


@router.post("/sessions/{session_id}/unsubscribe")
async def unsubscribe_session(
    session_id: str,
    identity: CallerIdentity = Depends(carried_caller),
) -> dict[str, object]:  # guard: loose-dict - API boundary
    """Stop caring about a target session — umbrella verb across both subscription axes.

    Removes the caller's listener row (if any) AND severs any active direct link
    the caller holds with the target. Idempotent for a session that exists: empty
    state returns success with both action flags false. An unknown session is
    refused as 404 naming the session id and the computer.
    See `local/projects/teleclaude/spec/session-subscriptions`.
    """
    await refuse_act_on_dispatching_orchestrator(identity, session_id, ACT_UNSUBSCRIBE)
    cmd = UnsubscribeSessionCommand(session_id=session_id, caller_session_id=identity.session_id)
    try:
        result = await dispatch_caller_command(_STATE.client, cmd, identity)
    except UnsubscribeUnknownSessionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(result, dict):
        return {"status": "success", **result}
    return {"status": "success", "listener_removed": False, "link_closed": False, "link_id": None}


@router.post("/sessions/self/escalate")
async def escalate_session(
    request: EscalateRequest,
    identity: CallerIdentity = Depends(carried_caller),
) -> dict[str, object]:  # guard: loose-dict - API boundary
    """Escalate a help-desk session to the admins of the home that owns its desk.

    Dispatches through CommandService.escalate_session() as an IMMEDIATE
    SystemCommand and returns 200 with the result; a refused or undelivered
    escalation is 503 with the reason. Requires dual-factor caller identity.
    """
    cmd = SystemCommand(
        command="escalate_session",
        session_id=identity.session_id,
        data={
            "customer_name": request.customer_name,
            "reason": request.reason,
            "context_summary": request.context_summary,
        },
    )
    try:
        result = await get_command_service().escalate_session(cmd)
        return JSONResponse(  # type: ignore[return-value]  # pyright: ignore[reportReturnType]
            status_code=200,
            content={
                "status": "success",
                _ESCALATE_NOTIFIED_KEY: result.get(_ESCALATE_NOTIFIED_KEY) if isinstance(result, dict) else None,  # type: ignore[union-attr]
                _ESCALATE_WARNING_KEY: result.get(_ESCALATE_WARNING_KEY) if isinstance(result, dict) else None,  # type: ignore[union-attr]
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
