"""Agent start, resume, restart, and run-command handlers."""

import asyncio
import hashlib
import json
import os
import shlex
import signal
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.config._models import AgentConfig
from teleclaude.config.machine import config
from teleclaude.constants import COMMAND_ROLE_MAP, RESTART_CONTINUATION_STIMULUS
from teleclaude.core import tmux_bridge, tmux_io
from teleclaude.core.agent_availability import launch_ownership
from teleclaude.core.agent_dispatch import (
    AgentDispatchFailure,
    AgentDispatchOutcome,
    AgentDispatchStage,
    classify_fresh_agent_preference,
    desk_session_kind,
    emit_agent_dispatch_decision,
    emit_agent_launch_started,
    resolve_agent_dispatch,
    resolve_launch_model,
)
from teleclaude.core.agent_readiness import await_agent_readiness
from teleclaude.core.agent_status import AgentRunStart, transition_agent_status
from teleclaude.core.agents import AgentName, _get_agent_config, assert_agent_enabled, get_agent_command
from teleclaude.core.control_delivery import ControlDeliveryWakeDecision, handoff_control_payload
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    AgentReadyContext,
    ErrorEventContext,
    SessionLifecycleContext,
    TeleClaudeEvents,
)
from teleclaude.core.injected_text import (
    EnvelopeName,
    InjectedTextSourceFeature,
    semantic_envelope,
    visible_input_update,
)
from teleclaude.core.models import (
    AgentResumeArgs,
    AgentStartArgs,
    EndpointStamp,
    HumanActionIntent,
    Session,
    SessionEntryPoint,
    ThinkingMode,
)
from teleclaude.core.session_launch_profile import resolve_session_launch_profile
from teleclaude.core.session_lifecycle import LifecycleTransition, LifecycleTransitionReason, transition_session
from teleclaude.core.session_runtime_gate import (
    acquire_session_runtime_lease,
    mark_relaunch_awaiting_readiness,
    session_runtime_owner,
)
from teleclaude.core.session_startup_message import compose_command_loader, resolve_slash_command
from teleclaude.core.session_status import SessionLifecycleStatus
from teleclaude.daemon_session import AGENT_PROMPT_READY_TIMEOUT_S
from teleclaude.events.envelope import EventLevel, EventVisibility
from teleclaude.events.envelope_facts import home_for_session_config
from teleclaude.events.producer import publish_event
from teleclaude.events.references import SessionRef
from teleclaude.events.schemas.system import SessionRestartFailed, SessionRestartFailedData
from teleclaude.events.wire import LegacyFacts
from teleclaude.paths import session_tmp_dir
from teleclaude.types.commands import (
    HandoffAgentCommand,
    RestartAgentCommand,
    RestartAgentResult,
    ResumeAgentCommand,
    ReviveAgentCommand,
    RunAgentCommand,
    StartAgentCommand,
)

from ._handoff import execute_handoff
from ._keys import _bind_host_pane, _ensure_tmux_for_headless
from ._utils import with_session

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)
_THINKING_MODE_VALUES = {mode.value for mode in ThinkingMode}
_RESTART_QUIET_S, _RESTART_STOP_TIMEOUT_S, _RESTART_STOP_POLL_INTERVAL_S = 1.0, 30.0, 1.0
_PROMPT_ARGUMENT_SEPARATOR = " "
_AGENT_START_DEBUG_LOG = (
    "agent_start: session=%s agent_name=%r base_command=%s prompt_len=%s prompt_sha=%s config_agents=%s"
)
_AGENT_START_COMMAND_LOG = "Executing agent start command for %s: base_command=%s prompt_len=%s prompt_sha=%s"
_AGENT_RESTART_READINESS_OPPORTUNITY_EVENT = "agent_restart_readiness_opportunity"
_RESTART_PANE_MISSING_EVENT = "agent_restart_pane_missing"
_HANDOFF_CONTEXT_HEADER = "ADDITIONAL CONTEXT:"
_HANDOFF_CONTEXT_WITH_TRANSCRIPT_TEMPLATE = (
    "This session was handed off from {predecessor}. Session: {session_id}. "
    "The predecessor was {state} for {elapsed_seconds} seconds. "
    "Read the predecessor transcript tail first: {transcript}. "
    "Inspect the worktree for uncommitted work, then re-derive state through the role command."
)
_HANDOFF_CONTEXT_WITHOUT_TRANSCRIPT_TEMPLATE = (
    "This session was handed off from {predecessor}. Session: {session_id}. "
    "The predecessor was {state} for {elapsed_seconds} seconds. "
    "No predecessor native transcript exists. Inspect the worktree for uncommitted work, "
    "then re-derive state through the role command."
)
_HANDOFF_NO_TRANSCRIPT = "no predecessor agent was recorded"
_HANDOFF_LIVE_STATE, _HANDOFF_CLOSED_STATE = "live", "closed"
_HANDOFF_CONTEXT_SEPARATOR = "\n\n"
_HANDOFF_COMMAND_PREFIX = "/"
_HANDOFF_LAUNCHED_EVENT = "agent_runtime.handoff.launched"
_HANDOFF_EVENT_SOURCE, _HANDOFF_EVENT_DOMAIN = "agent_restart", "agent_runtime"
_HANDOFF_DELIVERY_FAILURE = "Handoff startup brief could not be delivered; session kept alive for inspection."


