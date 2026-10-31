"""Settlement of canonical-main commit activations: which activations settled, and the announcement each owes.

An activation settles once every action it owes has a terminal outcome, or when it is registered owing none.
Settling records a durable pending announcement beside the maintenance records; delivery publishes it as an
event of the ``teleclaude.maintenance.activation`` family and retires it only after the producer accepted it.
An announcement that cannot be delivered stays recorded for the next delivery attempt, and the event id derives
from the project, the activation and its outcome, so a repeated delivery of one settlement is recognized
downstream and two projects activating one revision never share an id.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.checkpoint_model import ActivationRange
from teleclaude.core.integration._maintenance_records import (
    FailedAction,
    MaintenanceActionRecord,
    MaintenanceActivation,
    MaintenanceRecordState,
    PendingSettlement,
    SettlementOutcome,
    read_pending_settlements,
    remove_pending_settlement,
    write_pending_settlement,
)
from teleclaude.events.envelope import EventHomeRef, EventLevel, occurrence_id
from teleclaude.events.envelope_facts import home_for_project_path
from teleclaude.events.producer import loop_local_producer
from teleclaude.events.references import CommitRef
from teleclaude.events.schemas.maintenance import (
    FailedMaintenanceAction,
    MaintenanceActivationData,
    MaintenanceActivationFailed,
    MaintenanceActivationSucceeded,
)
from teleclaude.events.wire import LegacyFacts

logger = get_logger(__name__)

type ReplayCommand = Callable[[MaintenanceActivation, str], str]

_SETTLEMENT_RECORDED_EVENT = "post_commit_maintenance_settlement_recorded"
_SETTLEMENT_DELIVERED_EVENT = "post_commit_maintenance_settlement_delivered"
_SETTLEMENT_UNDELIVERED_EVENT = "post_commit_maintenance_settlement_undelivered"
_SETTLEMENT_UNROUTABLE_EVENT = "post_commit_maintenance_settlement_unroutable"
_COMMIT_IDENTITY: Final = "{project}/{sha}"
_PRODUCER: Final = "post-commit-maintenance"
_DOMAIN: Final = "maintenance"
_SETTLED_DESCRIPTION: Final = "Canonical-main activation {sha} settled: {outcome}"
_OPEN_STATES: Final = (MaintenanceRecordState.PENDING, MaintenanceRecordState.RUNNING)


@dataclass
class SettlementWatch:
    """Tracks the commit activations a drain has seen owing work and records each one's settlement.

    An activation is watched from the moment a read shows it still owing an action, so a stale failure from an
    earlier drain is never announced again. It settles when no action of it is pending or running: it failed
    when a failure stays recorded, otherwise it succeeded.
    """

    replay_command: ReplayCommand
    watched: set[ActivationRange] = field(default_factory=set)

    def record_settled(self, project_root: Path, records: tuple[MaintenanceActionRecord, ...]) -> None:
        """Record the announcement of every watched activation whose last owed action reached a terminal outcome."""
        by_activation: dict[ActivationRange, list[MaintenanceActionRecord]] = {}
        for record in records:
            if isinstance(record.activation, ActivationRange):
                by_activation.setdefault(record.activation, []).append(record)
        for activation, held in by_activation.items():
            if any(record.state in _OPEN_STATES for record in held):
                self.watched.add(activation)
        for activation in tuple(self.watched):
            held = by_activation.get(activation, [])
            if any(record.state in _OPEN_STATES for record in held):
                continue
            failed = tuple(
                FailedAction(record.action_id, self.replay_command(record.activation, record.action_id))
                for record in sorted(held, key=lambda record: record.action_id)
                if record.state is MaintenanceRecordState.FAILED
            )
            record_settlement(
                project_root,
                PendingSettlement(
                    activation=activation,
                    outcome=SettlementOutcome.FAILED if failed else SettlementOutcome.SUCCEEDED,
                    failed_actions=failed,
                ),
            )
            self.watched.discard(activation)


def record_settlement(project_root: Path, settlement: PendingSettlement) -> None:
    """Hold a settled activation's announcement durably until it is delivered."""
    write_pending_settlement(project_root, settlement)
    logger.info(
        _SETTLEMENT_RECORDED_EVENT,
        project_root=str(project_root),
        after_sha=settlement.activation.after_sha,
        outcome=settlement.outcome,
        failed_action_ids=tuple(failed.action_id for failed in settlement.failed_actions),
    )


def deliver_pending_settlements(project_root: Path) -> None:
    """Publish every held settlement of the checkout's project; one that cannot be published stays held."""
    pending = read_pending_settlements(project_root)
    if not pending:
        return
    home = home_for_project_path(project_root)
    if not isinstance(home, EventHomeRef):
        for settlement in pending:
            remove_pending_settlement(project_root, settlement)
        logger.info(_SETTLEMENT_UNROUTABLE_EVENT, project_root=str(project_root), settlement_count=len(pending))
        return
    try:
        asyncio.run(_deliver(project_root, home, pending))
    except Exception:  # supervision boundary: an unreachable stream leaves the settlement held for the next delivery
        logger.warning(
            _SETTLEMENT_UNDELIVERED_EVENT,
            project_root=str(project_root),
            settlement_count=len(pending),
            exc_info=True,
        )


async def _deliver(project_root: Path, home: EventHomeRef, pending: tuple[PendingSettlement, ...]) -> None:
    async with loop_local_producer() as producer:
        for settlement in pending:
            await producer.emit(*_announcement(home, settlement))
            remove_pending_settlement(project_root, settlement)
            logger.info(
                _SETTLEMENT_DELIVERED_EVENT,
                project=home.instance,
                after_sha=settlement.activation.after_sha,
                outcome=settlement.outcome,
            )


def _announcement(
    home: EventHomeRef, settlement: PendingSettlement
) -> tuple[MaintenanceActivationSucceeded | MaintenanceActivationFailed, LegacyFacts]:
    """The event a settlement announces, and the notification-path facts older computers read beside it."""
    failed = settlement.outcome is SettlementOutcome.FAILED
    event_class = MaintenanceActivationFailed if failed else MaintenanceActivationSucceeded
    activation = settlement.activation
    event = event_class(
        id=occurrence_id(home.instance, activation.after_sha, event_class.type_name()),
        subject=CommitRef(_COMMIT_IDENTITY.format(project=home.instance, sha=activation.after_sha)),
        home=home,
        data=MaintenanceActivationData(
            project=home.instance,
            before_revision=activation.before_sha,
            after_revision=activation.after_sha,
            failed_actions=[
                FailedMaintenanceAction(action_id=item.action_id, replay_command=item.replay_command)
                for item in settlement.failed_actions
            ],
        ),
    )
    legacy = LegacyFacts(
        producer=_PRODUCER,
        level=EventLevel.OPERATIONAL if failed else EventLevel.WORKFLOW,
        domain=_DOMAIN,
        entity=home.instance,
        description=_SETTLED_DESCRIPTION.format(sha=activation.after_sha, outcome=settlement.outcome.value),
    )
    return event, legacy
