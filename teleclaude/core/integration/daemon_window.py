"""Open and close the controlled daemon window used by maintenance runs."""

from __future__ import annotations

import asyncio
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.api_models_health import HealthDTO
from teleclaude.cli.api_client import TelecAPIClient
from teleclaude.constants import API_SOCKET_PATH
from teleclaude.core.integration._maintenance_records import (
    MaintenanceActivation,
    WindowFailure,
    clear_window_failure,
    maintenance_directory,
    read_window_failure,
    write_window_failure,
)
from teleclaude.core.integration.maintenance_output import secret_output_masker
from teleclaude.core.shutdown_drain import PREPARATION_OBSERVATION_BUDGET_SECONDS, DrainPhase
from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo
from teleclaude.runtime.command_runner import CommandResult, run_process_group_command
from teleclaude.runtime.daemon_shutdown_control import ControlRefusal, NothingListening, read_health

logger = get_logger(__name__)

ADMISSION_WAIT_BOUND_SECONDS = 180.0
WINDOW_START_BOUND_SECONDS = 120.0
# daemon-control.sh bounds verified exit at 25 s, then its kill wait at 5 s.
_STOP_WAIT_SECONDS = 25.0
_STOP_KILL_WAIT_SECONDS = 5.0
_STOP_COMMAND_MARGIN_SECONDS = 15.0
_POLL_INTERVAL_SECONDS = 1.0
_MAKE_EXECUTABLE = "make"
_STOP_TARGET = "stop"
_START_TARGET = "start"
_STOP_OUTCOME_ARGUMENT = "STOP_OUTCOME_FILE={path}"
_STOPPED_OUTCOME = "stopped"
_STOPPED_CLEANUP_FAILURE_OUTCOME = "stopped_cleanup_failure"
_WITHHELD_DRAINING_OUTCOME = "withheld_draining"
_WITHHELD_OUTCOME = "withheld"
_WINDOW_OPEN_EVENT = "maintenance_window_opened"
_WINDOW_OPEN_REFUSED_EVENT = "maintenance_window_open_refused"
_WINDOW_PREPARATION_EXPIRED_EVENT = "maintenance_window_preparation_expired"
_WINDOW_STOP_CLEANUP_FAILED_EVENT = "maintenance_window_stop_cleanup_failed"
_WINDOW_CLOSED_EVENT = "maintenance_window_closed"
_WINDOW_FAILURE_PREFIX = "Last maintenance window failure ({recorded_at}): {reason}"
_MISSING_STOP_OUTCOME = "make stop did not record an outcome"
_START_TIMEOUT = "make start did not return within the maintenance-window bound"
_START_UNVERIFIED = "daemon did not verify healthy with admission open on checkout tip within the bound"
_CONTEXT_STOP_REFUSED = "make stop withheld the daemon stop"
_START_FAILURE_REASON = "{reason}: {output_tail}"
_OPEN_STOP_FAILURE = "requesting make stop failed: {error_kind}"
_HEALTH_READ_FAILURE = "daemon health could not be read within the window: {error_kind}"
_STOP_OUTCOME_PREFIX = "stop-outcome-"
_OUTPUT_UNAVAILABLE = "captured output unavailable"
_TEXT_ENCODING = "utf-8"


class StopOutcome(StrEnum):
    """The facts established by the service lifecycle's stop operation."""

    STOPPED = _STOPPED_OUTCOME
    STOPPED_CLEANUP_FAILURE = _STOPPED_CLEANUP_FAILURE_OUTCOME
    WITHHELD_DRAINING = _WITHHELD_DRAINING_OUTCOME
    WITHHELD = _WITHHELD_OUTCOME


@dataclass(frozen=True)
class AdmissionWait:
    """How long the daemon held accepted work before the wait ended."""

    waited_seconds: float
    bound_expired: bool


@dataclass(frozen=True)
class WindowOpenResult:
    """Whether the daemon stopped safely, and any cleanup warning from its stop."""

    opened: bool
    reason: str | None = None
    warning: str | None = None


@dataclass(frozen=True)
class WindowCloseResult:
    """Whether the daemon recovered on the current checkout tip."""

    verified: bool
    reason: str | None = None
    output_tail: str | None = None


