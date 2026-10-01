"""Deterministic, target-local agent selection for fresh sessions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from sqlalchemy.exc import SQLAlchemyError

from teleclaude.agent_registry import AGENT_REGISTRY, DeskConfinement, agent_permutation, registry_digest
from teleclaude.caller_identity import is_desk_role
from teleclaude.config import config
from teleclaude.constants import SlashCommand
from teleclaude.core.agent_availability import (
    AgentAvailabilityStatus,
    AvailabilityState,
    LaunchOwnership,
    is_launchable,
)
from teleclaude.core.agents import AgentName
from teleclaude.core.db import db
from teleclaude.core.models._adapter import EndpointStamp
from teleclaude.core.models._session import AgentDispatchMode
from teleclaude.core.session_startup_message import resolve_slash_command

if TYPE_CHECKING:
    from teleclaude.core.models import SessionEntryPoint

logger = get_logger(__name__)


class AgentDispatchReason(StrEnum):
    """Closed, privacy-safe reasons emitted by the dispatch boundary."""

    RECEIVED = "received"
    ROLE_PREFERENCE = "role_preference"
    GLOBAL_UNMAPPED_ROLE = "global_unmapped_role"
    KNOWN_ROLE_POLICY_DEFECT = "known_role_policy_defect"
    FIXED_AGENT_REQUIRED = "fixed_agent_required"
    FIXED_AGENT_UNAVAILABLE = "fixed_agent_unavailable"
    FIXED_AGENT = "fixed_agent"
    PREFERRED_AGENT_REQUIRED = "preferred_agent_required"
    MANUAL_PREFERENCE = "manual_preference"
    MANUAL_PREFERENCE_DEGRADED = "manual_preference_degraded"
    MANUAL_PREFERENCE_UNAVAILABLE = "manual_preference_unavailable"
    DETERMINISTIC_INELIGIBILITY = "deterministic_ineligibility"
    UNKNOWN_AGENT = "unknown_agent"
    DISABLED_AGENT = "disabled_agent"
    AVAILABILITY_READ_FAILED = "availability_read_failed"
    NO_ELIGIBLE_CANDIDATE = "no_eligible_candidate"
    TARGET_CAPABILITY_PRESENT = "target_capability_present"
    TARGET_CAPABILITY_MISSING = "target_capability_missing"
    FIXED_INTENT = "fixed_intent"
    RUN_REQUEST_ACCEPTED = "run_request_accepted"
    RUN_REQUEST_REJECTED = "run_request_rejected"
    SLUG_REQUIRED = "slug_required"
    WORKTREE_MISMATCH = "worktree_mismatch"
    DISPATCH_PRIVILEGE_FORBIDDEN = "dispatch_privilege_forbidden"
    REVIEWER_CONFLICT = "reviewer_conflict"
    COMMAND_INVALID = "command_invalid"
    PROJECT_REQUIRED = "project_required"
    DISPATCH_PRIVILEGE_ALLOWED = "dispatch_privilege_allowed"
    HELD_WITHOUT_DRIVER = "held_without_driver"
    WORKING_SLUG_INFERRED = "working_slug_inferred"
    WORKING_SLUG_PRESENT = "working_slug_present"
    JOB_COMMAND_GENERIC_CREATE = "job_command_generic_create"
    STARTUP_PREPARED = "startup_prepared"
    SESSION_COMMITTED = "session_committed"
    LAUNCH_QUEUED = "launch_queued"
    LAUNCH_COMPLETED = "launch_completed"
    LAUNCH_FAILED = "launch_failed"
    RESPONSE_PRESENTED = "response_presented"
    CODEX_LOADER = "codex_loader"
    STARTUP_UNCHANGED_FOR_AGENT = "startup_unchanged_for_agent"
    THINKING_MODE_REQUIRED = "thinking_mode_required"
    MODEL_CHAIN_EXHAUSTED = "model_chain_exhausted"
    MODEL_AVAILABILITY_READ_FAILED = "model_availability_read_failed"
    JOB_DECLARATION = "job_declaration"
    SESSION_KIND_POLICY = "session_kind_policy"
    DESK_CONFINEMENT_UNVERIFIED = "desk_confinement_unverified"


class AgentDispatchStage(StrEnum):
    """Closed observation-map stages for agent dispatch decisions."""

    ACCEPTED = "accepted"
    TRANSPORT = "transport"
    RESOLVED = "resolved"
    RUN_OUTCOME = "run_outcome"
    STARTUP_PREPARED = "startup_prepared"
    RESPONSE_PRESENTED = "response_presented"
    SESSION_COMMITTED = "session_committed"


class AgentDispatchOutcome(StrEnum):
    """Closed outcomes for an observation-map stage."""

    SELECTED = "selected"
    FALLBACK = "fallback"
    REFUSED = "refused"
    PREPARED = "prepared"
    COMMITTED = "committed"
    STARTED = "started"
    FAILED = "failed"
    FORWARDED = "forwarded"
    LEGACY_FIXED = "legacy_fixed"
    REJECTED = "rejected"
    CONFLICT = "conflict"


class AgentDispatchPolicy(StrEnum):
    """Observation policy carried by every dispatch decision record."""

    EACH_OPPORTUNITY = "each_opportunity"


class AgentDispatchKindSource(StrEnum):
    """Provenance of a routing todo kind."""

    TARGET_TODO_RECORD = "target_todo_record"
    NOT_APPLICABLE = "not_applicable"


class AgentDispatchFailure(ValueError):
    """A stable refusal from the dispatch boundary."""

    def __init__(self, reason: AgentDispatchReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class ModelChainExhausted(AgentDispatchFailure):
    """Raised before session creation when no model in a declared chain is usable."""


class ModelAvailabilityStateFailure(AgentDispatchFailure):
    """Raised when model-scoped availability cannot be read safely."""


class RunSessionThinkingMode(StrEnum):
    """Public thinking modes resolved for a fresh run-session request."""

    FAST = "fast"
    MED = "med"
    SLOW = "slow"


class AgentDispatchOrderBranch(StrEnum):
    """Closed token naming which policy resolved an automatic dispatch's candidate order."""

    COMMAND_POLICY = "command_policy"
    GLOBAL = "global"
    JOB_DECLARATION = "job_declaration"
    SESSION_KIND = "session_kind"


