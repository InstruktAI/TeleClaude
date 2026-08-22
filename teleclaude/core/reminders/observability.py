"""Body-free structured reminder observations."""

from __future__ import annotations

from datetime import datetime

from instrukt_ai_logging import get_logger

from .models import (
    Reminder,
    ReminderAutoCancelOutcome,
    ReminderEntry,
    ReminderEvent,
    ReminderSubmissionResult,
    ReminderTransition,
)

logger = get_logger(__name__)

_TRANSITION_EVENT = "reminder_transition_committed"
_ADVANCED_EVENT = "reminder_occurrence_advanced"
_SLIDING_DECISION_EVENT = "reminder_sliding_decided"
_SLIDE_EVENT = "reminder_slide_committed"
_ENVELOPE_EVENT = "reminder_envelope_composed"
_AUTO_CANCEL_EVALUATED_EVENT = "reminder_autocancel_evaluated"
_SUBMISSION_EVENT = "reminder_submission_decided"
_AUTO_CANCEL_SWEEP_EVENT = "reminder_autocancel_sweep_decided"
_CORRELATION_REPLACED_EVENT = "reminder_correlation_replaced"
_CONSUMED_EVENT = "reminder_occurrence_consumed"
_MATCH_EVENT = "reminder_event_match_decided"
_QUERY_EVENT = "reminder_query_completed"
_CANCEL_EVENT = "reminder_cancel_committed"
_CLEAR_EVENT = "reminder_session_clear_committed"
_RECONCILE_EVENT = "reminder_reconciliation_completed"
_PROJECTION_DECISION_EVENT = "reminder_projection_decided"
_PROJECTION_HANDOFF_EVENT = "reminder_projection_handoff_completed"
_EXPLICIT_NOOP_MODE = "explicit_noop"


def observe_transition(entry: ReminderEntry) -> None:
    """Record a material reminder transition without its prose body."""
    logger.info(
        _TRANSITION_EVENT,
        outcome=entry.transition.value,
        owner_session_id=entry.session_id,
        slug=entry.slug,
        generation=entry.generation,
        occurrence_key=entry.occurrence_key,
        reminder_entry_id=entry.entry_id,
        profile=entry.profile.value if entry.profile is not None else None,
        recurrence=entry.schedule.recurrence.value,
        interval_seconds=entry.schedule.interval_seconds,
        sliding=entry.sliding,
        auto_cancel=entry.auto_cancel,
        next_fire_at=entry.schedule.next_fire_at.isoformat() if entry.schedule.next_fire_at else None,
        prior_generation=entry.generation - 1 if entry.transition is ReminderTransition.REPLACED else None,
        cancel_reason=entry.cancel_reason.value if entry.cancel_reason is not None else None,
    )


def observe_advanced(reminder: Reminder) -> None:
    """Record accepted recurring advancement."""
    logger.info(
        _ADVANCED_EVENT,
        outcome="accepted",
        owner_session_id=reminder.session_id,
        slug=reminder.slug,
        generation=reminder.generation,
        occurrence_key=reminder.occurrence_key,
        next_fire_at=reminder.schedule.next_fire_at.isoformat() if reminder.schedule.next_fire_at else None,
    )


def observe_sliding_decision(
    reminder: Reminder, *, observed_last_activity: datetime | None, decision_at: datetime, outcome: str
) -> None:
    """Record both branches of a sliding deadline decision."""
    logger.info(
        _SLIDING_DECISION_EVENT,
        outcome=outcome,
        owner_session_id=reminder.session_id,
        slug=reminder.slug,
        generation=reminder.generation,
        occurrence_key=reminder.occurrence_key,
        observed_next_fire_at=reminder.schedule.next_fire_at.isoformat() if reminder.schedule.next_fire_at else None,
        observed_last_activity=observed_last_activity.isoformat() if observed_last_activity else None,
        interval_seconds=reminder.schedule.interval_seconds,
        decision_at=decision_at.isoformat(),
    )


def observe_slide(reminder: Reminder, *, observed_last_activity: datetime) -> None:
    """Record a committed sliding re-anchor without creating a source entry."""
    logger.info(
        _SLIDE_EVENT,
        outcome="slid",
        owner_session_id=reminder.session_id,
        slug=reminder.slug,
        generation=reminder.generation,
        occurrence_key=reminder.occurrence_key,
        observed_last_activity=observed_last_activity.isoformat(),
        next_fire_at=reminder.schedule.next_fire_at.isoformat() if reminder.schedule.next_fire_at else None,
    )


def observe_envelope_composed(entry: ReminderEntry, *, explicit_noop: bool, auto_cancel: bool) -> None:
    """Record firing instructions without inspecting their rendered body."""
    logger.info(
        _ENVELOPE_EVENT,
        owner_session_id=entry.session_id,
        slug=entry.slug,
        generation=entry.generation,
        occurrence_key=entry.occurrence_key,
        sentinel_mode=_EXPLICIT_NOOP_MODE if explicit_noop else None,
        silent_answer_allowed=False if explicit_noop else None,
        auto_cancel=auto_cancel,
        consequence_included=auto_cancel,
    )


