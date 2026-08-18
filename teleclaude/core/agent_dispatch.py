"""Deterministic, target-local agent selection for fresh sessions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger
from sqlalchemy.exc import SQLAlchemyError

from teleclaude.config import config
from teleclaude.constants import JobRole
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


class AgentAvailabilityStatus(StrEnum):
    """Closed operator-availability states used by agent dispatch."""

    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class AgentAvailabilityFacts:
    """Availability facts interpreted by the mode-specific dispatch rules."""

    available: bool
    status: AgentAvailabilityStatus

    @property
    def automatically_eligible(self) -> bool:
        """Return whether the agent belongs in the automatic candidate pool."""
        return self.available and self.status is AgentAvailabilityStatus.AVAILABLE

    @property
    def manually_selectable(self) -> bool:
        """Return whether an explicit selection may launch this agent."""
        return self.available and self.status in {
            AgentAvailabilityStatus.AVAILABLE,
            AgentAvailabilityStatus.DEGRADED,
        }


@dataclass(frozen=True)
class AgentDispatchDecision:
    """Selected agent plus a stable, non-user-facing decision reason."""

    agent: str
    reason: AgentDispatchReason
    fallback_reason: AgentDispatchReason | None = None


@dataclass(frozen=True)
class LaunchModelResolution:
    """The selected model and rendered flags for a single computed launch."""

    model: str | None
    flags: str


@dataclass(frozen=True)
class JobDispatchPolicy:
    """Deterministic agent order and optional thinking mode for one job."""

    agent_order: tuple[str, ...]
    thinking_mode: RunSessionThinkingMode | None = None


_GLOBAL_ORDER = ("claude", "codex", "gemini")
_CODEX_FIRST = ("codex", "claude", "gemini")
_GEMINI_FIRST = ("gemini", "claude", "codex")

_PREPARE_POLICY = JobDispatchPolicy(_GLOBAL_ORDER, RunSessionThinkingMode.SLOW)

_JOB_POLICIES: dict[str, JobDispatchPolicy] = {
    JobRole.WORK_ORCHESTRATOR.value: JobDispatchPolicy(_CODEX_FIRST, RunSessionThinkingMode.MED),
    JobRole.BUILDER.value: JobDispatchPolicy(_CODEX_FIRST),
    JobRole.REVIEWER.value: JobDispatchPolicy(_CODEX_FIRST),
    JobRole.FINALIZER.value: JobDispatchPolicy(_CODEX_FIRST),
    JobRole.INTAKER.value: JobDispatchPolicy(_GLOBAL_ORDER),
    JobRole.PLANNER.value: JobDispatchPolicy(_GLOBAL_ORDER),
    JobRole.DIAGNOSER.value: JobDispatchPolicy(_CODEX_FIRST),
    JobRole.ARCHITECT.value: JobDispatchPolicy(_GLOBAL_ORDER),
    JobRole.ARCHITECTURE_REVIEWER.value: JobDispatchPolicy(_GLOBAL_ORDER),
    JobRole.TASK_PREPARER.value: JobDispatchPolicy(_GLOBAL_ORDER, RunSessionThinkingMode.MED),
    JobRole.TASK_RUNNER.value: JobDispatchPolicy(_CODEX_FIRST, RunSessionThinkingMode.MED),
    JobRole.DRIFT_ANALYZER.value: JobDispatchPolicy(_CODEX_FIRST, RunSessionThinkingMode.FAST),
    JobRole.PO_EMULATOR.value: JobDispatchPolicy(("claude", "gemini", "codex")),
    JobRole.CREATE_ORCHESTRATOR.value: JobDispatchPolicy(_GEMINI_FIRST),
    JobRole.ARTIST.value: JobDispatchPolicy(_GEMINI_FIRST),
    JobRole.FRONTENDER.value: JobDispatchPolicy(_GEMINI_FIRST),
    JobRole.INTEGRATOR.value: JobDispatchPolicy(_CODEX_FIRST),
}
_KNOWN_CANONICAL_ROLES = frozenset(role.value for role in JobRole)
_THINKING_MODE_REQUIRED_MESSAGE = "Assess the work and retry with an explicit thinking mode: fast, med, or slow"


def _policy_for(role: str | None) -> JobDispatchPolicy | None:
    if role == JobRole.PREPARE_ORCHESTRATOR.value:
        return _PREPARE_POLICY
    if role is None:
        return None
    return _JOB_POLICIES.get(role)


def _order_for(role: str | None, todo_kind: str | None) -> tuple[tuple[str, ...], AgentDispatchReason]:
    if role == JobRole.PREPARE_ORCHESTRATOR.value:
        if todo_kind == TODO_KIND_FEATURE:
            return _PREPARE_POLICY.agent_order, AgentDispatchReason.ROLE_PREFERENCE
        if todo_kind in {TODO_KIND_CHANGE, TODO_KIND_BUG}:
            return _CODEX_FIRST, AgentDispatchReason.ROLE_PREFERENCE
        return _PREPARE_POLICY.agent_order, AgentDispatchReason.GLOBAL_UNMAPPED_ROLE
    if role is None:
        return _GLOBAL_ORDER, AgentDispatchReason.GLOBAL_UNMAPPED_ROLE
    policy = _policy_for(role)
    if policy is None and role in _KNOWN_CANONICAL_ROLES:
        return _GLOBAL_ORDER, AgentDispatchReason.KNOWN_ROLE_POLICY_DEFECT
    if policy is None:
        return _GLOBAL_ORDER, AgentDispatchReason.GLOBAL_UNMAPPED_ROLE
    return policy.agent_order, AgentDispatchReason.ROLE_PREFERENCE


def resolve_run_session_thinking_mode(
    *,
    caller_mode: RunSessionThinkingMode | None,
    job_role: str | None,
) -> RunSessionThinkingMode:
    """Resolve one effective thinking mode from caller and job facts."""
    if caller_mode is not None:
        return caller_mode
    policy = _policy_for(job_role)
    if job_role is not None:
        return policy.thinking_mode if policy and policy.thinking_mode is not None else RunSessionThinkingMode.SLOW
    raise AgentDispatchFailure(
        AgentDispatchReason.THINKING_MODE_REQUIRED,
        _THINKING_MODE_REQUIRED_MESSAGE,
    )


def _configured_enabled(agent: str) -> bool:
    entry = config.agents.get(agent)
    return entry is not None and entry.enabled


async def _availability_facts(agent: str) -> AgentAvailabilityFacts:
    if not db.is_initialized():
        raise AgentDispatchFailure(
            AgentDispatchReason.AVAILABILITY_READ_FAILED,
            "Agent availability database is not initialized",
        )
    try:
        availability = await db.get_agent_availability(agent)
    except SQLAlchemyError as exc:
        raise AgentDispatchFailure(
            AgentDispatchReason.AVAILABILITY_READ_FAILED,
            "Unable to read agent availability",
        ) from exc
    if availability is None:
        return AgentAvailabilityFacts(available=True, status=AgentAvailabilityStatus.AVAILABLE)
    status_value = availability.get("status")
    try:
        status = (
            AgentAvailabilityStatus(status_value)
            if isinstance(status_value, str)
            else AgentAvailabilityStatus.UNAVAILABLE
        )
    except ValueError:
        status = AgentAvailabilityStatus.UNAVAILABLE
    return AgentAvailabilityFacts(available=bool(availability.get("available")), status=status)


async def resolve_launch_model(
    agent: str,
    thinking_mode: str,
    *,
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
            "model_launch_resolved agent=%s mode=%s session_id=%s selected_model=%s chain_position=%d override_active=%s",
            agent,
            thinking_mode,
            session_id,
            None,
            0,
            False,
        )
        return LaunchModelResolution(model=None, flags="")
    chain = agent_cfg.model_chains.get(thinking_mode, default_chain)
    try:
        model_rows = await db.list_model_availability(agent)
    except (OSError, RuntimeError, SQLAlchemyError) as exc:
        raise ModelAvailabilityStateFailure(
            AgentDispatchReason.MODEL_AVAILABILITY_READ_FAILED,
            f"Unable to read model availability for agent '{agent}'",
        ) from exc
    unavailable_models = {row["model"] for row in model_rows}
    for position, entry in enumerate(chain):
        model = entry.model
        if model in unavailable_models:
            continue
        flags = entry.flags
        logger.info(
            "model_launch_resolved agent=%s mode=%s session_id=%s selected_model=%s chain_position=%d override_active=%s",
            agent,
            thinking_mode,
            session_id,
            model,
            position,
            thinking_mode in agent_cfg.model_chains,
        )
        if position:
            skipped_models = [skipped.model for skipped in chain[:position]]
            logger.warning(
                "model_launch_fallback agent=%s mode=%s session_id=%s skipped_models=%s selected_model=%s reason=model_unavailable",
                agent,
                thinking_mode,
                session_id,
                skipped_models,
                model,
            )
        return LaunchModelResolution(model=model, flags=flags)
    logger.info(
        "model_chain_exhausted agent=%s mode=%s session_id=%s models_checked=%s",
        agent,
        thinking_mode,
        session_id,
        [entry.model for entry in chain],
    )
    raise ModelChainExhausted(
        AgentDispatchReason.MODEL_CHAIN_EXHAUSTED,
        f"Every declared model is unavailable for agent '{agent}' mode '{thinking_mode}'",
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
    todo_kind: str | None,
    preferred_agent: str | None,
    fixed_agent: str | None,
    producer_agent: str | None,
    entry_point: SessionEntryPoint | None,
) -> AgentDispatchDecision:
    """Select one eligible agent without consulting the caller's machine state."""
    del entry_point  # Kept typed at the boundary for structured decision evidence.

    if mode is AgentDispatchMode.FIXED:
        if not fixed_agent:
            raise AgentDispatchFailure(
                AgentDispatchReason.FIXED_AGENT_REQUIRED, "Fixed launch intent requires an agent"
            )
        _known_enabled(fixed_agent)
        if not (await _availability_facts(fixed_agent)).automatically_eligible:
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
        availability = await _availability_facts(preferred_agent)
        if not availability.manually_selectable:
            raise AgentDispatchFailure(
                AgentDispatchReason.MANUAL_PREFERENCE_UNAVAILABLE,
                f"Manual agent '{preferred_agent}' is not available",
            )
        reason = (
            AgentDispatchReason.MANUAL_PREFERENCE_DEGRADED
            if availability.status is AgentAvailabilityStatus.DEGRADED
            else AgentDispatchReason.MANUAL_PREFERENCE
        )
        return AgentDispatchDecision(agent=preferred_agent, reason=reason)

    order, reason = _order_for(role, todo_kind)
    eligible = [
        agent
        for agent in order
        if _configured_enabled(agent) and (await _availability_facts(agent)).automatically_eligible
    ]
    if not eligible:
        raise AgentDispatchFailure(
            AgentDispatchReason.NO_ELIGIBLE_CANDIDATE,
            "No configured and available agent can run this session",
        )

    if role == "reviewer" and producer_agent:
        independent = [agent for agent in eligible if agent != producer_agent]
        if independent:
            return AgentDispatchDecision(agent=independent[0], reason=reason)
        return AgentDispatchDecision(agent=eligible[0], reason=AgentDispatchReason.NO_INDEPENDENT_CANDIDATE)

    fallback = AgentDispatchReason.DETERMINISTIC_INELIGIBILITY if eligible[0] != order[0] else None
    return AgentDispatchDecision(agent=eligible[0], reason=reason, fallback_reason=fallback)


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
    caller_kind_present: bool | None = None,
    routing_explanation_included: bool | None = None,
    kind_source: AgentDispatchKindSource = AgentDispatchKindSource.NOT_APPLICABLE,
    decision_basis_digest: str | None = None,
    error: bool = False,
) -> None:
    """Emit the single privacy-safe routing record family."""
    emit = logger.error if error else logger.info
    emit(
        "agent_runtime.agent_dispatch.decision stage=%s outcome=%s reason=%s selected_agent=%s "
        "request_id=%s session_id=%s dispatch_mode=%s entry_point=%s job_role=%s todo_kind=%s "
        "fallback_reason_present=%s policy=%s revision=%s agent_supplied=%s working_slug_present=%s "
        "kind_source=%s decision_basis_digest=%s preferred_agent=%s fixed_agent=%s producer_agent=%s "
        "command_kind=%s caller_kind_present=%s routing_explanation_included=%s",
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
        caller_kind_present,
        routing_explanation_included,
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