class _AgentRestartReadinessOpportunityOutcome(StrEnum):
    """Closed outcomes for a self-restart readiness opportunity."""

    ACCEPTED = "accepted"


class _AgentRestartReadinessOpportunityReason(StrEnum):
    """Closed reasons for a self-restart readiness opportunity."""

    SELF_RESTART_RELAUNCHED = "self_restart_relaunched"


class RestartFailurePhase(StrEnum):
    """Closed vocabulary of the restart-failure exits that emit `teleclaude.agent_runtime.session.restart_failed`."""

    STOP_TIMEOUT = "stop_timeout"
    AGENT_DISABLED = "agent_disabled"
    READINESS_TIMEOUT = "readiness_timeout"


async def _emit_restart_failed(session: Session, *, reason: str, phase: RestartFailurePhase) -> None:
    """Emit the typed restart-failure event so the delivery-edge debounce coalesces operator notifications."""
    await publish_event(
        SessionRestartFailed(
            subject=SessionRef(session.session_id),
            home=home_for_session_config(session.config_subject),
            data=SessionRestartFailedData(
                session_id=session.session_id,
                restart_group=session.session_id,
                reason=reason,
                phase=phase.value,
                computer=config.computer.name,
            ),
        ),
        LegacyFacts(
            producer="agent_restart",
            level=EventLevel.OPERATIONAL,
            domain="agent_runtime",
            visibility=EventVisibility.LOCAL,
            human_action=HumanActionIntent(
                topic="Agent restart failed",
                summary="The session was kept alive for inspection.",
                action="Inspect it and restart manually",
                origin_session_id=session.session_id,
            ),
        ),
    )


@dataclass(frozen=True)
class _RestartStopAttempt:
    pane_pid: int | None = None
    agent_pid: int | None = None
    child_count: int = 0
    kill_returncode: int | None = None


def _launch_patch_entries(agent_cfg: AgentConfig, mode: str, profile: str) -> dict[str, dict[str, str]]:
    """Build the per-launch patch entries from the mode's parameter table.

    Each mode chain entry's `patch` is a JSON map of loader-id -> config
    (replace-semantics per entry; the agent-default-model entry must carry
    provider + the API's full model id or dsh's boot validation rejects the
    patch). `model` is a display label and is never written into the patch.
    The restricted profile additionally merges the sandbox override, jailing
    the session to its workspace cwd. An unusable mapping returns {} so the
    caller launches with the profile default.
    """
    entries: dict[str, dict[str, str]] = {}
    for chain in (agent_cfg.model_chains.get(mode, []), agent_cfg.mode_chains.get(mode, [])):
        for entry in chain:
            if not entry.patch:
                continue
            try:
                parsed = json.loads(entry.patch)
            except ValueError:
                logger.warning("mode %s: launch patch parameters are not valid JSON: %s", mode, entry.patch[:80])
                continue
            if not isinstance(parsed, dict):
                continue
            for entry_id, entry_cfg in parsed.items():
                if not isinstance(entry_cfg, dict):
                    continue
                merged = entries.setdefault(entry_id, {})
                for key, value in entry_cfg.items():
                    merged[str(key)] = str(value)
    if profile == "restricted" and agent_cfg.restricted_sandbox_mode:
        entries.setdefault("sandbox-policy", {})["mode"] = agent_cfg.restricted_sandbox_mode
    adm = entries.get("agent-default-model")
    if adm is not None and (not adm.get("provider") or not adm.get("model")):
        logger.warning(
            "mode %s: agent-default-model patch lacks provider or model — dropping model entry, keeping sandbox",
            mode,
        )
        entries.pop("agent-default-model", None)
    return entries


def _render_launch_patch(entries: dict[str, dict[str, str]]) -> str:
    """Render the patch entries as a cordis patch YAML document."""
    lines: list[str] = []
    for entry_id, entry_cfg in entries.items():
        lines.append(f"- id: {entry_id}")
        lines.append("  config:")
        for key, value in entry_cfg.items():
            lines.append(f"    {key}: {value}")
    return "\n".join(lines) + "\n"


