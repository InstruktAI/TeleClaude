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
    FIRST_ACTIVITY = "first_activity"
    FIRST_ACTIVITY_TIMEOUT = "first_activity_timeout"


class AgentDispatchStage(StrEnum):
    """Closed observation-map stages for agent dispatch decisions."""

    ACCEPTED = "accepted"
    TRANSPORT = "transport"
    RESOLVED = "resolved"
    RUN_OUTCOME = "run_outcome"
    STARTUP_PREPARED = "startup_prepared"
    RESPONSE_PRESENTED = "response_presented"
    SESSION_COMMITTED = "session_committed"
    LAUNCH_OUTCOME = "launch_outcome"


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


@dataclass(frozen=True)
class AgentDispatchDecision:
    """Selected agent plus a stable, non-user-facing decision reason."""

    agent: str
    reason: AgentDispatchReason
    fallback_reason: AgentDispatchReason | None = None


_GLOBAL_ORDER = ("claude", "codex", "gemini")
_CODEX_FIRST = ("codex", "claude", "gemini")
_GEMINI_FIRST = ("gemini", "claude", "codex")

_ROLE_ORDERS: dict[str, tuple[str, ...]] = {
    "work-orchestrator": _CODEX_FIRST,
    "builder": _CODEX_FIRST,
    "reviewer": _CODEX_FIRST,
    "finalizer": _CODEX_FIRST,
    "intaker": _GLOBAL_ORDER,
    "planner": _GLOBAL_ORDER,
    "diagnoser": _CODEX_FIRST,
    "architect": _GLOBAL_ORDER,
    "architecture-reviewer": _GLOBAL_ORDER,
    "task-preparer": _GLOBAL_ORDER,
    "task-runner": _CODEX_FIRST,
    "drift-analyzer": _CODEX_FIRST,
    "po-emulator": ("claude", "gemini", "codex"),
    "create-orchestrator": _GEMINI_FIRST,
    "artist": _GEMINI_FIRST,
    "frontender": _GEMINI_FIRST,
    "integrator": _CODEX_FIRST,
}
_KNOWN_CANONICAL_ROLES = frozenset(role.value for role in JobRole)


def _order_for(role: str | None, todo_kind: str | None) -> tuple[tuple[str, ...], AgentDispatchReason]:
    if role == "prepare-orchestrator":
        if todo_kind == TODO_KIND_FEATURE:
            return _GLOBAL_ORDER, AgentDispatchReason.ROLE_PREFERENCE
        if todo_kind in {TODO_KIND_CHANGE, TODO_KIND_BUG}:
            return _CODEX_FIRST, AgentDispatchReason.ROLE_PREFERENCE
        return _GLOBAL_ORDER, AgentDispatchReason.GLOBAL_UNMAPPED_ROLE
    if role is None:
        return _GLOBAL_ORDER, AgentDispatchReason.GLOBAL_UNMAPPED_ROLE
    order = _ROLE_ORDERS.get(role)
    if order is None and role in _KNOWN_CANONICAL_ROLES:
        return _GLOBAL_ORDER, AgentDispatchReason.KNOWN_ROLE_POLICY_DEFECT
    if order is None:
        return _GLOBAL_ORDER, AgentDispatchReason.GLOBAL_UNMAPPED_ROLE
    return order, AgentDispatchReason.ROLE_PREFERENCE


def _configured_enabled(agent: str) -> bool:
    entry = config.agents.get(agent)
    return entry is not None and entry.enabled


async def _is_available(agent: str) -> bool:
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
        return True
    return availability.get("status") == "available" and bool(availability.get("available"))


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
        if not await _is_available(fixed_agent):
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
        if await _is_available(preferred_agent):
            return AgentDispatchDecision(agent=preferred_agent, reason=AgentDispatchReason.MANUAL_PREFERENCE)

    order, reason = _order_for(role, todo_kind)
    eligible = [agent for agent in order if _configured_enabled(agent) and await _is_available(agent)]
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

    fallback = (
        AgentDispatchReason.MANUAL_PREFERENCE_UNAVAILABLE if mode is AgentDispatchMode.MANUAL_PREFERENCE else None
    )
    if fallback is None and eligible[0] != order[0]:
        fallback = AgentDispatchReason.DETERMINISTIC_INELIGIBILITY
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
) -> None:
    """Emit the single privacy-safe routing record family."""
    logger.info(
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