class DispatchSessionKind(StrEnum):
    """Session kinds whose agent order the matrix decides before any command."""

    HELP_DESK = "help_desk"


@dataclass(frozen=True)
class AgentDispatchDecision:
    """Selected agent plus a stable, non-user-facing decision reason.

    ``candidate_order`` and ``order_branch`` are populated only for the
    automatic-dispatch path (empty/``None`` for FIXED and MANUAL_PREFERENCE,
    which select by identity rather than by order).
    """

    agent: str
    reason: AgentDispatchReason
    fallback_reason: AgentDispatchReason | None = None
    candidate_order: tuple[str, ...] = ()
    order_branch: AgentDispatchOrderBranch | None = None


@dataclass(frozen=True)
class LaunchModelResolution:
    """The selected model and rendered flags for a single computed launch."""

    model: str | None
    flags: str


@dataclass(frozen=True)
class CommandDispatchPolicy:
    """Deterministic agent order and thinking mode for one canonical command."""

    agent_order: tuple[str, ...]
    thinking_mode: RunSessionThinkingMode


def classify_fresh_agent_preference(
    preferred_agent: str | None,
    *,
    caller_system_role: str | None,
) -> tuple[AgentDispatchMode, str | None]:
    """Classify an explicit fresh-session agent by caller authority."""
    mode = (
        AgentDispatchMode.AUTOMATIC
        if preferred_agent is None or caller_system_role is not None
        else AgentDispatchMode.MANUAL_PREFERENCE
    )
    return mode, preferred_agent


_GLOBAL_ORDER = agent_permutation(AgentName.CLAUDE, AgentName.CODEX, AgentName.GEMINI, AgentName.DEEPSEEK)
_CODEX_FIRST = agent_permutation(AgentName.CODEX, AgentName.CLAUDE, AgentName.GEMINI, AgentName.DEEPSEEK)
_GEMINI_FIRST = agent_permutation(AgentName.GEMINI, AgentName.CLAUDE, AgentName.CODEX, AgentName.DEEPSEEK)

