"""The daemon stop, start and health verification that the install act drives."""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.api_models_health import HealthDTO
from teleclaude.cli.api_client import TelecAPIClient
from teleclaude.constants import API_SOCKET_PATH
from teleclaude.core.integration.maintenance_output import secret_output_masker
from teleclaude.core.shutdown_drain import PREPARATION_OBSERVATION_BUDGET_SECONDS, DrainPhase
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
_STOP_OUTCOME_VARIABLE = "STOP_OUTCOME_FILE"
_LIFECYCLE_STOP_VERB = "stop"
_LIFECYCLE_START_VERB = "start"
_STOPPED_OUTCOME = "stopped"
_STOPPED_CLEANUP_FAILURE_OUTCOME = "stopped_cleanup_failure"
_WITHHELD_DRAINING_OUTCOME = "withheld_draining"
_WITHHELD_OUTCOME = "withheld"
_WINDOW_PREPARATION_EXPIRED_EVENT = "maintenance_window_preparation_expired"
_START_TIMEOUT = "make start did not return within the maintenance-window bound"
_START_UNVERIFIED = "daemon did not verify healthy with admission open on checkout tip within the bound"
_START_FAILURE_REASON = "{reason}: {output_tail}"
_HEALTH_READ_FAILURE = "daemon health could not be read within the window: {error_kind}"
_STOP_OUTCOME_PREFIX = "stop-outcome-"
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
class Lifecycle:
    """One release's service lifecycle: where its stop and start commands run."""

    cwd: Path
    stop: tuple[str, ...]
    start: tuple[str, ...]

    def stop_environment(self, outcome_path: Path) -> Mapping[str, str]:
        """The stop command's environment; the lifecycle script reads the outcome file from it."""
        # guard: direct-env-read - allowed: child-process environment construction
        return {**os.environ, _STOP_OUTCOME_VARIABLE: str(outcome_path)}  # fmt: skip


def script_lifecycle(script: Path) -> Lifecycle:
    """A release's lifecycle through its own ``bin/daemon-control.sh``."""
    return Lifecycle(
        cwd=script.parent.parent,
        stop=(str(script), _LIFECYCLE_STOP_VERB),
        start=(str(script), _LIFECYCLE_START_VERB),
    )


@dataclass(frozen=True)
class StopAttempt:
    """The lifecycle's recorded stop outcome after the daemon held no accepted work, or why it could not run."""

    outcome: StopOutcome | None
    result: CommandResult | None
    wait: AdmissionWait
    error_kind: str | None = None


@dataclass(frozen=True)
class StartAttempt:
    """A lifecycle start and whether the daemon verified healthy, admitting work, on the revision accepted."""

    started: CommandResult
    verified: bool
    reason: str | None = None
    start_commit: str | None = None


def _must_keep_waiting(socket_path: str) -> bool:
    """Whether the daemon is open with held work, or its preparation state cannot be read."""
    try:
        preparation = read_health(socket_path).preparation
    except NothingListening:
        return False
    except ControlRefusal:
        return True
    return preparation is not None and preparation.phase is DrainPhase.OPEN and preparation.held_units > 0


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


def stop_when_quiet(lifecycle: Lifecycle, scratch: Path, log_fields: Mapping[str, object]) -> StopAttempt:
    """Wait for accepted work to settle, then ask the lifecycle to stop; a draining refusal waits and asks again."""
    wait = wait_for_no_accepted_work(API_SOCKET_PATH)
    while True:
        try:
            outcome, result = _request_stop(lifecycle, scratch)
        except OSError as error:
            return StopAttempt(outcome=None, result=None, wait=wait, error_kind=type(error).__name__)
        if outcome is StopOutcome.WITHHELD_DRAINING:
            logger.warning(
                _WINDOW_PREPARATION_EXPIRED_EVENT,
                **log_fields,
                waited_seconds=round(wait.waited_seconds, 1),
                output_tail=result.output_tail,
            )
            wait = wait_for_no_accepted_work(API_SOCKET_PATH)
            continue
        return StopAttempt(outcome=outcome, result=result, wait=wait)


def start_until_verified(lifecycle: Lifecycle, accepts: Callable[[HealthDTO], bool]) -> StartAttempt:
    """Start through the lifecycle and verify, within one bound, health, open admission and an accepted revision."""
    deadline = time.monotonic() + WINDOW_START_BOUND_SECONDS
    started = run_process_group_command(
        list(lifecycle.start),
        lifecycle.cwd,
        timeout_seconds=max(0.0, deadline - time.monotonic()),
        capture_output=secret_output_masker(lifecycle.cwd),
    )
    reason = _START_TIMEOUT if started.timed_out else (started.output_tail or _START_UNVERIFIED)
    while time.monotonic() < deadline:
        try:
            health = asyncio.run(read_typed_health())
        except Exception as error:
            reason = _HEALTH_READ_FAILURE.format(error_kind=type(error).__name__)
            time.sleep(_POLL_INTERVAL_SECONDS)
            continue
        preparation = health.preparation
        # A start that finished with a failure (a hard dependency, the ingress receiver) is not verified by a
        # healthy daemon alone.
        start_failed = not started.timed_out and started.exit_code != 0
        if not start_failed and accepts(health) and preparation is not None and preparation.phase is DrainPhase.OPEN:
            return StartAttempt(started=started, verified=True, start_commit=health.start_commit)
        if start_failed:
            break
        reason = _START_UNVERIFIED
        time.sleep(_POLL_INTERVAL_SECONDS)

    if started.exit_code != 0 and started.output_tail:
        reason = _START_FAILURE_REASON.format(reason=reason, output_tail=started.output_tail)
    return StartAttempt(started=started, verified=False, reason=reason)


async def read_typed_health() -> HealthDTO:
    """Read the daemon's typed health DTO using the CLI's published local API client.

    Verification of a start and the check that a daemon serves the active release read health through this one path.
    """
    client = TelecAPIClient()
    await client.connect()
    try:
        return await client.get_health()
    finally:
        await client.close()


def _request_stop(lifecycle: Lifecycle, directory: Path) -> tuple[StopOutcome | None, CommandResult]:
    """Ask the lifecycle to stop and return its recorded outcome independently of its exit status."""
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=directory, prefix=_STOP_OUTCOME_PREFIX, delete=False) as handle:
        outcome_path = Path(handle.name)
    outcome_path.unlink(missing_ok=True)
    try:
        result = run_process_group_command(
            list(lifecycle.stop),
            lifecycle.cwd,
            lifecycle.stop_environment(outcome_path),
            timeout_seconds=_stop_command_bound_seconds(),
            capture_output=secret_output_masker(lifecycle.cwd),
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
