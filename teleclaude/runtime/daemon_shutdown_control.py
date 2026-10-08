"""Host-side preparation of the running daemon before an ordinary stop or restart.

`bin/daemon-control.sh` delegates here in one line per verb. The helper observes the
daemon on its local API socket, proves the observed process is the one the service
manager runs, asks it to prepare (SIGUSR1) and waits for that same instance to report
drained. It performs no service-manager action and never terminates anything: the
caller acts only on a successful outcome.

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
from enum import IntEnum, StrEnum
from pathlib import Path

from teleclaude.core.session_startup import UNFINISHED_STARTUP_STATES
from teleclaude.core.shutdown_drain import PREPARATION_PROTOCOL_VERSION, DrainPhase
from teleclaude.paths import MAIN_DB_PATH

_HEALTH_PATH = "/health"
_HEALTH_TIMEOUT_S = 2.0
_POLL_INTERVAL_S = 0.5
_DB_TIMEOUT_S = 2.0
_HEALTH_STATUS_OK = "ok"
_START_COMMIT_FIELD = "start_commit"
_STATUS_FIELD = "status"
_PREPARATION_FIELD = "preparation"
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


@dataclass(frozen=True)
class PreparationObservation:
    """The preparation block of a supporting daemon's health answer."""

    protocol: int
    pid: int
    token: str
    phase: DrainPhase
    budget_seconds: float


@dataclass(frozen=True)
class HealthObservation:
    """One validated answer from the daemon's health endpoint."""

    fields: frozenset[str]
    preparation: PreparationObservation | None


class _UnixSocketConnection(http.client.HTTPConnection):
    """HTTP over the daemon's local API socket."""

    def __init__(self, socket_path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._socket_path)


def read_health(socket_path: str) -> HealthObservation:
    """Read and validate the daemon's health answer; any malformed answer is unreadable."""
    connection = _UnixSocketConnection(socket_path, _HEALTH_TIMEOUT_S)
    try:
        connection.request("GET", _HEALTH_PATH)
        response = connection.getresponse()
        body = response.read()
        status = response.status
    except (OSError, http.client.HTTPException) as exc:
        raise ControlRefusal(ControlOutcome.UNREADABLE, str(exc)) from exc
    finally:
        connection.close()
    if status != http.HTTPStatus.OK:
        raise ControlRefusal(ControlOutcome.UNREADABLE, f"health answered {status}")
    try:
        document = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ControlRefusal(ControlOutcome.UNREADABLE, "health answer is not JSON") from exc
    if not isinstance(document, dict) or document.get(_STATUS_FIELD) != _HEALTH_STATUS_OK:
        raise ControlRefusal(ControlOutcome.UNREADABLE, "health answer is not an ok document")
    raw_preparation = document.get(_PREPARATION_FIELD)
    return HealthObservation(
        fields=frozenset(document),
        preparation=_parse_preparation(raw_preparation) if raw_preparation is not None else None,
    )


def _parse_preparation(raw: object) -> PreparationObservation:
    if not isinstance(raw, dict):
        raise ControlRefusal(ControlOutcome.UNREADABLE, "preparation observation is malformed")
    try:
        return PreparationObservation(
            protocol=int(raw["protocol"]),
            pid=int(raw["pid"]),
            token=str(raw["token"]),
            phase=DrainPhase(raw["phase"]),
            budget_seconds=float(raw["budget_seconds"]),
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
            raise ControlRefusal(ControlOutcome.TIMEOUT, f"phase {current.phase}")
        sleep(_POLL_INTERVAL_S)
    return _same_instance(socket_path, first).pid


def _same_instance(socket_path: str, expected: PreparationObservation) -> PreparationObservation:
    observed = read_health(socket_path).preparation
    if observed is None or observed.pid != expected.pid or observed.token != expected.token:
        raise ControlRefusal(ControlOutcome.INSTANCE_REPLACED, "a different process instance answered")
    return observed


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


def main(argv: Sequence[str] | None = None) -> int:
    """Run one verb; print the instance pid on success, the typed refusal on failure."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verb", choices=[verb.value for verb in _Verb])
    parser.add_argument("--socket", required=True)
    parser.add_argument("--manager-pid", required=True, type=int)
    parser.add_argument("--pid-file")
    args = parser.parse_args(argv)
    try:
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
