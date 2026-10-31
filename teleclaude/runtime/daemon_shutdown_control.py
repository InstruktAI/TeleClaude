"""Host-side preparation of the running daemon before an ordinary stop or restart.

`bin/daemon-control.sh` delegates here in one line per verb. The helper observes the
daemon on its local API socket, proves the observed process is the one the service
manager runs, asks it to prepare (SIGUSR1) and waits for that same instance to report
drained. It performs no service-manager action and never terminates anything: the
caller acts only on a successful outcome. A window that expires on an instance that
completes its own shutdown is a deferral, not a failure: the draining daemon finishes
the restart once its accepted work settles.

The read-only `status` verb reports the same observation for `make status`, the read-only
`degraded` verb the optional components the daemon serves without, and the read-only `ready` verb
the event Redis scopes the daemon's readiness answer names as not answering.

Maintenance callers that must not store configuration documents past what the running daemon reads
ask `read_migration_reach` for the migration reach the daemon reports.

The explicit legacy activation path serves the one daemon that predates the
preparation protocol. It identifies that runtime positively, inspects its unfinished
durable work read-only and reports observed quiescence; it neither closes admission
nor proves that effects have settled.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import signal
import socket
import sqlite3
import stat
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum, StrEnum
from pathlib import Path

from teleclaude.config.migrations.daemon_reach import DaemonReach, ReachState
from teleclaude.core.session_startup import UNFINISHED_STARTUP_STATES
from teleclaude.core.shutdown_drain import PREPARATION_PROTOCOL_VERSION, DrainPhase
from teleclaude.paths import MAIN_DB_PATH

_HEALTH_PATH = "/health"
_READY_PATH = "/ready"
_HEALTH_TIMEOUT_S = 2.0
_POLL_INTERVAL_S = 0.5
# Bounds how long a listening daemon may stay silent before its migration reach is treated as unanswered.
_REACH_ANSWER_BOUND_S = 15.0
_DB_TIMEOUT_S = 2.0
_HEALTH_STATUS_OK = "ok"
_START_COMMIT_FIELD = "start_commit"
_STATUS_FIELD = "status"
_PREPARATION_FIELD = "preparation"
_MIGRATION_REACH_FIELD = "config_migration_reach"
_MIGRATION_REACH_MALFORMED = "migration reach is malformed"
_DEGRADED_FIELD = "degraded"
_DEGRADED_MALFORMED = "degraded components are malformed"
_READY_MALFORMED = "readiness answer is malformed"
_SCOPE_FIELD = "scope"
_STARTED_AT_FIELD = "preparation_started_at"
_HELD_LABELS_FIELD = "held_labels"
_GRACE_FIELD = "termination_grace_seconds"
_MANAGER_PID_REQUIRED = "--manager-pid is required for {verb}"
_HELD_LABEL_SEPARATOR = ", "
_ADMISSION_OPEN_LINE = "admission open"
_ADMISSION_CLOSED_LINE = "phase {phase}, preparation began {started_at}, holding {held_units} unit(s): {held}"
_UNKNOWN_START = "at an unreported time"
_NO_HELD_WORK = "none"
_LEGACY_HEALTH_FIELDS = frozenset({_STATUS_FIELD, _START_COMMIT_FIELD})
_PREPARED_PHASES = frozenset({DrainPhase.DRAINED, DrainPhase.STOPPING})
_STATE_PLACEHOLDER = ",".join("?" for _ in UNFINISHED_STARTUP_STATES)


class ControlOutcome(IntEnum):
    """Typed exit outcomes the lifecycle script reports."""

    OK = 0
    UNSUPPORTED = 10
    UNREADABLE = 11
    IDENTITY_MISMATCH = 12
    TIMEOUT = 13
    INSTANCE_REPLACED = 14
    DEFERRED = 15
    ADMISSION_CLOSED = 16
    DEGRADED = 17
    LEGACY_NOT_IDENTIFIED = 20
    LEGACY_SUPPORTS_PREPARATION = 21
    LEGACY_RESIDUAL_WORK = 22
    LEGACY_EVIDENCE_UNREADABLE = 23


_OUTCOME_MESSAGES: dict[ControlOutcome, str] = {
    ControlOutcome.OK: "daemon instance is prepared",
    ControlOutcome.UNSUPPORTED: "the running daemon does not support shutdown preparation",
    ControlOutcome.UNREADABLE: "the running daemon's preparation state could not be read: {detail}",
    ControlOutcome.IDENTITY_MISMATCH: (
        "the process answering on the API socket is not the service manager's daemon process: {detail}"
    ),
    ControlOutcome.TIMEOUT: (
        "preparation did not complete within its observation window; the daemon is left running and draining: {detail}"
    ),
    ControlOutcome.INSTANCE_REPLACED: "the daemon process changed during preparation: {detail}",
    ControlOutcome.DEFERRED: (
        "preparation did not complete within its observation window; the draining daemon completes the restart"
        " once its accepted work settles: {detail}"
    ),
    ControlOutcome.ADMISSION_CLOSED: "the daemon is not accepting new work: {detail}",
    ControlOutcome.DEGRADED: "the daemon serves without some optional components: {detail}",
    ControlOutcome.LEGACY_NOT_IDENTIFIED: "the running daemon is not positively identified as the legacy runtime: {detail}",
    ControlOutcome.LEGACY_SUPPORTS_PREPARATION: "the running daemon supports preparation; legacy activation is refused",
    ControlOutcome.LEGACY_RESIDUAL_WORK: "unfinished durable work remains: {detail}",
    ControlOutcome.LEGACY_EVIDENCE_UNREADABLE: "the unfinished-work evidence could not be read: {detail}",
}


class ControlRefusal(Exception):
    """A typed refusal carrying the outcome the script reports."""

    def __init__(self, outcome: ControlOutcome, detail: str = "") -> None:
        super().__init__(_OUTCOME_MESSAGES[outcome].format(detail=detail))
        self.outcome = outcome


class NothingListening(ControlRefusal):
    """The API socket is absent or refuses the connection: no daemon process serves it."""

    def __init__(self, detail: str) -> None:
        super().__init__(ControlOutcome.UNREADABLE, detail)


@dataclass(frozen=True)
class PreparationObservation:
    """The preparation block of a supporting daemon's health answer."""

    protocol: int
    pid: int
    token: str
    phase: DrainPhase
    held_units: int
    budget_seconds: float
    preparation_started_at: datetime | None = None
    held_labels: tuple[str, ...] = ()
    termination_grace_seconds: float | None = None


