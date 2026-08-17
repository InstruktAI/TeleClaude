"""Prescribed reminder profile registry and formatters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .models import (
    PrescribedReminderSlug,
    ReminderEventAnchor,
    ReminderSchedule,
    ReminderSetRequest,
)

_GOAL_DRIVE_INTENT = (
    "Reassess whether the current work remains aligned with {goal}. "
    "If aligned, continue; otherwise correct course or stop."
)
_HALT_TO_RESPOND_INTENT = (
    "Resume the work interrupted to answer the non-human input, unless intervening input made that work stale."
)
_SESSION_DEPARTURE_INTENT = (
    "End this session only if its work remains complete, no later input or obligation requires attention, "
    "and no wider owner must retain it."
)
_ORCHESTRATION_WATCH_INTENT = (
    "Re-enter {machine} for {target_slug} after checking for intervening human input. "
    "If the worker is active, inspect only new output; if it is idle, advance the state machine."
)
_COORDINATOR_SWEEP_INTENT = (
    "Reassess the live project fleet from current source truth. Restore missing ownership or attention, "
    "record only material findings, and carry only human-owned need."
)
_INTEGRATOR_MAIN_CLEARANCE_INTENT = (
    "Recheck whether repo-root main is clear without touching another session's work. "
    "If clear, resume integration; otherwise continue the prescribed wait and escalation discipline."
)
_INTEGRATOR_CANDIDATE_SETTLEDNESS_INTENT = (
    "Recheck the integration queue after its caller-owned settledness interval. "
    "If a candidate is ready, continue the drain; otherwise follow the integration procedure's queue-empty outcome."
)
_DEFAULT_GOAL_DRIVE_SECONDS = 300.0
_DEFAULT_ORCHESTRATION_SECONDS = 300.0
_DEFAULT_COORDINATOR_SECONDS = 60.0
_DEFAULT_MAIN_CLEARANCE_SECONDS = 150.0
_DEFAULT_SETTLEDNESS_SECONDS = 30.0


@dataclass(frozen=True)
class PrescribedReminderInput:
    """Profile-specific varying inputs accepted by the registry."""

    goal: str | None = None
    machine: str | None = None
    target_slug: str | None = None
    after_seconds: float | None = None


ProfileFormatter = Callable[[str, PrescribedReminderInput], ReminderSetRequest]


@dataclass(frozen=True)
class PrescribedReminderProfile:
    """One prescribed formatter and the only public inputs it accepts."""

    formatter: ProfileFormatter
    accepted_parameters: frozenset[str]


def _required(value: str | None, field: str) -> str:
    if value is None or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _required_after(value: float | None) -> float:
    if value is None:
        raise ValueError("after_seconds is required")
    return value


def _goal_drive(session_id: str, inputs: PrescribedReminderInput) -> ReminderSetRequest:
    goal = _required(inputs.goal, "goal")
    slug = PrescribedReminderSlug.GOAL_DRIVE
    return ReminderSetRequest(
        session_id=session_id,
        slug=slug.value,
        profile=slug,
        intent=_GOAL_DRIVE_INTENT.format(goal=goal),
        schedule=ReminderSchedule.relative(after_seconds=_DEFAULT_GOAL_DRIVE_SECONDS, repeat=True),
    )


def _halt_to_respond(session_id: str, inputs: PrescribedReminderInput) -> ReminderSetRequest:
    _ = inputs
    slug = PrescribedReminderSlug.HALT_TO_RESPOND
    return ReminderSetRequest(
        session_id=session_id,
        slug=slug.value,
        profile=slug,
        intent=_HALT_TO_RESPOND_INTENT,
        schedule=ReminderSchedule.on_event(ReminderEventAnchor.AGENT_STOP),
    )


def _session_departure(session_id: str, inputs: PrescribedReminderInput) -> ReminderSetRequest:
    slug = PrescribedReminderSlug.SESSION_DEPARTURE
    return ReminderSetRequest(
        session_id=session_id,
        slug=slug.value,
        profile=slug,
        intent=_SESSION_DEPARTURE_INTENT,
        schedule=ReminderSchedule.relative(after_seconds=_required_after(inputs.after_seconds), repeat=False),
    )


def _orchestration_watch(session_id: str, inputs: PrescribedReminderInput) -> ReminderSetRequest:
    machine = _required(inputs.machine, "machine")
    target_slug = _required(inputs.target_slug, "target_slug")
    interval = inputs.after_seconds or _DEFAULT_ORCHESTRATION_SECONDS
    slug = PrescribedReminderSlug.ORCHESTRATION_WATCH
    return ReminderSetRequest(
        session_id=session_id,
        slug=slug.value,
        profile=slug,
        intent=_ORCHESTRATION_WATCH_INTENT.format(machine=machine, target_slug=target_slug),
        schedule=ReminderSchedule.relative(after_seconds=interval, repeat=True),
    )


def _coordinator_sweep(session_id: str, inputs: PrescribedReminderInput) -> ReminderSetRequest:
    interval = inputs.after_seconds or _DEFAULT_COORDINATOR_SECONDS
    slug = PrescribedReminderSlug.COORDINATOR_SWEEP
    return ReminderSetRequest(
        session_id=session_id,
        slug=slug.value,
        profile=slug,
        intent=_COORDINATOR_SWEEP_INTENT,
        schedule=ReminderSchedule.relative(after_seconds=interval, repeat=True),
    )


def _integrator_main_clearance(session_id: str, inputs: PrescribedReminderInput) -> ReminderSetRequest:
    interval = inputs.after_seconds or _DEFAULT_MAIN_CLEARANCE_SECONDS
    slug = PrescribedReminderSlug.INTEGRATOR_MAIN_CLEARANCE
    return ReminderSetRequest(
        session_id=session_id,
        slug=slug.value,
        profile=slug,
        intent=_INTEGRATOR_MAIN_CLEARANCE_INTENT,
        schedule=ReminderSchedule.relative(after_seconds=interval, repeat=True),
    )


def _integrator_candidate_settledness(session_id: str, inputs: PrescribedReminderInput) -> ReminderSetRequest:
    interval = inputs.after_seconds or _DEFAULT_SETTLEDNESS_SECONDS
    slug = PrescribedReminderSlug.INTEGRATOR_CANDIDATE_SETTLEDNESS
    return ReminderSetRequest(
        session_id=session_id,
        slug=slug.value,
        profile=slug,
        intent=_INTEGRATOR_CANDIDATE_SETTLEDNESS_INTENT,
        schedule=ReminderSchedule.relative(after_seconds=interval, repeat=False),
    )


PROFILE_REGISTRY: dict[PrescribedReminderSlug, PrescribedReminderProfile] = {
    PrescribedReminderSlug.GOAL_DRIVE: PrescribedReminderProfile(_goal_drive, frozenset({"goal"})),
    PrescribedReminderSlug.HALT_TO_RESPOND: PrescribedReminderProfile(_halt_to_respond, frozenset()),
    PrescribedReminderSlug.SESSION_DEPARTURE: PrescribedReminderProfile(_session_departure, frozenset({"after"})),
    PrescribedReminderSlug.ORCHESTRATION_WATCH: PrescribedReminderProfile(
        _orchestration_watch, frozenset({"machine", "target_slug", "after"})
    ),
    PrescribedReminderSlug.COORDINATOR_SWEEP: PrescribedReminderProfile(_coordinator_sweep, frozenset({"after"})),
    PrescribedReminderSlug.INTEGRATOR_MAIN_CLEARANCE: PrescribedReminderProfile(
        _integrator_main_clearance, frozenset({"after"})
    ),
    PrescribedReminderSlug.INTEGRATOR_CANDIDATE_SETTLEDNESS: PrescribedReminderProfile(
        _integrator_candidate_settledness, frozenset({"after"})
    ),
}


def format_prescribed_reminder(
    *, session_id: str, slug: PrescribedReminderSlug, inputs: PrescribedReminderInput
) -> ReminderSetRequest:
    """Resolve one reserved slug through its statically declared formatter."""
    return PROFILE_REGISTRY[slug].formatter(session_id, inputs)


def accepted_prescribed_parameters(slug: PrescribedReminderSlug) -> frozenset[str]:
    """Return the profile-owned public parameter names for an API adapter."""
    return PROFILE_REGISTRY[slug].accepted_parameters