@with_session
async def start_agent(
    session: Session,
    cmd: StartAgentCommand,
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, str | None, bool], Awaitable[bool]],
) -> None:
    """Start a generic AI agent in session with optional arguments."""
    if session.lifecycle_status == "headless" or not session.tmux_session_name:
        adopted = await _ensure_tmux_for_headless(
            session,
            client,
            None,
            resume_native=False,
        )
        if not adopted:
            return
        session = adopted

    agent_name = cmd.agent_name
    args = list(cmd.args)
    try:
        agent_name = assert_agent_enabled(agent_name)
    except ValueError as exc:
        error = str(exc)
        logger.error(
            "Agent start rejected: %r (session=%s, available=%s, error=%s)",
            agent_name,
            session.session_id,
            [agent.value for agent in config.agents],
            error,
        )
        await client.send_message(session, error)
        return

    stored_mode_raw = session.thinking_mode if isinstance(session.thinking_mode, str) else None
    stored_mode = stored_mode_raw or ThinkingMode.SLOW.value

    user_args = list(args)
    thinking_mode = stored_mode
    if user_args and user_args[0] in _THINKING_MODE_VALUES:
        thinking_mode = user_args.pop(0)

    if thinking_mode == ThinkingMode.DEEP.value and agent_name != AgentName.CODEX.value:
        await client.send_message(
            session,
            "deep is only supported for codex. Use fast/med/slow for other agents.",
        )
        return

    start_args = AgentStartArgs(
        agent_name=agent_name,
        thinking_mode=ThinkingMode(thinking_mode),
        user_args=user_args,
    )
    initial_prompt = _PROMPT_ARGUMENT_SEPARATOR.join(start_args.user_args) if start_args.user_args else None
    prompt_len = len(initial_prompt) if initial_prompt is not None else None
    prompt_sha = hashlib.sha256(initial_prompt.encode()).hexdigest()[:12] if initial_prompt is not None else None

    await db.update_session(session.session_id, thinking_mode=start_args.thinking_mode.value)

    has_prompt = bool(start_args.user_args)
    resolved_model_flags = cmd.resolved_model_flags
    if resolved_model_flags is None:
        resolved_model_flags = (
            await resolve_launch_model(
                start_args.agent_name,
                start_args.thinking_mode.value,
                ownership=launch_ownership(session.job),
                session_id=session.session_id,
            )
        ).flags
    launch_profile = resolve_session_launch_profile(session, start_args.agent_name)
    base_cmd = get_agent_command(
        start_args.agent_name,
        thinking_mode=start_args.thinking_mode.value,
        interactive=has_prompt,
        profile=launch_profile.profile,
        launch_flags=launch_profile.flags,
        resolved_flags=resolved_model_flags,
    )

    cmd_parts = [base_cmd]

    # dsh has no model CLI flag: for agents that declare model_via_launch_patch,
    # the mode chain's flags are a parameter table (JSON map of loader-id ->
    # config) rendered into a per-launch `--patch` overlay. The patch is
    # written to THIS session's tmpdir (unique per tmux session), applied at
    # launch, and discarded with the session — no static patch files exist.
    agent_cfg = _get_agent_config(start_args.agent_name)
    if agent_cfg.model_via_launch_patch:
        entries = _launch_patch_entries(agent_cfg, start_args.thinking_mode.value, launch_profile.profile)
        if entries:
            patch_dir = session_tmp_dir(session.session_id)
            patch_dir.mkdir(parents=True, exist_ok=True)
            patch_path = patch_dir / "launch.patch.yml"
            patch_path.write_text(_render_launch_patch(entries))
            cmd_parts.append("--patch")
            cmd_parts.append(shlex.quote(str(patch_path)))
        else:
            logger.warning(
                "model_via_launch_patch: mode %s carries no usable launch parameters "
                "— launching with the profile default (session=%s)",
                start_args.thinking_mode.value,
                session.session_id,
            )

    if start_args.user_args:
        quoted_args = [shlex.quote(arg) for arg in start_args.user_args]
        cmd_parts.extend(quoted_args)

    command_str = _PROMPT_ARGUMENT_SEPARATOR.join(cmd_parts)
    logger.debug(
        _AGENT_START_DEBUG_LOG,
        session.session_id,
        agent_name,
        base_cmd,
        prompt_len,
        prompt_sha,
        [agent.value for agent in config.agents],
    )
    logger.info(_AGENT_START_COMMAND_LOG, agent_name, base_cmd, prompt_len, prompt_sha)

    truncated_prompt = initial_prompt[:200] if initial_prompt is not None else None

    updates: dict[str, object] = {  # guard: loose-dict - optional session field set
        "active_agent": agent_name,
        "thinking_mode": start_args.thinking_mode.value,
    }
    # A start that carries no prompt of its own leaves the acceptance marker
    # alone. Clearing it discards the proof that an origin accepted the pending
    # turn, so the prompt hook cannot attribute that turn and relabels it
    # terminal — which reflects the input straight back into the thread already
    # showing it.
    if truncated_prompt is not None:
        updates["last_message_sent"] = truncated_prompt
        # Resolved from the prompt as written, never from its truncated
        # fingerprint: a cut entry cannot be recognized as an envelope and
        # would carry its framing into the row.
        updates.update(visible_input_update(initial_prompt or "", visible_source_text=cmd.visible_input_source_text))
        updates["last_message_sent_at"] = datetime.now(UTC).isoformat()
    if cmd.origin:
        updates["last_input_origin"] = cmd.origin
    await db.update_session(session.session_id, **updates)

    run_started_at = datetime.now(UTC)
    await transition_agent_status(
        db,
        session.session_id,
        AgentRunStart(startup_work_expected=initial_prompt is not None),
        at=run_started_at,
    )
    await execute_terminal_command(session.session_id, command_str, None, True)
    emit_agent_launch_started(session_id=session.session_id, agent=agent_name)