_COMMAND_POLICIES: dict[SlashCommand, CommandDispatchPolicy] = {
    SlashCommand.BUILD: CommandDispatchPolicy(_CODEX_FIRST, RunSessionThinkingMode.MED),
    SlashCommand.REVIEW_BUILD: CommandDispatchPolicy(_CODEX_FIRST, RunSessionThinkingMode.MED),
    SlashCommand.REVIEW_PRD: CommandDispatchPolicy(_CODEX_FIRST, RunSessionThinkingMode.SLOW),
    SlashCommand.REVIEW_PLAN: CommandDispatchPolicy(_CODEX_FIRST, RunSessionThinkingMode.SLOW),
    SlashCommand.REVIEW_ARCHITECTURE: CommandDispatchPolicy(_CODEX_FIRST, RunSessionThinkingMode.SLOW),
    SlashCommand.REVIEW_COMMITS: CommandDispatchPolicy(_CODEX_FIRST, RunSessionThinkingMode.SLOW),
    SlashCommand.FINALIZE: CommandDispatchPolicy(_GEMINI_FIRST, RunSessionThinkingMode.FAST),
    SlashCommand.PREPARE_INTAKE: CommandDispatchPolicy(_GLOBAL_ORDER, RunSessionThinkingMode.SLOW),
    SlashCommand.PREPARE_ARCHITECTURE: CommandDispatchPolicy(_GLOBAL_ORDER, RunSessionThinkingMode.SLOW),
    SlashCommand.PREPARE_DIAGNOSE: CommandDispatchPolicy(_CODEX_FIRST, RunSessionThinkingMode.MED),
    SlashCommand.PREPARE_PLAN: CommandDispatchPolicy(_GLOBAL_ORDER, RunSessionThinkingMode.SLOW),
    SlashCommand.PREPARE_TASK: CommandDispatchPolicy(_GLOBAL_ORDER, RunSessionThinkingMode.MED),
    SlashCommand.DRIFT_ANALYZE: CommandDispatchPolicy(_CODEX_FIRST, RunSessionThinkingMode.FAST),
    SlashCommand.PREPARE: CommandDispatchPolicy(_GLOBAL_ORDER, RunSessionThinkingMode.SLOW),
    SlashCommand.WORK: CommandDispatchPolicy(_CODEX_FIRST, RunSessionThinkingMode.SLOW),
    SlashCommand.RUN_TASK: CommandDispatchPolicy(_CODEX_FIRST, RunSessionThinkingMode.MED),
    SlashCommand.INTEGRATE: CommandDispatchPolicy(_CODEX_FIRST, RunSessionThinkingMode.SLOW),
    SlashCommand.COORDINATE: CommandDispatchPolicy(_GLOBAL_ORDER, RunSessionThinkingMode.SLOW),
    SlashCommand.CREATE: CommandDispatchPolicy(_GLOBAL_ORDER, RunSessionThinkingMode.SLOW),
    SlashCommand.CREATE_ART: CommandDispatchPolicy(_GEMINI_FIRST, RunSessionThinkingMode.MED),
    SlashCommand.CREATE_HTML: CommandDispatchPolicy(_GEMINI_FIRST, RunSessionThinkingMode.MED),
    SlashCommand.DEFER: CommandDispatchPolicy(_GLOBAL_ORDER, RunSessionThinkingMode.SLOW),
    SlashCommand.ACTIVATE_PROCEDURE: CommandDispatchPolicy(_GLOBAL_ORDER, RunSessionThinkingMode.MED),
}
# Desk sessions take their order from the session kind, never from the
# visitor's first message; only agents with a verified desk confinement are
# eligible (see ``_desk_confined``).
_SESSION_KIND_POLICIES: dict[DispatchSessionKind, CommandDispatchPolicy] = {
    DispatchSessionKind.HELP_DESK: CommandDispatchPolicy(_GLOBAL_ORDER, RunSessionThinkingMode.SLOW),
}
_DESK_CONFINEMENT_UNVERIFIED_MESSAGE = "Agent '{agent}' has no verified desk confinement"
_THINKING_MODE_REQUIRED_MESSAGE = "Assess the work and retry with an explicit thinking mode: fast, med, or slow"
_MODEL_SKIP_REASON_PREFIX = "model_"
_COMMAND_PREFIX = "/"


