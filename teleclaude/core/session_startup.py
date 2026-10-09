"""Startup handover: the durable record of a session's first startup input.

An acknowledged session start keeps its launch intent and its progress together
so a replacement of the service neither loses the start nor repeats it. The
first startup input is the agent launch for a start without an initial message,
and the initial message for a start that carries one. Progress is marked at the
first act that places input in the child's pane, so an interruption before the
mark leaves the step resumable and an interruption after it never repeats the
step: a launch is not launched again, and a submission is reported as uncertain.

This module owns the state vocabulary, the rule for which state each startup
step moves to, the recovery decision per state, and the stored form of the
launch intent. Storage lives in the database layer; effects live in the daemon.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from teleclaude.core.models import JsonDict, SessionLaunchIntent, SessionLaunchKind
from teleclaude.core.models._session import FIELD_CALLER_HEADER

STARTUP_RESOLVED_MODEL_FLAGS_FIELD = "resolved_model_flags"
STARTUP_BOOTSTRAP_TASK_LABEL_TEMPLATE = "session_bootstrap:{session_id}"
STARTUP_UNCERTAIN_OCCURRENCE_TEMPLATE = "startup-delivery-uncertain:{session_id}"
STARTUP_STATE_NOT_UNFINISHED_TEMPLATE = "startup state {state} has no recovery: it is finished"
STARTUP_MARK_REFUSED_TEMPLATE = "startup handover for session {session_id} refused the progress mark {target}"


class StartupHandoverState(StrEnum):
    """Progress of a session's startup, from acceptance to its terminal outcome."""

    ACCEPTED = "accepted"
    AGENT_LAUNCHED = "agent_launched"
    SUBMITTING = "submitting"
    REPORTING_UNCERTAIN = "reporting_uncertain"
    HANDED_OVER = "handed_over"
    FAILED = "failed"
    DELIVERY_UNCERTAIN = "delivery_uncertain"


TERMINAL_STARTUP_STATES: frozenset[StartupHandoverState] = frozenset(
    {
        StartupHandoverState.HANDED_OVER,
        StartupHandoverState.FAILED,
        StartupHandoverState.DELIVERY_UNCERTAIN,
    }
)
UNFINISHED_STARTUP_STATES: frozenset[StartupHandoverState] = frozenset(StartupHandoverState) - TERMINAL_STARTUP_STATES

# States in which a running bootstrap still owns the outcome of its startup.
BOOTSTRAP_OWNED_STATES: frozenset[StartupHandoverState] = frozenset(
    {
        StartupHandoverState.ACCEPTED,
        StartupHandoverState.AGENT_LAUNCHED,
        StartupHandoverState.SUBMITTING,
    }
)


class StartupRecovery(StrEnum):
    """What a replacement service does with an unfinished startup."""

    RESUME = "resume"
    REPORT_INTERRUPTED_SUBMISSION = "report_interrupted_submission"
    REPORT_OWED_NOTICE = "report_owed_notice"


_RECOVERY_BY_STATE: dict[StartupHandoverState, StartupRecovery] = {
    StartupHandoverState.ACCEPTED: StartupRecovery.RESUME,
    StartupHandoverState.AGENT_LAUNCHED: StartupRecovery.RESUME,
    StartupHandoverState.SUBMITTING: StartupRecovery.REPORT_INTERRUPTED_SUBMISSION,
    StartupHandoverState.REPORTING_UNCERTAIN: StartupRecovery.REPORT_OWED_NOTICE,
}


class StartupMarkRefusedError(RuntimeError):
    """A progress mark could not be taken, so the input effect it guards must not happen."""

    def __init__(self, session_id: str, target: StartupHandoverState) -> None:
        super().__init__(STARTUP_MARK_REFUSED_TEMPLATE.format(session_id=session_id, target=target.value))


@dataclass(frozen=True)
class StartupHandover:
    """One session's startup intent together with its progress."""

    session_id: str
    intent: SessionLaunchIntent
    state: StartupHandoverState


def encode_startup_intent(intent: SessionLaunchIntent) -> str:
    """Serialize a launch intent for storage, including the model decided at acceptance.

    The wire form omits the resolved model flags because a remote target resolves
    its own availability; the stored form keeps them so a resumed launch uses the
    model the acknowledged start was accepted with. The stored form omits the
    caller header, which launch resolution has already applied to the startup
    message before the handover is recorded.
    """
    payload: JsonDict = {**intent.to_dict(), STARTUP_RESOLVED_MODEL_FLAGS_FIELD: intent.resolved_model_flags}
    del payload[FIELD_CALLER_HEADER]
    return json.dumps(payload)


def decode_startup_intent(stored: str) -> SessionLaunchIntent:
    """Restore a launch intent from its stored form."""
    payload = cast(JsonDict, json.loads(stored))
    intent = SessionLaunchIntent.from_dict(payload)
    intent.resolved_model_flags = cast(str | None, payload.get(STARTUP_RESOLVED_MODEL_FLAGS_FIELD))
    return intent


def launch_dispatch_target(intent: SessionLaunchIntent, *, message_follows_launch: bool) -> StartupHandoverState:
    """Return the state the launcher command's dispatch moves an accepted startup to.

    Only a start whose initial message is delivered after the agent is up leaves
    its first startup input pending past the launch. For every other start the
    launch is that input.
    """
    if intent.kind is SessionLaunchKind.AGENT_THEN_MESSAGE and message_follows_launch:
        return StartupHandoverState.AGENT_LAUNCHED
    return StartupHandoverState.SUBMITTING


def launch_is_owed(state: StartupHandoverState) -> bool:
    """Return whether the agent has not yet been launched in the child's pane."""
    return state is StartupHandoverState.ACCEPTED


def recovery_for(state: StartupHandoverState) -> StartupRecovery:
    """Return the recovery decision for an unfinished startup state."""
    recovery = _RECOVERY_BY_STATE.get(state)
    if recovery is None:
        raise ValueError(STARTUP_STATE_NOT_UNFINISHED_TEMPLATE.format(state=state.value))
    return recovery


def bootstrap_task_label(session_id: str) -> str:
    """Name the background task that bootstraps a session's resources, fresh or resumed."""
    return STARTUP_BOOTSTRAP_TASK_LABEL_TEMPLATE.format(session_id=session_id)


def uncertain_delivery_occurrence_key(session_id: str) -> str:
    """Return the one occurrence key of a startup's uncertain-delivery notice.

    Deriving it from the session alone makes a retried report reuse the control
    payload already recorded for a watcher instead of waking it twice.
    """
    return STARTUP_UNCERTAIN_OCCURRENCE_TEMPLATE.format(session_id=session_id)