@with_session
async def resume_agent(
    session: Session,
    cmd: ResumeAgentCommand,
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, str | None, bool], Awaitable[bool]],
) -> None:
    """Resume a generic AI agent session."""
    if session.lifecycle_status == "headless" or not session.tmux_session_name:
        adopted = await _ensure_tmux_for_headless(
            session,
            client,
            None,
            resume_native=False,
        )
        if not adopted:
            return
        session = adopted

    agent_name = cmd.agent_name or ""
    args = [cmd.native_session_id] if cmd.native_session_id else []

    if not agent_name:
        active = session.active_agent
        if not active:
            await client.send_message(session, "No active agent to resume")
            return
        agent_name = active

    try:
        agent_name = assert_agent_enabled(agent_name)
    except ValueError as exc:
        await client.send_message(session, str(exc))
        return

    thinking_raw = session.thinking_mode
    native_session_id_override = args[0].strip() if args else ""
    native_session_id = native_session_id_override or session.native_session_id
    if native_session_id_override:
        await db.update_session(session.session_id, native_session_id=native_session_id_override)

    resume_args = AgentResumeArgs(
        agent_name=agent_name,
        native_session_id=native_session_id,
        thinking_mode=ThinkingMode(thinking_raw) if thinking_raw else None,
    )

    launch = (
        await resolve_launch_model(
            resume_args.agent_name,
            resume_args.thinking_mode.value,
            ownership=launch_ownership(session.job),
            session_id=session.session_id,
        )
        if resume_args.thinking_mode
        else None
    )
    launch_profile = resolve_session_launch_profile(session, resume_args.agent_name)
    command_str = get_agent_command(
        agent=resume_args.agent_name,
        thinking_mode=resume_args.thinking_mode.value if resume_args.thinking_mode else None,
        exec=False,
        resume=not resume_args.native_session_id,
        native_session_id=resume_args.native_session_id,
        profile=launch_profile.profile,
        launch_flags=launch_profile.flags,
        resolved_flags=launch.flags if launch else None,
    )

    if resume_args.native_session_id:
        logger.info("Resuming %s session %s (from database)", agent_name, resume_args.native_session_id)
    else:
        logger.info("Continuing latest %s session (no native session ID in database)", agent_name)

    if cmd.origin:
        await db.update_session(session.session_id, active_agent=agent_name, last_input_origin=cmd.origin)
    else:
        await db.update_session(session.session_id, active_agent=agent_name)

    run_started_at = datetime.now(UTC)
    await transition_agent_status(db, session.session_id, AgentRunStart(), at=run_started_at)
    await execute_terminal_command(session.session_id, command_str, None, True)