@dataclass(frozen=True)
class HealthObservation:
    """One validated answer from the daemon's health endpoint."""

    fields: frozenset[str]
    preparation: PreparationObservation | None
    migration_reach: int | None = None
    degraded: tuple[str, ...] | None = None


class _UnixSocketConnection(http.client.HTTPConnection):
    """HTTP over the daemon's local API socket."""

    def __init__(self, socket_path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._socket_path)


def _read_document(socket_path: str, path: str, name: str) -> object:
    """GET one JSON document from the daemon's API socket; anything but a 200 JSON answer is unreadable."""
    connection = _UnixSocketConnection(socket_path, _HEALTH_TIMEOUT_S)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read()
        status = response.status
    except (FileNotFoundError, ConnectionRefusedError) as exc:
        raise NothingListening(str(exc)) from exc
    except (OSError, http.client.HTTPException) as exc:
        raise ControlRefusal(ControlOutcome.UNREADABLE, str(exc)) from exc
    finally:
        connection.close()
    if status != http.HTTPStatus.OK:
        raise ControlRefusal(ControlOutcome.UNREADABLE, f"{name} answered {status}")
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ControlRefusal(ControlOutcome.UNREADABLE, f"{name} answer is not JSON") from exc


def read_health(socket_path: str) -> HealthObservation:
    """Read and validate the daemon's health answer; any malformed answer is unreadable."""
    document = _read_document(socket_path, _HEALTH_PATH, "health")
    if not isinstance(document, dict) or document.get(_STATUS_FIELD) != _HEALTH_STATUS_OK:
        raise ControlRefusal(ControlOutcome.UNREADABLE, "health answer is not an ok document")
    raw_preparation = document.get(_PREPARATION_FIELD)
    return HealthObservation(
        fields=frozenset(document),
        preparation=_parse_preparation(raw_preparation) if raw_preparation is not None else None,
        migration_reach=_parse_migration_reach(document.get(_MIGRATION_REACH_FIELD)),
        degraded=_parse_degraded(document.get(_DEGRADED_FIELD)),
    )


