"""Close a drain's daemon window at a registered checkout-tip boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.checkpoint_model import ActivationRange
from teleclaude.constants import RESTART_MAINTENANCE_ACTION_ID
from teleclaude.core.integration._maintenance_records import (
    MaintenanceActivation,
    MaintenanceRecordState,
    maintenance_activation_registration_lock,
    read_activation_registration,
    read_records,
)
from teleclaude.core.integration.daemon_window import (
    WindowCloseResult,
    close_window,
    open_window,
    record_window_failure,
)
from teleclaude.git import Repo

logger = get_logger(__name__)

_WINDOW_CLOSED_EVENT = "post_commit_maintenance_window_closed"
_WINDOW_TIP_REGISTERED_EVENT = "post_commit_maintenance_window_tip_registered"
_WINDOW_START_OVERTAKEN_EVENT = "post_commit_maintenance_window_start_overtaken"
_WINDOW_TIP_REGISTRATION_REFUSED_EVENT = "post_commit_maintenance_window_tip_registration_refused"

type RegisterTip = Callable[[str], tuple[ActivationRange, tuple[str, ...] | None, str | None]]
type SettleWindow = Callable[[Path, list[MaintenanceActivation], WindowCloseResult], None]


class WindowBoundaryDecision(StrEnum):
    """What the drain does after reaching its empty-record close boundary."""

    CONTINUE = "continue"
    COMPLETE = "complete"
    REFUSED = "refused"


@dataclass(frozen=True)
class WindowBoundaryResult:
    """The boundary decision and whether a successfully opened window remains stopped."""

    decision: WindowBoundaryDecision
    window_open: bool


def close_drain_window(
    root: Path,
    repository: Repo,
    activations: list[MaintenanceActivation],
    register_tip: RegisterTip,
    settle_window: SettleWindow,
) -> WindowBoundaryResult:
    """Drain newly actionable work, register an unrecorded tip, and close under registration exclusion."""
    while True:
        unregistered_tip: str | None = None
        with maintenance_activation_registration_lock(root):
            records = read_records(root)
            if any(
                record.state in (MaintenanceRecordState.PENDING, MaintenanceRecordState.RUNNING) for record in records
            ):
                return WindowBoundaryResult(WindowBoundaryDecision.CONTINUE, True)

            start_commit = repository.head.commit.hexsha
            if read_activation_registration(root, start_commit) is None:
                unregistered_tip = start_commit
                close_result = None
                tip_after_close = None
            else:
                close_result = close_window(
                    root,
                    start_commit,
                    tuple(activations),
                    current_tip=lambda: repository.head.commit.hexsha,
                )
                tip_after_close = repository.head.commit.hexsha
                if not close_result.verified:
                    settle_window(root, activations, close_result)
                    logger.info(
                        _WINDOW_CLOSED_EVENT,
                        activations=tuple(_activation_fields(item) for item in activations),
                        verified=False,
                        reason=close_result.reason,
                    )
                    return WindowBoundaryResult(WindowBoundaryDecision.REFUSED, False)
                if tip_after_close == start_commit:
                    settle_window(root, activations, close_result)
                    logger.info(
                        _WINDOW_CLOSED_EVENT,
                        activations=tuple(_activation_fields(item) for item in activations),
                        verified=close_result.verified,
                        reason=close_result.reason,
                    )
                    activations.clear()
                    return WindowBoundaryResult(WindowBoundaryDecision.COMPLETE, False)

        if close_result is None:
            if unregistered_tip is None:
                continue
            activation_range, action_ids, refusal = register_tip(unregistered_tip)
            if refusal is not None:
                _refuse_tip_registration(root, activation_range, refusal, activations, settle_window)
                return WindowBoundaryResult(WindowBoundaryDecision.REFUSED, True)
            logger.info(
                _WINDOW_TIP_REGISTERED_EVENT,
                **_activation_fields(activation_range),
                action_ids=action_ids or (),
                covered_activations=tuple(_activation_fields(item) for item in activations),
            )
            continue

        if tip_after_close is None:
            continue
        logger.warning(
            _WINDOW_START_OVERTAKEN_EVENT,
            start_commit=start_commit,
            checkout_tip=tip_after_close,
            covered_activations=tuple(_activation_fields(item) for item in activations),
        )
        activation_range, action_ids, refusal = register_tip(tip_after_close)
        if refusal is not None:
            reopened = open_window(root, activation_range)
            if reopened.opened:
                record_window_failure(root, refusal)
                with maintenance_activation_registration_lock(root):
                    settle_window(
                        root,
                        activations,
                        WindowCloseResult(verified=False, reason=refusal),
                    )
            logger.error(
                _WINDOW_TIP_REGISTRATION_REFUSED_EVENT,
                **_activation_fields(activation_range),
                reason=refusal,
                daemon_stopped=reopened.opened,
            )
            return WindowBoundaryResult(WindowBoundaryDecision.REFUSED, reopened.opened)

        if RESTART_MAINTENANCE_ACTION_ID in (action_ids or ()):
            return WindowBoundaryResult(WindowBoundaryDecision.CONTINUE, False)
        with maintenance_activation_registration_lock(root):
            settle_window(root, activations, close_result)
        activations.clear()
        return WindowBoundaryResult(WindowBoundaryDecision.CONTINUE, False)


def refuse_unregistered_tip(
    root: Path,
    activation_range: ActivationRange,
    reason: str,
    activations: list[MaintenanceActivation],
    settle_window: SettleWindow,
) -> None:
    """Keep a refused pre-start registration stopped and fail every covered replacement record."""
    record_window_failure(root, reason)
    with maintenance_activation_registration_lock(root):
        settle_window(root, activations, WindowCloseResult(verified=False, reason=reason))
    logger.error(
        _WINDOW_TIP_REGISTRATION_REFUSED_EVENT,
        **_activation_fields(activation_range),
        reason=reason,
        covered_activations=tuple(_activation_fields(item) for item in activations),
        daemon_stopped=True,
    )


def _refuse_tip_registration(
    root: Path,
    activation_range: ActivationRange,
    reason: str,
    activations: list[MaintenanceActivation],
    settle_window: SettleWindow,
) -> None:
    """Record a refusal while the daemon is already stopped at the pre-start boundary."""
    refuse_unregistered_tip(root, activation_range, reason, activations, settle_window)


def _activation_fields(activation: MaintenanceActivation) -> dict[str, str | None]:
    """Serialize the commit range or event identity in structured window records."""
    return asdict(activation)