async def _terminate_agent_process(tmux_session_name: str) -> _RestartStopAttempt:
    """Send SIGTERM directly to the agent process via its PID.

    tmux send-keys C-c goes through the terminal layer and gets swallowed
    when the agent is mid-tool-execution. Direct kill bypasses that.
    """
    pane_pid = await tmux_bridge.get_pane_pid(tmux_session_name)
    if not pane_pid:
        return _RestartStopAttempt()
    # Python stdlib has no portable child-process enumeration; pgrep locates the tmux pane child.
    child_procs = await asyncio.create_subprocess_exec(
        "pgrep",
        "-P",
        str(pane_pid),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await child_procs.communicate()
    if not stdout:
        return _RestartStopAttempt(pane_pid=pane_pid)
    child_pids = tuple(int(line.strip()) for line in stdout.decode().splitlines() if line.strip().isdigit())
    if not child_pids:
        return _RestartStopAttempt(pane_pid=pane_pid)
    agent_pid = child_pids[0]
    kill_returncode = 0
    try:
        os.kill(agent_pid, signal.SIGTERM)
    except OSError as exc:
        kill_returncode = exc.errno or 1
    attempt = _RestartStopAttempt(
        pane_pid=pane_pid,
        agent_pid=agent_pid,
        child_count=len(child_pids),
        kill_returncode=kill_returncode,
    )
    logger.debug(
        "agent_restart_sigterm_sent",
        tmux_session=tmux_session_name,
        pane_pid=attempt.pane_pid,
        agent_pid=attempt.agent_pid,
        child_count=attempt.child_count,
        kill_returncode=attempt.kill_returncode,
    )
    return attempt


async def _log_restart_shell_ready_timeout(
    session: Session,
    *,
    target_agent: str,
    stop_attempt: _RestartStopAttempt,
    elapsed_ms: int,
) -> None:
    tmux_session = session.tmux_session_name or ""
    current_command = await tmux_bridge.get_current_command(tmux_session)
    tmux_exists = await tmux_bridge.session_exists(tmux_session, log_missing=False)
    pane_dead = await tmux_bridge.is_pane_dead(tmux_session) if tmux_exists else None
    agent_pid_alive = tmux_bridge.pid_is_alive(stop_attempt.agent_pid) if stop_attempt.agent_pid else None
    logger.warning(
        "agent_restart_shell_ready_timeout",
        session_id=session.session_id,
        tmux_session=tmux_session,
        target_agent=target_agent,
        pane_pid=stop_attempt.pane_pid,
        agent_pid=stop_attempt.agent_pid,
        child_count=stop_attempt.child_count,
        kill_returncode=stop_attempt.kill_returncode,
        agent_pid_alive=agent_pid_alive,
        current_command=current_command,
        tmux_exists=tmux_exists,
        pane_dead=pane_dead,
        elapsed_ms=elapsed_ms,
    )


async def _wait_for_restart_barrier(
    session: Session,
    *,
    stop_attempt: _RestartStopAttempt,
    stop_deadline: float,
) -> bool:
    """Wait for both the host shell and the terminated agent process under one deadline."""
    while True:
        remaining_stop_s = stop_deadline - time.monotonic()
        if remaining_stop_s <= 0:
            return False
        shell_ready = await tmux_io.wait_for_shell_ready(
            session,
            timeout_s=remaining_stop_s,
            poll_interval_s=_RESTART_STOP_POLL_INTERVAL_S,
        )
        if not shell_ready:
            return False
        agent_exited = not stop_attempt.agent_pid or not tmux_bridge.pid_is_alive(stop_attempt.agent_pid)
        if agent_exited:
            return True
        await asyncio.sleep(min(_RESTART_STOP_POLL_INTERVAL_S, remaining_stop_s))


def _handoff_startup_message(session: Session, *, predecessor: str, was_closed: bool, elapsed_seconds: int) -> str:
    """Compose the successor's ordinary loader plus the one handoff context section."""
    state = _HANDOFF_CLOSED_STATE if was_closed else _HANDOFF_LIVE_STATE
    context_template = (
        _HANDOFF_CONTEXT_WITH_TRANSCRIPT_TEMPLATE
        if session.native_log_file
        else _HANDOFF_CONTEXT_WITHOUT_TRANSCRIPT_TEMPLATE
    )
    context = context_template.format(
        predecessor=predecessor,
        session_id=session.session_id,
        state=state,
        elapsed_seconds=elapsed_seconds,
        transcript=session.native_log_file,
    )
    context_block = _HANDOFF_CONTEXT_SEPARATOR.join((_HANDOFF_CONTEXT_HEADER, context))
    if session.command is None:
        return context_block
    loader = compose_command_loader(session.command, session.working_slug or "")
    return _HANDOFF_CONTEXT_SEPARATOR.join((loader, context_block))


async def select_handoff_successor(
    session: Session,
    *,
    agent_name: str | None,
    caller_system_role: str | None,
    request_id: str | None,
) -> HandoffAgentCommand:
    """Resolve a handoff successor synchronously, before any operation is submitted.

    Pure selection — no session mutation and no runtime lease — so the caller
    (the API route) can report ``selected_agent`` on the receipt it returns,
    and the RECEIPT operation's work body only has to execute the handoff
    this function already decided. Raises ``AgentDispatchFailure`` when no
    successor can be resolved.
    """
    command = f"{_HANDOFF_COMMAND_PREFIX}{session.command}" if session.command else None
    role_info = None
    if session.command:
        resolved_command = resolve_slash_command(session.command)
        role_info = COMMAND_ROLE_MAP.get(resolved_command) if resolved_command else None
    role = role_info[0] if role_info else None
    dispatch_mode, preferred_agent = classify_fresh_agent_preference(
        agent_name,
        caller_system_role=caller_system_role,
    )
    try:
        decision = await resolve_agent_dispatch(
            mode=dispatch_mode,
            role=role,
            command=command,
            preferred_agent=preferred_agent,
            fixed_agent=None,
            candidate_order=None,
            entry_point=SessionEntryPoint.AGENT_HANDOFF,
            session_kind=desk_session_kind(
                session.system_role, session.human_role, EndpointStamp.from_session(session)
            ),
        )
    except AgentDispatchFailure as exc:
        emit_agent_dispatch_decision(
            stage=AgentDispatchStage.RESOLVED,
            outcome=AgentDispatchOutcome.REFUSED,
            reason=exc.reason,
            request_id=request_id,
            session_id=session.session_id,
            dispatch_mode=dispatch_mode,
            entry_point=SessionEntryPoint.AGENT_HANDOFF,
            preferred_agent=preferred_agent,
        )
        raise

    emit_agent_dispatch_decision(
        stage=AgentDispatchStage.RESOLVED,
        outcome=AgentDispatchOutcome.SELECTED,
        reason=decision.reason,
        selected_agent=decision.agent,
        request_id=request_id,
        session_id=session.session_id,
        dispatch_mode=dispatch_mode,
        entry_point=SessionEntryPoint.AGENT_HANDOFF,
        preferred_agent=preferred_agent,
        fallback_reason=decision.fallback_reason,
        candidate_order=decision.candidate_order,
        order_branch=decision.order_branch,
    )
    return HandoffAgentCommand(
        session_id=session.session_id,
        agent_name=decision.agent,
        caller_system_role=caller_system_role,
        request_id=request_id,
    )


@with_session
async def handoff_agent(
    session: Session,
    cmd: HandoffAgentCommand,
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, str | None, bool], Awaitable[bool]],
) -> None:
    """Execute a handoff to the successor ``select_handoff_successor`` already resolved."""
    lease = await acquire_session_runtime_lease(session.session_id)
    predecessor = session.active_agent or _HANDOFF_NO_TRANSCRIPT
    reference_time = session.closed_at if session.closed_at is not None else session.last_activity
    elapsed_seconds = int((datetime.now(UTC) - reference_time).total_seconds()) if reference_time else 0
    startup_message = _handoff_startup_message(
        session,
        predecessor=predecessor,
        was_closed=session.closed_at is not None,
        elapsed_seconds=max(elapsed_seconds, 0),
    )
    await execute_handoff(session, cmd, client, execute_terminal_command, startup_message, lease)