def _order_for(
    command: str | None,
) -> tuple[tuple[str, ...], AgentDispatchReason, AgentDispatchOrderBranch]:
    slash_command = None
    if command is not None and command.startswith(_COMMAND_PREFIX):
        # A leading slash marks a genuine command attempt; anything else is
        # generic fresh work and is never parsed here. A bare token is
        # resolved against the global corpus first, so an unqualified
        # lifecycle command still matches its `SlashCommand` member.
        token = command.lstrip(_COMMAND_PREFIX).split(maxsplit=1)[0]
        slash_command = resolve_slash_command(token)
        if slash_command is None:
            logger.error("agent_dispatch_command_unmapped")
    if slash_command is None:
        return _GLOBAL_ORDER, AgentDispatchReason.GLOBAL_UNMAPPED_ROLE, AgentDispatchOrderBranch.GLOBAL
    policy = _COMMAND_POLICIES.get(slash_command)
    if policy is None:
        logger.error("agent_dispatch_policy_defect command=%s", slash_command.value)
        return _GLOBAL_ORDER, AgentDispatchReason.KNOWN_ROLE_POLICY_DEFECT, AgentDispatchOrderBranch.GLOBAL
    return policy.agent_order, AgentDispatchReason.ROLE_PREFERENCE, AgentDispatchOrderBranch.COMMAND_POLICY


def desk_session_kind(
    system_role: str | None,
    human_role: str | None,
    endpoint: EndpointStamp | None = None,
) -> DispatchSessionKind | None:
    """Return the help-desk session kind for a session placed at a desk.

    A session is a desk session when its roles place it at a desk (below
    member, no system role) or when its endpoint is a help desk, whatever the
    entering person's role.
    """
    at_desk = is_desk_role(system_role, human_role) or (endpoint is not None and endpoint.is_help_desk)
    return DispatchSessionKind.HELP_DESK if at_desk else None


def _desk_confined(agent: str) -> bool:
    return AGENT_REGISTRY[AgentName.from_str(agent)].desk_confinement is DeskConfinement.VERIFIED


def _require_desk_confined(agent: str, session_kind: DispatchSessionKind | None) -> None:
    if session_kind is DispatchSessionKind.HELP_DESK and not _desk_confined(agent):
        raise AgentDispatchFailure(
            AgentDispatchReason.DESK_CONFINEMENT_UNVERIFIED,
            _DESK_CONFINEMENT_UNVERIFIED_MESSAGE.format(agent=agent),
        )


def _order_with_preference(order: tuple[str, ...], preferred_agent: str | None) -> tuple[str, ...]:
    if preferred_agent is None:
        return order
    return (preferred_agent,) + tuple(agent for agent in order if agent != preferred_agent)


def resolve_run_session_thinking_mode(
    *,
    caller_mode: RunSessionThinkingMode | None,
    command: SlashCommand | None,
) -> RunSessionThinkingMode:
    """Resolve one effective thinking mode from caller and command facts."""
    if caller_mode is not None:
        return caller_mode
    policy = _COMMAND_POLICIES.get(command) if command is not None else None
    if policy is not None:
        return policy.thinking_mode
    raise AgentDispatchFailure(
        AgentDispatchReason.THINKING_MODE_REQUIRED,
        _THINKING_MODE_REQUIRED_MESSAGE,
    )


def _configured_enabled(agent: str) -> bool:
    entry = config.agents.get(AgentName.from_str(agent))
    return entry is not None and entry.enabled


async def _availability_facts(agent: str) -> AgentAvailabilityStatus:
    if not db.is_initialized():
        raise AgentDispatchFailure(
            AgentDispatchReason.AVAILABILITY_READ_FAILED,
            "Agent availability database is not initialized",
        )
    try:
        availability = await db.get_agent_availability(agent)
    except (SQLAlchemyError, ValueError) as exc:
        raise AgentDispatchFailure(
            AgentDispatchReason.AVAILABILITY_READ_FAILED,
            "Unable to read agent availability",
        ) from exc
    if availability is None:
        return AgentAvailabilityStatus.AVAILABLE
    return availability.status