def _must_keep_waiting(socket_path: str) -> bool:
    """Whether the daemon is open with held work, or its preparation state cannot be read."""
    try:
        preparation = read_health(socket_path).preparation
    except NothingListening:
        return False
    except ControlRefusal:
        return True
    return preparation is not None and preparation.phase is DrainPhase.OPEN and preparation.held_units > 0


def _activation_fields(activation: MaintenanceActivation) -> dict[str, str | None]:
    """Serialize one typed activation identity for structured window events."""
    return asdict(activation)


def wait_for_no_accepted_work(
    socket_path: str,
    *,
    bound_seconds: float = ADMISSION_WAIT_BOUND_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> AdmissionWait:
    """Poll until the open daemon holds no accepted work, or its observation bound expires."""
    started = clock()
    deadline = started + bound_seconds
    while _must_keep_waiting(socket_path):
        if clock() >= deadline:
            return AdmissionWait(waited_seconds=clock() - started, bound_expired=True)
        sleep(_POLL_INTERVAL_SECONDS)
    return AdmissionWait(waited_seconds=clock() - started, bound_expired=False)


def open_window(
    root: Path,
    activation: MaintenanceActivation,
) -> WindowOpenResult:
    """Wait for accepted work, then open a window only on the lifecycle's recorded stopped outcome."""
    activation_fields = _activation_fields(activation)
    wait = wait_for_no_accepted_work(API_SOCKET_PATH)
    while True:
        try:
            outcome, result = _request_stop(root)
        except OSError as error:
            reason = _OPEN_STOP_FAILURE.format(error_kind=type(error).__name__)
            record_window_failure(root, reason)
            logger.error(_WINDOW_OPEN_REFUSED_EVENT, **(activation_fields or {}), reason=reason)
            return WindowOpenResult(opened=False, reason=reason)
        if outcome in (StopOutcome.STOPPED, StopOutcome.STOPPED_CLEANUP_FAILURE):
            warning = result.output_tail if outcome is StopOutcome.STOPPED_CLEANUP_FAILURE else None
            if outcome is StopOutcome.STOPPED_CLEANUP_FAILURE:
                warning = warning or _OUTPUT_UNAVAILABLE
                logger.warning(
                    _WINDOW_STOP_CLEANUP_FAILED_EVENT,
                    **(activation_fields or {}),
                    waited_seconds=round(wait.waited_seconds, 1),
                    output_tail=warning,
                )
            logger.info(
                _WINDOW_OPEN_EVENT,
                **(activation_fields or {}),
                waited_seconds=round(wait.waited_seconds, 1),
                bound_expired=wait.bound_expired,
            )
            return WindowOpenResult(opened=True, warning=warning)
        if outcome is StopOutcome.WITHHELD_DRAINING:
            logger.warning(
                _WINDOW_PREPARATION_EXPIRED_EVENT,
                **(activation_fields or {}),
                waited_seconds=round(wait.waited_seconds, 1),
                output_tail=result.output_tail,
            )
            wait = wait_for_no_accepted_work(API_SOCKET_PATH)
            continue

        reason = result.output_tail or _CONTEXT_STOP_REFUSED
        if outcome is None:
            reason = result.output_tail or _MISSING_STOP_OUTCOME
        record_window_failure(root, reason)
        logger.error(_WINDOW_OPEN_REFUSED_EVENT, **(activation_fields or {}), reason=reason)
        return WindowOpenResult(opened=False, reason=reason)


def close_window(
    root: Path,
    start_commit: str,
    covered_activations: tuple[MaintenanceActivation, ...] = (),
    current_tip: Callable[[], str] | None = None,
) -> WindowCloseResult:
    """Start the daemon and verify its health, open admission and checkout start commit within one bound."""
    activation_fields = tuple(_activation_fields(activation) for activation in covered_activations)
    deadline = time.monotonic() + WINDOW_START_BOUND_SECONDS
    started = run_process_group_command(
        [_MAKE_EXECUTABLE, _START_TARGET],
        root,
        timeout_seconds=max(0.0, deadline - time.monotonic()),
        capture_output=secret_output_masker(root),
    )
    reason = _START_TIMEOUT if started.timed_out else (started.output_tail or _START_UNVERIFIED)
    while time.monotonic() < deadline:
        try:
            health = asyncio.run(_read_health())
        except Exception as error:
            reason = _HEALTH_READ_FAILURE.format(error_kind=type(error).__name__)
            time.sleep(_POLL_INTERVAL_SECONDS)
            continue
        preparation = health.preparation
        accepted_tip = current_tip() if current_tip is not None else start_commit
        if (
            _start_commit_matches_checkout(root, start_commit, health.start_commit, accepted_tip)
            and preparation is not None
            and preparation.phase is DrainPhase.OPEN
        ):
            clear_window_failure(root)
            logger.info(
                _WINDOW_CLOSED_EVENT,
                covered_activations=activation_fields,
                verified=True,
                start_commit=health.start_commit,
            )
            return WindowCloseResult(verified=True, output_tail=started.output_tail)
        reason = _START_UNVERIFIED
        time.sleep(_POLL_INTERVAL_SECONDS)

    if started.exit_code != 0 and started.output_tail:
        reason = _START_FAILURE_REASON.format(reason=reason, output_tail=started.output_tail)
    record_window_failure(root, reason)
    logger.error(_WINDOW_CLOSED_EVENT, covered_activations=activation_fields, verified=False, reason=reason)
    return WindowCloseResult(verified=False, reason=reason, output_tail=started.output_tail)


def _start_commit_matches_checkout(root: Path, requested: str, reported: str | None, current: str) -> bool:
    """Accept the requested tip or an intermediate commit the start raced to load on the checkout's ancestry."""
    if reported in (requested, current):
        return True
    if reported is None:
        return False
    try:
        repository = Repo(str(root))
        return repository.is_ancestor(
            repository.commit(requested), repository.commit(reported)
        ) and repository.is_ancestor(repository.commit(reported), repository.commit(current))
    except (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError, TypeError, ValueError):
        return False


async def _read_health() -> HealthDTO:
    """Read the daemon's typed health DTO using the CLI's published local API client."""
    client = TelecAPIClient()
    await client.connect()
    try:
        return await client.get_health()
    finally:
        await client.close()


def _request_stop(root: Path) -> tuple[StopOutcome | None, CommandResult]:
    """Ask the lifecycle to stop and return its recorded outcome independently of make's exit status."""
    directory = maintenance_directory(root)
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=directory, prefix=_STOP_OUTCOME_PREFIX, delete=False) as handle:
        outcome_path = Path(handle.name)
    outcome_path.unlink(missing_ok=True)
    try:
        result = run_process_group_command(
            [_MAKE_EXECUTABLE, _STOP_TARGET, _STOP_OUTCOME_ARGUMENT.format(path=outcome_path)],
            root,
            timeout_seconds=_stop_command_bound_seconds(),
            capture_output=secret_output_masker(root),
        )
        try:
            value = outcome_path.read_text(encoding=_TEXT_ENCODING).strip()
            return StopOutcome(value), result
        except (OSError, ValueError):
            return None, result
    finally:
        outcome_path.unlink(missing_ok=True)


def _stop_command_bound_seconds() -> float:
    """Cover the serving daemon's preparation budget and the lifecycle's bounded exit waits."""
    try:
        preparation = read_health(API_SOCKET_PATH).preparation
    except ControlRefusal:
        preparation = None
    preparation_budget = (
        preparation.budget_seconds if preparation is not None else PREPARATION_OBSERVATION_BUDGET_SECONDS
    )
    return preparation_budget + _STOP_WAIT_SECONDS + _STOP_KILL_WAIT_SECONDS + _STOP_COMMAND_MARGIN_SECONDS


def record_window_failure(root: Path, reason: str) -> None:
    """Persist the reason and time visible to make status until a later verified start."""
    write_window_failure(root, WindowFailure(reason=reason, recorded_at=datetime.now(UTC).isoformat()))


def print_window_failure(root: Path) -> None:
    """Print the last failed window for make status, if a failure remains recorded."""
    failure = read_window_failure(root)
    if failure is not None:
        print(_WINDOW_FAILURE_PREFIX.format(recorded_at=failure.recorded_at, reason=failure.reason))


def main() -> None:
    """Expose the retained window failure to the service status surface."""
    print_window_failure(Path.cwd())


if __name__ == "__main__":
    main()