async def _restart_agent(
    session: Session,
    cmd: RestartAgentCommand | ReviveAgentCommand,
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, str | None, bool], Awaitable[bool]],
) -> tuple[bool, str | None] | RestartAgentResult:
    """Restart an AI agent in the session by resuming the native session."""
    active_agent = session.active_agent
    native_session_id = session.native_session_id

    target_agent = active_agent
    if not target_agent:
        error = "Cannot restart agent: no active agent for this session."
        logger.error("agent_restart blocked (session=%s): %s", session.session_id, error)
        event_bus.emit(
            TeleClaudeEvents.ERROR,
            ErrorEventContext(session_id=session.session_id, message=error, source="agent_restart"),
            visibility=EventVisibility.CLUSTER,
        )
        await client.send_message(session, f"❌ {error}")
        return False, error

    if not native_session_id:
        error = "Cannot restart agent: no native session ID stored. Start the agent first."
        logger.error("agent_restart blocked (session=%s): %s", session.session_id, error)
        event_bus.emit(
            TeleClaudeEvents.ERROR,
            ErrorEventContext(session_id=session.session_id, message=error, source="agent_restart"),
            visibility=EventVisibility.CLUSTER,
        )
        await client.send_message(session, f"❌ {error}")
        return False, error

    session_updates: dict[str, str | None] = {}
    if session.closed_at is not None:
        session_updates["closed_at"] = None
        logger.info("Reviving closed session before agent restart (session=%s)", session.session_id)

    if session.tmux_session_name:
        tmux_exists = await tmux_bridge.session_exists(session.tmux_session_name, log_missing=False)
        if not tmux_exists:
            session_updates["tmux_session_name"] = None
            logger.info(
                _RESTART_PANE_MISSING_EVENT,
                session_id=session.session_id,
                tmux_session=session.tmux_session_name,
            )

    if session_updates:
        await db.update_session(session.session_id, **session_updates)
        refreshed = await db.get_session(session.session_id)
        if refreshed:
            session = refreshed

    if session.lifecycle_status == "headless" or not session.tmux_session_name:
        bound = await _bind_host_pane(session, client)
        if bound is None:
            return False, "Failed to adopt headless session."
        session, _ = bound

    if session.lifecycle_status in {SessionLifecycleStatus.CLOSED, SessionLifecycleStatus.HEADLESS}:
        await transition_session(
            db,
            session.session_id,
            LifecycleTransition(SessionLifecycleStatus.ACTIVE, LifecycleTransitionReason.RELAUNCH_REOPENED),
        )
        refreshed = await db.get_session(session.session_id)
        if refreshed:
            session = refreshed

    try:
        target_agent = assert_agent_enabled(target_agent)
    except ValueError as exc:
        error = str(exc)
        logger.error("agent_restart blocked (session=%s): %s", session.session_id, error)
        event_bus.emit(
            TeleClaudeEvents.ERROR,
            ErrorEventContext(session_id=session.session_id, message=error, source="agent_restart"),
            visibility=EventVisibility.CLUSTER,
        )
        await client.send_message(session, f"❌ {error}")
        await _emit_restart_failed(session, reason=error, phase=RestartFailurePhase.AGENT_DISABLED)
        return False, error

    logger.info(
        "Restarting agent %s in session %s (tmux: %s)",
        target_agent,
        session.session_id,
        session.tmux_session_name,
    )

    stop_started = time.monotonic()
    stop_attempt = await _terminate_agent_process(session.tmux_session_name)
    stop_deadline = stop_started + _RESTART_STOP_TIMEOUT_S
    ready = await _wait_for_restart_barrier(
        session,
        stop_attempt=stop_attempt,
        stop_deadline=stop_deadline,
    )
    stop_elapsed_ms = int((time.monotonic() - stop_started) * 1000)
    if not ready:
        error = "Agent did not exit after termination. Restart aborted."
        await _log_restart_shell_ready_timeout(
            session,
            target_agent=target_agent,
            stop_attempt=stop_attempt,
            elapsed_ms=stop_elapsed_ms,
        )
        event_bus.emit(
            TeleClaudeEvents.ERROR,
            ErrorEventContext(session_id=session.session_id, message=error, source="agent_restart"),
            visibility=EventVisibility.CLUSTER,
        )
        await client.send_message(session, f"❌ {error}")
        await _emit_restart_failed(session, reason=error, phase=RestartFailurePhase.STOP_TIMEOUT)
        return False, error
    logger.debug(
        "agent_restart_shell_ready",
        session_id=session.session_id,
        tmux_session=session.tmux_session_name,
        target_agent=target_agent,
        pane_pid=stop_attempt.pane_pid,
        agent_pid=stop_attempt.agent_pid,
        child_count=stop_attempt.child_count,
        kill_returncode=stop_attempt.kill_returncode,
        elapsed_ms=stop_elapsed_ms,
    )

    restart_mode = session.thinking_mode if session.thinking_mode else "slow"
    launch = await resolve_launch_model(
        target_agent,
        restart_mode,
        ownership=launch_ownership(session.job),
        session_id=session.session_id,
    )
    launch_profile = resolve_session_launch_profile(session, target_agent)
    restart_cmd = get_agent_command(
        agent=target_agent,
        thinking_mode=restart_mode,
        exec=False,
        native_session_id=native_session_id,
        profile=launch_profile.profile,
        launch_flags=launch_profile.flags,
        resolved_flags=launch.flags,
    )

    if cmd.self_restart:
        # Subscribe BEFORE the restart paste — the agent's SessionStart hook
        # can race execute_terminal_command and emit AGENT_READY before the
        # wait task runs. event_bus has no replay; subscribing after the
        # launch loses the event.
        loop = asyncio.get_running_loop()
        ready_future: asyncio.Future[None] = loop.create_future()

        async def _on_ready(_event_type: str, ctx: AgentReadyContext) -> None:
            if (
                ctx.session_id == session.session_id
                and ctx.compaction_launch_context is None
                and not ready_future.done()
            ):
                ready_future.set_result(None)

        ready_handler = event_bus.subscribe(TeleClaudeEvents.AGENT_READY, _on_ready)

        mark_relaunch_awaiting_readiness(session.session_id)
        await execute_terminal_command(session.session_id, restart_cmd, None, True)
        logger.info(
            _AGENT_RESTART_READINESS_OPPORTUNITY_EVENT,
            session_id=session.session_id,
            agent_name=target_agent,
            outcome=_AgentRestartReadinessOpportunityOutcome.ACCEPTED.value,
            reason=_AgentRestartReadinessOpportunityReason.SELF_RESTART_RELAUNCHED.value,
        )

        async def _inject_after_restart() -> None:
            try:
                try:
                    # Shared start/restart readiness follows the provider-declared
                    # native signal or complete-pane authority.
                    gate_winner = await await_agent_readiness(
                        agent_name=target_agent,
                        session=session,
                        session_id=session.session_id,
                        ready_future=ready_future,
                        quiet_s=_RESTART_QUIET_S,
                        timeout_s=AGENT_PROMPT_READY_TIMEOUT_S,
                    )
                except TimeoutError:
                    logger.warning(
                        "agent_restart readiness timeout: session=%s timeout_s=%.1f — continuation stimulus not sent",
                        session.session_id,
                        AGENT_PROMPT_READY_TIMEOUT_S,
                    )
                    event_bus.emit(
                        TeleClaudeEvents.AGENT_READINESS_TIMEOUT,
                        SessionLifecycleContext(session_id=session.session_id),
                        visibility=EventVisibility.LOCAL,
                    )
                    await client.send_message(
                        session,
                        "Agent readiness timed out after restart. Session kept alive for inspection; continuation stimulus not sent.",
                    )
                    await _emit_restart_failed(
                        session,
                        reason="Agent readiness timed out after restart.",
                        phase=RestartFailurePhase.READINESS_TIMEOUT,
                    )
                    return
            finally:
                event_bus.unsubscribe(TeleClaudeEvents.AGENT_READY, ready_handler)

            # Start-path parity: confirm the process is live before injecting.
            if not await tmux_io.is_process_running(session):
                logger.error(
                    "agent_restart: process not running after readiness session=%s — continuation stimulus not sent",
                    session.session_id,
                )
                await client.send_message(
                    session,
                    "Agent process exited after restart before the continuation stimulus could be sent; session kept alive for inspection.",
                )
                return

            # The shared control-delivery handoff persists the semantic payload and
            # queues only the content-free wake; the adapter drains the payload at
            # its declared hook boundary.
            logger.info(
                "agent_restart: queueing continuation stimulus session=%s gate=%s",
                session.session_id,
                gate_winner.value,
            )
            occurrence_key = f"restart-continuation:{session.session_id}:{cmd.request_id or time.time_ns()}"
            await handoff_control_payload(
                session_id=session.session_id,
                body=RESTART_CONTINUATION_STIMULUS,
                source_key=occurrence_key,
                envelope=semantic_envelope(EnvelopeName.RESTART_CONTINUATION),
                wake_decision=ControlDeliveryWakeDecision.OBSERVED_IDLE,
                wake_source_feature=InjectedTextSourceFeature.AGENT_RESTART,
            )
            logger.info("agent_restart: continuation stimulus accepted session=%s", session.session_id)

        asyncio.create_task(_inject_after_restart(), name="send-restart-stimulus")
    else:
        mark_relaunch_awaiting_readiness(session.session_id)
        await execute_terminal_command(session.session_id, restart_cmd, None, True)

    return True, None