async def resolve_launch_model(
    agent: str,
    thinking_mode: str,
    *,
    ownership: LaunchOwnership,
    session_id: str | None = None,
) -> LaunchModelResolution:
    """Resolve one computed launch through its declared model fallback chain."""
    agent_cfg = config.agents.get(AgentName.from_str(agent))
    if agent_cfg is None:
        raise AgentDispatchFailure(AgentDispatchReason.UNKNOWN_AGENT, f"Unknown agent '{agent}'")
    default_chain = agent_cfg.mode_chains.get(thinking_mode)
    if default_chain is None:
        raise AgentDispatchFailure(
            AgentDispatchReason.THINKING_MODE_REQUIRED,
            f"Invalid thinking mode '{thinking_mode}' for agent '{agent}'",
        )
    if thinking_mode == "default":
        logger.info(
            "model_launch_resolved agent=%s thinking_mode=%s session_id=%s selected_model=%s chain_position=%d override_active=%s launch_ownership=%s",
            agent,
            thinking_mode,
            session_id,
            None,
            0,
            False,
            ownership.value,
        )
        return LaunchModelResolution(model=None, flags="")
    chain = agent_cfg.model_chains.get(thinking_mode, default_chain)
    try:
        model_rows = await db.list_model_availability(agent)
    except (OSError, RuntimeError, SQLAlchemyError, ValueError) as exc:
        raise ModelAvailabilityStateFailure(
            AgentDispatchReason.MODEL_AVAILABILITY_READ_FAILED,
            f"Unable to read model availability for agent '{agent}'",
        ) from exc
    for position, entry in enumerate(chain):
        model = entry.model
        state = model_rows.get(model)
        status = state.status if state is not None else AgentAvailabilityStatus.AVAILABLE
        if not is_launchable(status, ownership):
            continue
        flags = entry.flags
        logger.info(
            "model_launch_resolved agent=%s thinking_mode=%s session_id=%s selected_model=%s chain_position=%d override_active=%s launch_ownership=%s",
            agent,
            thinking_mode,
            session_id,
            model,
            position,
            thinking_mode in agent_cfg.model_chains,
            ownership.value,
        )
        if position:
            skipped_models = [skipped.model for skipped in chain[:position]]
            skipped_statuses = [
                (
                    model_rows.get(skipped.model) or AvailabilityState(AgentAvailabilityStatus.AVAILABLE, None, None)
                ).status.value
                for skipped in chain[:position]
            ]
            logger.info(
                "model_launch_fallback agent=%s thinking_mode=%s session_id=%s skipped_models=%s skipped_statuses=%s selected_model=%s reason=%s launch_ownership=%s",
                agent,
                thinking_mode,
                session_id,
                skipped_models,
                skipped_statuses,
                model,
                _MODEL_SKIP_REASON_PREFIX + skipped_statuses[0],
                ownership.value,
            )
        return LaunchModelResolution(model=model, flags=flags)
    model_statuses = [
        (model_rows.get(entry.model) or AvailabilityState(AgentAvailabilityStatus.AVAILABLE, None, None)).status.value
        for entry in chain
    ]
    logger.info(
        "model_chain_exhausted agent=%s thinking_mode=%s session_id=%s models_checked=%s model_statuses=%s launch_ownership=%s",
        agent,
        thinking_mode,
        session_id,
        [entry.model for entry in chain],
        model_statuses,
        ownership.value,
    )
    raise ModelChainExhausted(
        AgentDispatchReason.MODEL_CHAIN_EXHAUSTED,
        f"Every declared model is unavailable for {ownership.value} launch of agent '{agent}' mode '{thinking_mode}'",
    )


def _known_enabled(agent: str) -> None:
    try:
        AgentName.from_str(agent)
    except ValueError as exc:
        raise AgentDispatchFailure(AgentDispatchReason.UNKNOWN_AGENT, str(exc)) from exc
    if not _configured_enabled(agent):
        raise AgentDispatchFailure(AgentDispatchReason.DISABLED_AGENT, f"Agent '{agent}' is disabled by configuration")