def _parse_degraded(raw: object) -> tuple[str, ...] | None:
    """One line per degraded component: what, for which subject, since when, and why."""
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ControlRefusal(ControlOutcome.UNREADABLE, _DEGRADED_MALFORMED)
    lines: list[str] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ControlRefusal(ControlOutcome.UNREADABLE, _DEGRADED_MALFORMED)
        component, subject, reason, since = (entry.get(key) for key in ("component", "subject", "reason", "since"))
        if not isinstance(component, str) or not isinstance(reason, str) or not isinstance(since, str):
            raise ControlRefusal(ControlOutcome.UNREADABLE, _DEGRADED_MALFORMED)
        scope = f"{component} ({subject})" if isinstance(subject, str) else component
        lines.append(f"{scope} since {since}: {reason}")
    return tuple(lines)


def _parse_migration_reach(raw: object) -> int | None:
    """A reported reach is a non-negative integer; anything else makes the answer unreadable, never a reach."""
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise ControlRefusal(ControlOutcome.UNREADABLE, _MIGRATION_REACH_MALFORMED)
    return raw


def read_migration_reach(
    socket_path: str,
    *,
    bound_seconds: float = _REACH_ANSWER_BOUND_S,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> DaemonReach:
    """Ask the daemon on the API socket which configuration migration version it reads.

    An absent or refusing socket means nothing listens. A daemon that answers without a reach predates
    the field. Something that listens but gives no valid answer within the bound is unanswered, and is
    retried until then.
    """
    deadline = clock() + bound_seconds
    while True:
        try:
            reach = read_health(socket_path).migration_reach
        except NothingListening:
            return DaemonReach(ReachState.NOT_LISTENING)
        except ControlRefusal:
            if clock() >= deadline:
                return DaemonReach(ReachState.UNANSWERED)
            sleep(_POLL_INTERVAL_S)
            continue
        if reach is None:
            return DaemonReach(ReachState.NOT_REPORTED)
        return DaemonReach(ReachState.REPORTED, reach)


def _parse_preparation(raw: object) -> PreparationObservation:
    if not isinstance(raw, dict):
        raise ControlRefusal(ControlOutcome.UNREADABLE, "preparation observation is malformed")
    started_at = raw.get(_STARTED_AT_FIELD)
    grace = raw.get(_GRACE_FIELD)
    try:
        return PreparationObservation(
            protocol=int(raw["protocol"]),
            pid=int(raw["pid"]),
            token=str(raw["token"]),
            phase=DrainPhase(raw["phase"]),
            held_units=int(raw["held_units"]),
            budget_seconds=float(raw["budget_seconds"]),
            preparation_started_at=None if started_at is None else datetime.fromisoformat(str(started_at)),
            held_labels=tuple(str(label) for label in raw.get(_HELD_LABELS_FIELD) or ()),
            termination_grace_seconds=None if grace is None else float(grace),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ControlRefusal(ControlOutcome.UNREADABLE, "preparation observation is malformed") from exc


def prepare(
    socket_path: str,
    manager_pid: int,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Prepare the observed daemon and return the pid of the instance that reported drained.

    Raises `ControlRefusal` with the typed outcome when the capability is missing, the
    observed process is not the manager's, the window elapses, or the instance changes.
    """
    first = read_health(socket_path).preparation
    if first is None or first.protocol != PREPARATION_PROTOCOL_VERSION:
        raise ControlRefusal(ControlOutcome.UNSUPPORTED)
    if first.pid != manager_pid:
        raise ControlRefusal(ControlOutcome.IDENTITY_MISMATCH, f"observed pid {first.pid}, manager pid {manager_pid}")
    if first.phase is DrainPhase.OPEN:
        os.kill(first.pid, signal.SIGUSR1)
    deadline = clock() + first.budget_seconds
    while True:
        current = _same_instance(socket_path, first)
        if current.phase in _PREPARED_PHASES:
            break
        if clock() >= deadline:
            outcome = ControlOutcome.TIMEOUT if current.termination_grace_seconds is None else ControlOutcome.DEFERRED
            raise ControlRefusal(outcome, f"phase {current.phase}")
        sleep(_POLL_INTERVAL_S)
    return _same_instance(socket_path, first).pid


def _same_instance(socket_path: str, expected: PreparationObservation) -> PreparationObservation:
    observed = read_health(socket_path).preparation
    if observed is None or observed.pid != expected.pid or observed.token != expected.token:
        raise ControlRefusal(ControlOutcome.INSTANCE_REPLACED, "a different process instance answered")
    return observed


def describe_admission(preparation: PreparationObservation) -> str:
    """One line naming the phase, when preparation began, and the work the daemon still holds."""
    if preparation.phase is DrainPhase.OPEN:
        return _ADMISSION_OPEN_LINE
    started_at = preparation.preparation_started_at
    return _ADMISSION_CLOSED_LINE.format(
        phase=preparation.phase,
        started_at=_UNKNOWN_START if started_at is None else started_at.isoformat(),
        held_units=preparation.held_units,
        held=_HELD_LABEL_SEPARATOR.join(preparation.held_labels) or _NO_HELD_WORK,
    )


def report_admission(socket_path: str) -> int:
    """Print the daemon's admission state; exit OK only while admission is open. Sends no signal."""
    preparation = read_health(socket_path).preparation
    if preparation is None:
        raise ControlRefusal(ControlOutcome.UNSUPPORTED)
    print(describe_admission(preparation))
    if preparation.phase is DrainPhase.OPEN:
        return int(ControlOutcome.OK)
    return int(ControlOutcome.ADMISSION_CLOSED)


def report_degraded(socket_path: str) -> int:
    """Print each optional component the daemon serves without; exit OK only when there is none."""
    degraded = read_health(socket_path).degraded
    if degraded is None:
        raise ControlRefusal(ControlOutcome.UNSUPPORTED)
    for line in degraded:
        print(line)
    return int(ControlOutcome.DEGRADED) if degraded else int(ControlOutcome.OK)


def report_readiness(socket_path: str) -> int:
    """Print each event Redis scope the daemon's readiness answer names as not answering; OK only when none."""
    document = _read_document(socket_path, _READY_PATH, "readiness")
    if not isinstance(document, dict):
        raise ControlRefusal(ControlOutcome.UNREADABLE, _READY_MALFORMED)
    entries = document.get(_DEGRADED_FIELD, [])
    if not isinstance(entries, list):
        raise ControlRefusal(ControlOutcome.UNREADABLE, _READY_MALFORMED)
    scopes: list[str] = []
    for entry in entries:
        scope = entry.get(_SCOPE_FIELD) if isinstance(entry, dict) else None
        if not isinstance(scope, str):
            raise ControlRefusal(ControlOutcome.UNREADABLE, _READY_MALFORMED)
        scopes.append(scope)
    for scope in scopes:
        print(scope)
    return int(ControlOutcome.DEGRADED) if scopes else int(ControlOutcome.OK)


def quiesce_legacy(socket_path: str, manager_pid: int, pid_file: str | None) -> int:
    """Return the pid of the positively identified legacy daemon whose durable work is quiescent."""
    pid = _identify_legacy(socket_path, manager_pid, pid_file)
    residual = _residual_work(MAIN_DB_PATH)
    if residual:
        raise ControlRefusal(
            ControlOutcome.LEGACY_RESIDUAL_WORK, ", ".join(f"{name}={count}" for name, count in residual)
        )
    if _identify_legacy(socket_path, manager_pid, pid_file) != pid or _residual_work(MAIN_DB_PATH):
        raise ControlRefusal(ControlOutcome.LEGACY_RESIDUAL_WORK, "state changed during inspection")
    return pid


def _identify_legacy(socket_path: str, manager_pid: int, pid_file: str | None) -> int:
    """Positive identification from health, socket and manager process evidence; absence is not identification."""
    health = read_health(socket_path)
    if health.preparation is not None:
        raise ControlRefusal(ControlOutcome.LEGACY_SUPPORTS_PREPARATION)
    if health.fields != _LEGACY_HEALTH_FIELDS:
        raise ControlRefusal(ControlOutcome.LEGACY_NOT_IDENTIFIED, "health document is not the known legacy shape")
    try:
        socket_is_socket = stat.S_ISSOCK(os.stat(socket_path).st_mode)
    except OSError as exc:
        raise ControlRefusal(ControlOutcome.LEGACY_NOT_IDENTIFIED, f"API socket: {exc}") from exc
    if not socket_is_socket:
        raise ControlRefusal(ControlOutcome.LEGACY_NOT_IDENTIFIED, "API socket path is not a socket")
    try:
        os.kill(manager_pid, 0)
    except OSError as exc:
        raise ControlRefusal(ControlOutcome.LEGACY_NOT_IDENTIFIED, f"manager pid {manager_pid}: {exc}") from exc
    if pid_file is not None and Path(pid_file).is_file() and Path(pid_file).read_text().strip() != str(manager_pid):
        raise ControlRefusal(ControlOutcome.LEGACY_NOT_IDENTIFIED, "pid file disagrees with the manager pid")
    return manager_pid


def _residual_work(db_path: Path) -> list[tuple[str, int]]:
    """Unfinished operations, live startup handovers and in-flight inbound rows, read-only."""
    queries: dict[str, tuple[str, Sequence[str]]] = {
        "operations": ("SELECT COUNT(*) FROM operations WHERE state IN ('queued', 'running')", ()),
        "startup_handovers": (
            "SELECT COUNT(*) FROM session_startup_handovers h JOIN sessions s ON s.session_id = h.session_id "
            f"WHERE s.closed_at IS NULL AND h.state IN ({_STATE_PLACEHOLDER})",
            tuple(state.value for state in UNFINISHED_STARTUP_STATES),
        ),
        "inbound_processing": ("SELECT COUNT(*) FROM inbound_queue WHERE status = 'processing'", ()),
    }
    try:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=_DB_TIMEOUT_S)
        try:
            counts = [
                (name, int(connection.execute(sql, params).fetchone()[0])) for name, (sql, params) in queries.items()
            ]
        finally:
            connection.close()
    except (sqlite3.Error, TypeError, ValueError) as exc:
        raise ControlRefusal(ControlOutcome.LEGACY_EVIDENCE_UNREADABLE, str(exc)) from exc
    return [(name, count) for name, count in counts if count > 0]


class _Verb(StrEnum):
    PREPARE = "prepare"
    LEGACY = "legacy"
    STATUS = "status"
    DEGRADED = "degraded"
    READY = "ready"


def main(argv: Sequence[str] | None = None) -> int:
    """Run one verb; print the instance pid on success, the typed refusal on failure."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verb", choices=[verb.value for verb in _Verb])
    parser.add_argument("--socket", required=True)
    parser.add_argument("--manager-pid", type=int)
    parser.add_argument("--pid-file")
    args = parser.parse_args(argv)
    if args.verb not in (_Verb.STATUS, _Verb.DEGRADED, _Verb.READY) and args.manager_pid is None:
        parser.error(_MANAGER_PID_REQUIRED.format(verb=args.verb))
    try:
        if args.verb == _Verb.STATUS:
            return report_admission(args.socket)
        if args.verb == _Verb.DEGRADED:
            return report_degraded(args.socket)
        if args.verb == _Verb.READY:
            return report_readiness(args.socket)
        if args.verb == _Verb.PREPARE:
            pid = prepare(args.socket, args.manager_pid)
        else:
            pid = quiesce_legacy(args.socket, args.manager_pid, args.pid_file)
    except ControlRefusal as refusal:
        print(refusal, file=sys.stderr)
        return int(refusal.outcome)
    print(pid)
    return int(ControlOutcome.OK)


if __name__ == "__main__":
    sys.exit(main())
