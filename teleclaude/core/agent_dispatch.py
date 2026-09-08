"""Deterministic, target-local agent selection for fresh sessions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from sqlalchemy.exc import SQLAlchemyError

from teleclaude.agent_registry import agent_permutation, registry_digest
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
from teleclaude.core.models._session import AgentDispatchMode
from teleclaude.types.todo_kind import TODO_KIND_BUG, TODO_KIND_CHANGE, TODO_KIND_FEATURE

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
    REVIEWER_INDEPENDENCE = "reviewer_independence"
    UNKNOWN_AGENT = "unknown_agent"
    DISABLED_AGENT = "disabled_agent"
    AVAILABILITY_READ_FAILED = "availability_read_failed"
    NO_ELIGIBLE_CANDIDATE = "no_eligible_candidate"
    NO_INDEPENDENT_CANDIDATE = "no_independent_candidate"
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
    TODO_KIND = "todo_kind"
    GLOBAL = "global"


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
    SlashCommand.ANALYZE_TODO_INPUT: CommandDispatchPolicy(_GLOBAL_ORDER, RunSessionThinkingMode.SLOW),
    SlashCommand.NEXT_BUILD: CommandDispatchPolicy(_CODEX_FIRST, RunSessionThinkingMode.MED),
    SlashCommand.NEXT_REVIEW_BUILD: CommandDispatchPolicy(_CODEX_FIRST, RunSessionThinkingMode.MED),
    SlashCommand.NEXT_REVIEW_PRD: CommandDispatchPolicy(_CODEX_FIRST, RunSessionThinkingMode.SLOW),
    SlashCommand.NEXT_REVIEW_PLAN: CommandDispatchPolicy(_CODEX_FIRST, RunSessionThinkingMode.SLOW),
    SlashCommand.NEXT_REVIEW_ARCHITECTURE: CommandDispatchPolicy(_CODEX_FIRST, RunSessionThinkingMode.SLOW),
    SlashCommand.NEXT_REVIEW_COMMITS: CommandDispatchPolicy(_CODEX_FIRST, RunSessionThinkingMode.MED),
    SlashCommand.NEXT_FINALIZE: CommandDispatchPolicy(_GEMINI_FIRST, RunSessionThinkingMode.FAST),
    SlashCommand.NEXT_PREPARE_INTAKE: CommandDispatchPolicy(_GLOBAL_ORDER, RunSessionThinkingMode.SLOW),
    SlashCommand.NEXT_PREPARE_ARCHITECTURE: CommandDispatchPolicy(_GLOBAL_ORDER, RunSessionThinkingMode.SLOW),
    SlashCommand.NEXT_PREPARE_DIAGNOSE: CommandDispatchPolicy(_CODEX_FIRST, RunSessionThinkingMode.MED),
    SlashCommand.NEXT_PREPARE_PLAN: CommandDispatchPolicy(_GLOBAL_ORDER, RunSessionThinkingMode.SLOW),
    SlashCommand.NEXT_PREPARE_TASK: CommandDispatchPolicy(_GLOBAL_ORDER, RunSessionThinkingMode.MED),
    SlashCommand.NEXT_EMULATE_PO: CommandDispatchPolicy(
        agent_permutation(AgentName.CLAUDE, AgentName.GEMINI, AgentName.CODEX, AgentName.DEEPSEEK),
        RunSessionThinkingMode.MED,
    ),
    SlashCommand.NEXT_DRIFT_ANALYZE: CommandDispatchPolicy(_CODEX_FIRST, RunSessionThinkingMode.FAST),
    SlashCommand.NEXT_PREPARE: CommandDispatchPolicy(_GLOBAL_ORDER, RunSessionThinkingMode.SLOW),
    SlashCommand.NEXT_WORK: CommandDispatchPolicy(_CODEX_FIRST, RunSessionThinkingMode.MED),
    SlashCommand.NEXT_RUN_TASK: CommandDispatchPolicy(_CODEX_FIRST, RunSessionThinkingMode.MED),
    SlashCommand.NEXT_INTEGRATE: CommandDispatchPolicy(_CODEX_FIRST, RunSessionThinkingMode.SLOW),
    SlashCommand.NEXT_COORDINATE: CommandDispatchPolicy(_GLOBAL_ORDER, RunSessionThinkingMode.SLOW),
    SlashCommand.NEXT_CREATE: CommandDispatchPolicy(_GLOBAL_ORDER, RunSessionThinkingMode.MED),
    SlashCommand.NEXT_CREATE_ART: CommandDispatchPolicy(_GEMINI_FIRST, RunSessionThinkingMode.MED),
    SlashCommand.NEXT_CREATE_HTML: CommandDispatchPolicy(_GEMINI_FIRST, RunSessionThinkingMode.MED),
    SlashCommand.NEXT_DEFER: CommandDispatchPolicy(_GLOBAL_ORDER, RunSessionThinkingMode.SLOW),
    SlashCommand.NEXT_RUN_JOB: CommandDispatchPolicy(_GLOBAL_ORDER, RunSessionThinkingMode.FAST),
}
_THINKING_MODE_REQUIRED_MESSAGE = "Assess the work and retry with an explicit thinking mode: fast, med, or slow"
_MODEL_SKIP_REASON_PREFIX = "model_"


def _command_policy(command: str | None) -> CommandDispatchPolicy | None:
    if command is None:
        return None
    try:
        return _COMMAND_POLICIES.get(SlashCommand(command.lstrip("/").split(maxsplit=1)[0]))
    except ValueError:
        return None


def _order_for(
    command: str | None, todo_kind: str | None
) -> tuple[tuple[str, ...], AgentDispatchReason, AgentDispatchOrderBranch]:
    command_name = command.lstrip("/").split(maxsplit=1)[0] if command is not None else None
    if command_name == SlashCommand.NEXT_PREPARE.value:
        if todo_kind == TODO_KIND_FEATURE:
            return (
                _COMMAND_POLICIES[SlashCommand.NEXT_PREPARE].agent_order,
                AgentDispatchReason.ROLE_PREFERENCE,
                AgentDispatchOrderBranch.TODO_KIND,
            )
        if todo_kind in {TODO_KIND_CHANGE, TODO_KIND_BUG}:
            return _CODEX_FIRST, AgentDispatchReason.ROLE_PREFERENCE, AgentDispatchOrderBranch.TODO_KIND
        return (
            _COMMAND_POLICIES[SlashCommand.NEXT_PREPARE].agent_order,
            AgentDispatchReason.GLOBAL_UNMAPPED_ROLE,
            AgentDispatchOrderBranch.TODO_KIND,
        )
    policy = _command_policy(command)
    if policy is None:
        return _GLOBAL_ORDER, AgentDispatchReason.GLOBAL_UNMAPPED_ROLE, AgentDispatchOrderBranch.GLOBAL
    return policy.agent_order, AgentDispatchReason.ROLE_PREFERENCE, AgentDispatchOrderBranch.COMMAND_POLICY


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
    entry = config.agents.get(agent)
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
    agent_cfg = config.agents.get(agent)
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
    todo_kind: str | None,
    preferred_agent: str | None,
    fixed_agent: str | None,
    producer_agent: str | None,
    entry_point: SessionEntryPoint | None,
) -> AgentDispatchDecision:
    """Select one eligible agent without consulting the caller's machine state."""
    del entry_point  # Kept typed at the boundary for structured decision evidence.
    ownership = LaunchOwnership.HUMAN if mode is AgentDispatchMode.MANUAL_PREFERENCE else LaunchOwnership.JOB_ROLE

    if mode is AgentDispatchMode.FIXED:
        if not fixed_agent:
            raise AgentDispatchFailure(
                AgentDispatchReason.FIXED_AGENT_REQUIRED, "Fixed launch intent requires an agent"
            )
        _known_enabled(fixed_agent)
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

    policy_order, reason, order_branch = _order_for(command, todo_kind)
    order = _order_with_preference(policy_order, preferred_agent)
    eligible = [
        agent
        for agent in order
        if _configured_enabled(agent) and is_launchable(await _availability_facts(agent), ownership)
    ]
    if not eligible:
        raise AgentDispatchFailure(
            AgentDispatchReason.NO_ELIGIBLE_CANDIDATE,
            "No configured and available agent can run this session",
        )

    if role == "reviewer" and producer_agent:
        independent = [agent for agent in eligible if agent != producer_agent]
        if independent:
            fallback = (
                AgentDispatchReason.REVIEWER_INDEPENDENCE
                if preferred_agent == eligible[0] and independent[0] != preferred_agent
                else None
            )
            return AgentDispatchDecision(
                agent=independent[0],
                reason=reason,
                fallback_reason=fallback,
                candidate_order=policy_order,
                order_branch=order_branch,
            )
        return AgentDispatchDecision(
            agent=eligible[0],
            reason=AgentDispatchReason.NO_INDEPENDENT_CANDIDATE,
            candidate_order=policy_order,
            order_branch=order_branch,
        )

    fallback = AgentDispatchReason.DETERMINISTIC_INELIGIBILITY if eligible[0] != order[0] else None
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
    producer_agent: str | None = None,
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
        "kind_source=%s decision_basis_digest=%s preferred_agent=%s fixed_agent=%s producer_agent=%s "
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
        producer_agent,
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
    producer_agent: str | None,
) -> str:
    """Create a stable privacy-safe correlation basis for equivalent decisions."""
    basis = json.dumps(
        {
            "fixed_agent": fixed_agent,
            "mode": mode.value,
            "preferred_agent": preferred_agent,
            "producer_agent": producer_agent,
            "role": role,
            "todo_kind": todo_kind,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(basis.encode()).hexdigest()