async def resolve_agent_dispatch(
    *,
    mode: AgentDispatchMode,
    role: str | None,
    command: str | None,
    preferred_agent: str | None,
    fixed_agent: str | None,
    candidate_order: tuple[str, ...] | None,
    entry_point: SessionEntryPoint | None,
    session_kind: DispatchSessionKind | None = None,
) -> AgentDispatchDecision:
    """Select one eligible agent without consulting the caller's machine state.

    A ``session_kind`` takes the order from that kind's row instead of the
    command; for a help-desk session every candidate must carry a verified
    desk confinement, and each one skipped for lacking it is logged.
    """
    ownership = LaunchOwnership.HUMAN if mode is AgentDispatchMode.MANUAL_PREFERENCE else LaunchOwnership.JOB_ROLE

    if mode is AgentDispatchMode.FIXED:
        if not fixed_agent:
            raise AgentDispatchFailure(
                AgentDispatchReason.FIXED_AGENT_REQUIRED, "Fixed launch intent requires an agent"
            )
        _known_enabled(fixed_agent)
        _require_desk_confined(fixed_agent, session_kind)
        if not is_launchable(await _availability_facts(fixed_agent), ownership):
            raise AgentDispatchFailure(
                AgentDispatchReason.FIXED_AGENT_UNAVAILABLE,
                f"Fixed agent '{fixed_agent}' is not available",
            )
        return AgentDispatchDecision(agent=fixed_agent, reason=AgentDispatchReason.FIXED_AGENT)

    if mode is AgentDispatchMode.MANUAL_PREFERENCE:
        if not preferred_agent:
            raise AgentDispatchFailure(
                AgentDispatchReason.PREFERRED_AGENT_REQUIRED, "Manual launch intent requires an agent"
            )
        _known_enabled(preferred_agent)
        _require_desk_confined(preferred_agent, session_kind)
        status = await _availability_facts(preferred_agent)
        if not is_launchable(status, ownership):
            raise AgentDispatchFailure(
                AgentDispatchReason.MANUAL_PREFERENCE_UNAVAILABLE,
                f"Manual agent '{preferred_agent}' is not available",
            )
        reason = (
            AgentDispatchReason.MANUAL_PREFERENCE_DEGRADED
            if status is AgentAvailabilityStatus.DEGRADED
            else AgentDispatchReason.MANUAL_PREFERENCE
        )
        return AgentDispatchDecision(agent=preferred_agent, reason=reason)

    if session_kind is not None:
        policy_order = _SESSION_KIND_POLICIES[session_kind].agent_order
        reason = AgentDispatchReason.SESSION_KIND_POLICY
        order_branch = AgentDispatchOrderBranch.SESSION_KIND
    elif candidate_order:
        policy_order = candidate_order
        reason = AgentDispatchReason.JOB_DECLARATION
        order_branch = AgentDispatchOrderBranch.JOB_DECLARATION
    else:
        policy_order, reason, order_branch = _order_for(command)
    order = _order_with_preference(policy_order, preferred_agent)
    desk_skipped: list[str] = []
    eligible: list[str] = []
    for agent in order:
        if session_kind is DispatchSessionKind.HELP_DESK and not _desk_confined(agent):
            desk_skipped.append(agent)
            emit_agent_dispatch_decision(
                stage=AgentDispatchStage.RESOLVED,
                outcome=AgentDispatchOutcome.REFUSED,
                reason=AgentDispatchReason.DESK_CONFINEMENT_UNVERIFIED,
                selected_agent=agent,
                entry_point=entry_point,
                candidate_order=policy_order,
                order_branch=order_branch,
            )
            continue
        if _configured_enabled(agent) and is_launchable(await _availability_facts(agent), ownership):
            eligible.append(agent)
    if not eligible:
        raise AgentDispatchFailure(
            AgentDispatchReason.NO_ELIGIBLE_CANDIDATE,
            "No configured and available agent can run this session",
        )

    fallback = None
    if eligible[0] != order[0]:
        fallback = (
            AgentDispatchReason.DESK_CONFINEMENT_UNVERIFIED
            if order[0] in desk_skipped
            else AgentDispatchReason.DETERMINISTIC_INELIGIBILITY
        )
    return AgentDispatchDecision(
        agent=eligible[0],
        reason=reason,
        fallback_reason=fallback,
        candidate_order=policy_order,
        order_branch=order_branch,
    )