def observe_submission(entry: ReminderEntry, submission: ReminderSubmissionResult) -> None:
    """Record accepted submission and whether a row identity was recovered."""
    logger.info(
        _SUBMISSION_EVENT,
        outcome="accepted",
        owner_session_id=entry.session_id,
        slug=entry.slug,
        generation=entry.generation,
        occurrence_key=entry.occurrence_key,
        recurrence=entry.schedule.recurrence.value,
        auto_cancel=entry.auto_cancel,
        acceptance_path=submission.acceptance_path.value,
        inbound_queue_id=submission.inbound_queue_id,
    )


def observe_correlation_replaced(
    entry: ReminderEntry, *, superseded_inbound_queue_id: int, inbound_queue_id: int
) -> None:
    """Record the ruled per-slug replacement of one outstanding correlation."""
    logger.info(
        _CORRELATION_REPLACED_EVENT,
        owner_session_id=entry.session_id,
        slug=entry.slug,
        generation=entry.generation,
        occurrence_key=entry.occurrence_key,
        superseded_inbound_queue_id=superseded_inbound_queue_id,
        inbound_queue_id=inbound_queue_id,
    )


def observe_consumed(entry: ReminderEntry) -> None:
    """Record accepted consumption of a one-shot occurrence."""
    logger.info(
        _CONSUMED_EVENT,
        outcome="accepted",
        owner_session_id=entry.session_id,
        slug=entry.slug,
        generation=entry.generation,
        occurrence_key=entry.occurrence_key,
    )


def observe_auto_cancel_evaluation(
    reminder: Reminder,
    *,
    outcome: ReminderAutoCancelOutcome,
) -> None:
    """Record one pending firing-answer evaluation without transcript content."""
    logger.info(
        _AUTO_CANCEL_EVALUATED_EVENT,
        outcome=outcome.value,
        owner_session_id=reminder.session_id,
        slug=reminder.slug,
        generation=reminder.generation,
        occurrence_key=reminder.pending_answer_occurrence_key,
        inbound_queue_id=reminder.pending_answer_inbound_id,
    )


def observe_auto_cancel_sweep(event: ReminderEvent, *, considered: list[Reminder], correlated: list[Reminder]) -> None:
    """Record every stop-time auto-cancel eligibility sweep, including an empty one."""
    logger.info(
        _AUTO_CANCEL_SWEEP_EVENT,
        outcome="swept",
        owner_session_id=event.session_id,
        agent_event_id=event.event_id,
        considered_count=len(considered),
        correlated_count=len(correlated),
        correlated_slugs=[reminder.slug for reminder in correlated],
    )


def observe_event_match(event: ReminderEvent, reminder: Reminder, *, matched: bool) -> None:
    """Record a typed event predicate decision without creating domain work."""
    logger.info(
        _MATCH_EVENT,
        outcome="matched" if matched else "not_matched",
        owner_session_id=reminder.session_id,
        slug=reminder.slug,
        generation=reminder.generation,
        agent_event_id=event.event_id,
        agent_event_type=event.anchor.value,
    )


def observe_query(session_id: str, *, reminders: list[Reminder]) -> None:
    """Record a caller-scoped reminder query."""
    logger.info(
        _QUERY_EVENT,
        outcome="success",
        owner_session_id=session_id,
        count=len(reminders),
        aggregate_identities=[f"{reminder.session_id}:{reminder.slug}" for reminder in reminders],
    )


def observe_cancel(
    session_id: str,
    *,
    slug: str | None,
    entries: list[ReminderEntry],
    transaction_id: str,
) -> None:
    """Record an idempotent cancellation result."""
    logger.info(
        _CANCEL_EVENT,
        outcome="success" if entries else "already_absent",
        reason="owner_requested",
        owner_session_id=session_id,
        slug=slug,
        count=len(entries),
        transaction_id=transaction_id,
        generations=[entry.generation for entry in entries],
        occurrence_keys=[entry.occurrence_key for entry in entries],
    )


def observe_clear(session_id: str, *, count: int, operation_id: str) -> None:
    """Record ended-session cleanup without creating a reminder entry."""
    logger.info(_CLEAR_EVENT, outcome="cleanup", owner_session_id=session_id, count=count, operation_id=operation_id)


def observe_reconciliation(*, future_count: int, overdue_count: int) -> None:
    """Record scheduler restart reconciliation counts."""
    logger.info(_RECONCILE_EVENT, outcome="success", future_count=future_count, overdue_count=overdue_count)


def observe_projection_decision(
    entry: ReminderEntry, *, consumer: str, outcome: str, reason: str, projection_pass_id: str
) -> None:
    """Record a body-free eligibility decision for one consumer cursor."""
    logger.info(
        _PROJECTION_DECISION_EVENT,
        outcome=outcome,
        owner_session_id=entry.session_id,
        reminder_entry_id=entry.entry_id,
        ordering_key=f"{entry.occurred_at.isoformat()}:reminder:{entry.entry_id}",
        recipient_lane=consumer,
        reason=reason,
        projection_pass_id=projection_pass_id,
    )


def observe_projection_handoff(entry: ReminderEntry, *, consumer: str, projection_pass_id: str) -> None:
    """Record successful handoff and cursor settlement without reminder prose."""
    logger.info(
        _PROJECTION_HANDOFF_EVENT,
        outcome="success",
        owner_session_id=entry.session_id,
        reminder_entry_id=entry.entry_id,
        ordering_key=f"{entry.occurred_at.isoformat()}:reminder:{entry.entry_id}",
        recipient_lane=consumer,
        projection_pass_id=projection_pass_id,
    )