@with_session
async def agent_restart(
    session: Session,
    cmd: RestartAgentCommand | ReviveAgentCommand,
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, str | None, bool], Awaitable[bool]],
) -> tuple[bool, str | None] | RestartAgentResult:
    """Serialize ordinary restart with every other session runtime mutation."""
    async with session_runtime_owner(session.session_id):
        return await _restart_agent(session, cmd, client, execute_terminal_command)


@with_session
async def run_agent_command(
    session: Session,
    cmd: RunAgentCommand,
    client: "AdapterClient",
    execute_terminal_command: Callable[[str, str, str | None, bool], Awaitable[bool]],
) -> None:
    """Send a slash command directly to the running agent."""
    if not cmd.command:
        logger.warning("run_agent_command called without a command")
        return
    if session.active_agent:
        try:
            assert_agent_enabled(session.active_agent)
        except ValueError as exc:
            await client.send_message(session, str(exc))
            return
    if session.lifecycle_status == "headless" or not session.tmux_session_name:
        adopted = await _ensure_tmux_for_headless(
            session,
            client,
            None,
            resume_native=True,
        )
        if not adopted:
            return
        session = adopted

    command_text = f"/{cmd.command}".strip()
    if cmd.args:
        command_text = f"{command_text} {cmd.args}".strip()

    await db.update_session(
        session.session_id,
        last_message_sent=command_text[:200],
        **visible_input_update(command_text),
        last_message_sent_at=datetime.now(UTC).isoformat(),
        last_input_origin=cmd.origin,
    )

    await execute_terminal_command(session.session_id, command_text, None, True)