def emit_agent_dispatch_decision(
    *,
    stage: AgentDispatchStage,
    reason: AgentDispatchReason,
    outcome: AgentDispatchOutcome,
    selected_agent: str | None = None,
    request_id: str | None = None,
    session_id: str | None = None,
    dispatch_mode: AgentDispatchMode | None = None,
    entry_point: SessionEntryPoint | None = None,
    job_role: str | None = None,
    todo_kind: str | None = None,
    fallback_reason: AgentDispatchReason | None = None,
    preferred_agent: str | None = None,
    fixed_agent: str | None = None,
    policy: AgentDispatchPolicy = AgentDispatchPolicy.EACH_OPPORTUNITY,
    revision: int = 1,
    agent_supplied: bool | None = None,
    working_slug_present: bool | None = None,
    command_kind: str | None = None,
    thinking_mode: str | None = None,
    caller_kind_present: bool | None = None,
    routing_explanation_included: bool | None = None,
    kind_source: AgentDispatchKindSource = AgentDispatchKindSource.NOT_APPLICABLE,
    decision_basis_digest: str | None = None,
    candidate_order: tuple[str, ...] = (),
    order_branch: AgentDispatchOrderBranch | None = None,
    error: bool = False,
) -> None:
    """Emit the single privacy-safe routing record family.

    ``candidate_order`` and ``order_branch`` are populated only for an
    automatic-dispatch decision; they distinguish a correctly resolved
    order from a reordered one (OM-13/OM-14), since two branches can share
    one ``reason`` token while disagreeing on the order they resolved.
    """
    emit = logger.error if error else logger.info
    emit(
        "agent_runtime.agent_dispatch.decision stage=%s outcome=%s reason=%s selected_agent=%s "
        "request_id=%s session_id=%s dispatch_mode=%s entry_point=%s job_role=%s todo_kind=%s "
        "fallback_reason_present=%s policy=%s revision=%s agent_supplied=%s working_slug_present=%s "
        "kind_source=%s decision_basis_digest=%s preferred_agent=%s fixed_agent=%s "
        "command_kind=%s thinking_mode=%s caller_kind_present=%s "
        "routing_explanation_included=%s candidate_order=%s order_branch=%s",
        stage,
        outcome,
        reason,
        selected_agent,
        request_id,
        session_id,
        dispatch_mode,
        entry_point,
        job_role,
        todo_kind,
        fallback_reason is not None,
        policy,
        revision,
        agent_supplied,
        working_slug_present,
        kind_source,
        decision_basis_digest,
        preferred_agent,
        fixed_agent,
        command_kind,
        thinking_mode,
        caller_kind_present,
        routing_explanation_included,
        ",".join(candidate_order) if candidate_order else None,
        order_branch,
    )


def emit_agent_launch_started(*, session_id: str, agent: str) -> None:
    """Emit the launch-started record once the agent command is handed to tmux (OM-1).

    Closes the launch half of the OM-1 correlation: session_committed (this
    module, stage=session_committed) names the session id the caller
    accepted; this record confirms that session actually reached tmux, with
    the registry revision the launch resolved against.
    """
    logger.info(
        "agent_runtime.agent_launch.started session_id=%s agent=%s registry_digest=%s outcome=started",
        session_id,
        agent,
        registry_digest(),
    )


def decision_basis_digest(
    *,
    mode: AgentDispatchMode,
    role: str | None,
    todo_kind: str | None,
    preferred_agent: str | None,
    fixed_agent: str | None,
    candidate_order: tuple[str, ...] | None = None,
) -> str:
    """Create a stable privacy-safe correlation basis for equivalent decisions."""
    basis = json.dumps(
        {
            "fixed_agent": fixed_agent,
            "mode": mode.value,
            "preferred_agent": preferred_agent,
            "candidate_order": candidate_order,
            "role": role,
            "todo_kind": todo_kind,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(basis.encode()).hexdigest()
