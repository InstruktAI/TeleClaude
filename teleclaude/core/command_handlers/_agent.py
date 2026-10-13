"""Agent start, resume, handoff-selection, and run-command handlers."""

import hashlib
import json
import shlex
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.config._models import AgentConfig
from teleclaude.config.machine import config
from teleclaude.context_selector import resolve_snippet_meta
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
from teleclaude.core.agent_status import AgentRunStart, transition_agent_status
from teleclaude.core.agents import AgentName, _get_agent_config, assert_agent_enabled, get_agent_command
from teleclaude.core.db import db
from teleclaude.core.injected_text import visible_input_update
from teleclaude.core.models import (
    AgentResumeArgs,
    AgentStartArgs,
    EndpointStamp,
    Session,
    SessionEntryPoint,
    ThinkingMode,
)
from teleclaude.core.session_continuation import ContinuationLoader, rebuild_continuation_loader
from teleclaude.core.session_launch_profile import resolve_session_launch_profile
from teleclaude.core.session_runtime_gate import acquire_session_runtime_lease
from teleclaude.paths import REPO_ROOT, session_tmp_dir
from teleclaude.types.commands import HandoffAgentCommand, ResumeAgentCommand, RunAgentCommand, StartAgentCommand

from ._handoff import execute_handoff
from ._keys import _ensure_tmux_for_headless
from ._utils import with_session

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)
_THINKING_MODE_VALUES = {mode.value for mode in ThinkingMode}
_PROMPT_ARGUMENT_SEPARATOR = " "
_AGENT_START_DEBUG_LOG = (
    "agent_start: session=%s agent_name=%r base_command=%s prompt_len=%s prompt_sha=%s config_agents=%s"
)
_AGENT_START_COMMAND_LOG = "Executing agent start command for %s: base_command=%s prompt_len=%s prompt_sha=%s"
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
                ownership=launch_ownership(session.role),
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
            ownership=launch_ownership(session.role),
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


def _handoff_startup_message(
    session: Session,
    *,
    continuation: ContinuationLoader | None,
    predecessor: str,
    was_closed: bool,
    elapsed_seconds: int,
) -> str:
    """Compose the loader rebuilt from the session's resolved invocation plus the one handoff context section."""
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
    if continuation is None:
        return context_block
    return _HANDOFF_CONTEXT_SEPARATOR.join((continuation.loader, context_block))


def _recorded_procedure_candidate_order(session: Session) -> tuple[str, ...] | None:
    """The agent preference the session's recorded procedure declares; ``None`` when it records no usable one."""
    if not session.command:
        return None
    project_root = Path(session.project_path) if session.project_path else REPO_ROOT
    snippet = resolve_snippet_meta(session.command, project_root=project_root)
    declarations = snippet.entry.declarations if snippet is not None else None
    if declarations is None or declarations.dispatch is None:
        return None
    return tuple(agent.value for agent in declarations.dispatch.agents)


async def select_handoff_successor(
    session: Session,
    *,
    agent_name: str | None,
    caller_role: str | None,
    request_id: str | None,
) -> HandoffAgentCommand:
    """Resolve a handoff successor synchronously, before any operation is submitted.

    Pure selection — no session mutation and no runtime lease — so the caller
    (the API route) can report ``selected_agent`` on the receipt it returns,
    and the RECEIPT operation's work body only has to execute the handoff
    this function already decided. Raises ``AgentDispatchFailure`` when no
    successor can be resolved.
    """
    candidate_order = _recorded_procedure_candidate_order(session)
    dispatch_mode, preferred_agent = classify_fresh_agent_preference(
        agent_name,
        caller_role=caller_role,
    )
    try:
        decision = await resolve_agent_dispatch(
            mode=dispatch_mode,
            role=session.role,
            preferred_agent=preferred_agent,
            fixed_agent=None,
            candidate_order=candidate_order,
            entry_point=SessionEntryPoint.AGENT_HANDOFF,
            session_kind=desk_session_kind(session.role, session.human_role, EndpointStamp.from_session(session)),
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
        caller_role=caller_role,
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
    continuation = await rebuild_continuation_loader(session)
    lease = await acquire_session_runtime_lease(session.session_id)
    predecessor = session.active_agent or _HANDOFF_NO_TRANSCRIPT
    reference_time = session.closed_at if session.closed_at is not None else session.last_activity
    elapsed_seconds = int((datetime.now(UTC) - reference_time).total_seconds()) if reference_time else 0
    startup_message = _handoff_startup_message(
        session,
        continuation=continuation,
        predecessor=predecessor,
        was_closed=session.closed_at is not None,
        elapsed_seconds=max(elapsed_seconds, 0),
    )
    await execute_handoff(session, cmd, client, execute_terminal_command, startup_message, lease)


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
