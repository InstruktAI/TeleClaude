"""Fail-closed host admission and durable ownership for the release proof VM."""

from __future__ import annotations

import argparse
import fcntl
import http.client
import json
import os
import socket
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import cast

import psutil
from instrukt_ai_logging import configure_logging, get_logger

_ROOT_NAME = "teleclaude-release-host"
_STATE_DIRECTORY = "state"
_PROOF_RECORD = "installer-proof.json"
_LOCK_FILE = "installer-proof.lock"
_FLEET_ROOT_NAME = "tart-runner-fleet"
_FLEET_STATE_NAME = "state"
_FLEET_SOCKET_NAME = "fleetd.sock"
_FLEET_STATUS_PATH = "/v1/status"
_FLEET_API_VERSION = "fleet.v1"
_FLEET_KIND = "Status"
_FLEET_AUTHORITY_MODE = "authority"
_FLEET_STALE_SECONDS = 90
_FLEET_DISPOSAL_TIMEOUT_SECONDS = 300
_FLEET_DISPOSAL_POLL_SECONDS = 5
_HTTP_TIMEOUT_SECONDS = 5
_COMMAND_TIMEOUT_SECONDS = 45
_TART_BINARY = "/opt/homebrew/bin/tart"
_TART_LIST_COMMAND = "list"
_TART_FORMAT_OPTION = "--format"
_JSON_FORMAT = "json"
_TART_STOP_COMMAND = "stop"
_TART_DELETE_COMMAND = "delete"
_TART_RUNNING_KEY = "Running"
_TART_INVENTORY_PREFIX = "teleclaude-release-proof-"
_LOCK_MODE = 0o600
_DIRECTORY_MODE = 0o700
_UTF8 = "utf-8"
_EMPTY = ""
_NEWLINE = "\n"
_JSON_INDENT = 2
_STATUS_SUCCESS = "success"
_STATUS_SETTLED = "settled"
_STATUS_CREATED = "created"
_STATUS_CREATE_INTENT = "create_intent"
_STATUS_RECOVERED = "recovered"
_RESULT_ARGUMENT = "result"
_VM_ARGUMENT = "vm-name"
_BASE_ARGUMENT = "base-image"
_RUN_ID_ARGUMENT = "run-id"
_ATTEMPT_ARGUMENT = "run-attempt"
_CPU_ARGUMENT = "cpu"
_MEMORY_ARGUMENT = "memory-mib"
_RUNNER_DESTINATION_ARGUMENT = "runner-destination"
_ADMIT_COMMAND = "admit"
_VALIDATE_INPUTS_COMMAND = "validate-inputs"
_BEGIN_COMMAND = "proof-begin"
_CREATED_COMMAND = "proof-created"
_SETTLE_COMMAND = "proof-settle"
_OUTCOME_COMMAND = "proof-outcome"
_CLEANUP_FAILED_COMMAND = "proof-cleanup-failed"
_REFUSED_EVENT = "release_host_guard_refused"
_RECORD_INVALID = "the durable proof record is invalid; preserve it for operator review"
_RECORD_EXISTS = "an unfinished or conflicting installer proof record already exists"
_RECORD_MISSING = "installer proof ownership has not been recorded"
_RECORD_MISMATCH = "the requested proof does not match the durable ownership record"
_FLEET_UNAVAILABLE = "Fleet status is unavailable or invalid"
_FLEET_API_MISMATCH = "Fleet status uses an unsupported API or response kind"
_FLEET_NOT_READY = "Fleet is not ready and admitting work"
_FLEET_NOT_QUIESCENT = "Fleet has queued work, live instances, or unfinished lifecycle operations"
_FLEET_STALE = "Fleet status or its last successful observation is stale"
_FLEET_DISPOSAL_TIMEOUT = "Fleet disposal was not observed before the bounded deadline"
_TART_UNAVAILABLE = "Tart inventory is unavailable or invalid"
_TART_VM_PRESENT = "a release proof VM is still present; disposal is not confirmed"
_TART_VM_MISSING = "the recorded release proof VM is absent before creation was confirmed"
_TART_UNKNOWN_VM = "an unrecorded release proof VM exists; refusing to infer ownership"
_HOST_PRESSURE = "host capacity does not meet the qualified proof reservation"
_HOST_RESOURCE_INPUT_INVALID = "the qualified proof CPU and memory allocations must be positive integers"
_RUNNER_DESTINATION_INVALID = "the owned runner destination must be configured"
_BASE_IMAGE_INVALID = "the immutable Mac proof base image must be configured"
_HOST_DISK_MIN_GIB = 60
_HOST_LOAD_PER_CPU_MAX = 0.75
_HOST_CPU_RESERVE = 2
_HOST_MEMORY_RESERVE_MIB = 4096
_VM_NAME_PATTERN = "{prefix}{run_id}-{attempt}"
_RECORD_SCHEMA_VERSION = 1
_LOCK_EXCLUSIVE = fcntl.LOCK_EX
_FILE_MODE = "w"
_STATUS_FAILURE = "failure"
_FIELD_SCHEMA = "schema_version"
_FIELD_RUN_ID = "run_id"
_FIELD_RUN_ATTEMPT = "run_attempt"
_FIELD_VM_NAME = "vm_name"
_FIELD_BASE_IMAGE = "base_image"
_FIELD_CPU = "cpu"
_FIELD_MEMORY = "memory_mib"
_FIELD_PHASE = "phase"
_FIELD_CREATED = "created_at"
_FIELD_UPDATED = "updated_at"
_FIELD_INSTALLER_RESULT = "installer_result"
_FIELD_CLEANUP_RESULT = "cleanup_result"
_FIELD_CLEANUP_OBSERVED = "cleanup_observed_at"
_FIELD_CLEANUP_FAILED = "cleanup_failed_at"
_FIELD_CONTROLLER_MODE = "controllerMode"
_HTTP_HOST = "localhost"
_HTTP_ACCEPT = "Accept"
_JSON_MEDIA_TYPE = "application/json"
_FIELD_API_VERSION = "apiVersion"
_FIELD_KIND = "kind"
_FIELD_DATA = "data"
_FIELD_READY = "ready"
_FIELD_OK = "ok"
_FIELD_PRESSURE = "hostPressure"
_FIELD_ADMISSION_ALLOWED = "admissionAllowed"
_FIELD_GENERATED_AT = "generatedAt"
_FIELD_LAST_SUCCESSFUL_TICK = "lastSuccessfulTick"
_FIELD_QUEUES = "queues"
_FIELD_SCOPE_QUEUES = "scopeQueues"
_FIELD_INGEST_CHECK = "ingestCheck"
_FIELD_JOBS = "jobs"
_FIELD_COUNT = "count"
_FIELD_INSTANCES = "instances"
_FIELD_OPERATIONS = "operations"
_FIELD_RETRYING = "retrying"
_FIELD_DEAD = "dead"
_FIELD_TART_NAME = "Name"
_HOST_REPORT_AVAILABLE_MEMORY = "available_memory_mib"
_HOST_REPORT_USED_SWAP = "used_swap_mib"
_HOST_REPORT_FREE_DISK = "free_disk_gib"
_HOST_REPORT_CPU_COUNT = "cpu_count"
_HOST_REPORT_LOAD_PER_CPU = "load_per_cpu"
_REPORT_ADMITTED = "admitted"
_REPORT_FLEET = "fleet"
_REPORT_FLEET_READY = "ready-and-quiescent"
_REPORT_HOST = "host"
_REPORT_RECOVERY = "proof_recovery"
_LIBRARY = "Library"
_APPLICATION_SUPPORT = "Application Support"
_HTTP_GET = "GET"
_UTC_Z = "Z"
_UTC_OFFSET = "+00:00"
_FIELD_COMMAND = "command"
_OPTION_PREFIX = "--"
_REPORT_INPUTS_VALID = "inputs_valid"
_LOAD_AVERAGE_ATTRIBUTE = "getloadavg"
_LOG_APPLICATION_NAME = "teleclaude"
logger = get_logger(__name__)


def validate_inputs(runner_destination: str, base_image: str, proof_cpu: int, proof_memory_mib: int) -> None:
    if not runner_destination.strip():
        raise RuntimeError(_RUNNER_DESTINATION_INVALID)
    if not base_image.strip():
        raise RuntimeError(_BASE_IMAGE_INVALID)
    if proof_cpu < 1 or proof_memory_mib < 1:
        raise RuntimeError(_HOST_RESOURCE_INPUT_INVALID)
    print(json.dumps({_REPORT_INPUTS_VALID: True}, sort_keys=True), flush=True)


class Phase(StrEnum):
    """Durable proof lifecycle states."""

    CREATE_INTENT = _STATUS_CREATE_INTENT
    CREATED = _STATUS_CREATED
    SETTLED = _STATUS_SETTLED


class InstallerResult(StrEnum):
    """Closed outcomes for installer execution."""

    SUCCESS = _STATUS_SUCCESS
    FAILURE = _STATUS_FAILURE


class CleanupResult(StrEnum):
    """Closed outcomes for proof VM cleanup."""

    SUCCESS = _STATUS_SUCCESS
    FAILURE = _STATUS_FAILURE
    RECOVERED = _STATUS_RECOVERED


class GuardCommand(StrEnum):
    """Supported release host guard commands."""

    ADMIT = _ADMIT_COMMAND
    VALIDATE_INPUTS = _VALIDATE_INPUTS_COMMAND
    BEGIN = _BEGIN_COMMAND
    CREATED = _CREATED_COMMAND
    OUTCOME = _OUTCOME_COMMAND
    CLEANUP_FAILED = _CLEANUP_FAILED_COMMAND
    SETTLE = _SETTLE_COMMAND


@dataclass(frozen=True)
class ProofOwnership:
    """Private record identifying one release proof VM and its observed outcome."""

    schema_version: int
    run_id: str
    run_attempt: str
    vm_name: str
    base_image: str
    cpu: int
    memory_mib: int
    phase: Phase
    created_at: str
    updated_at: str
    installer_result: InstallerResult | None = None
    cleanup_result: CleanupResult | None = None
    cleanup_observed_at: str | None = None
    cleanup_failed_at: str | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _host_root() -> Path:
    root = Path.home() / _LIBRARY / _APPLICATION_SUPPORT / _ROOT_NAME
    state = root / _STATE_DIRECTORY
    root.mkdir(mode=_DIRECTORY_MODE, parents=True, exist_ok=True)
    state.mkdir(mode=_DIRECTORY_MODE, exist_ok=True)
    root.chmod(_DIRECTORY_MODE)
    state.chmod(_DIRECTORY_MODE)
    return state


def _fleet_socket() -> Path:
    return Path.home() / _LIBRARY / _APPLICATION_SUPPORT / _FLEET_ROOT_NAME / _FLEET_STATE_NAME / _FLEET_SOCKET_NAME


class UnixHTTPConnection(http.client.HTTPConnection):
    """Send one HTTP request over Fleet's private local Unix socket."""

    def __init__(self, socket_path: Path, timeout: float) -> None:
        super().__init__(host=_HTTP_HOST, timeout=timeout)
        self._socket_path = socket_path

    def connect(self) -> None:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(self.timeout)
        connection.connect(str(self._socket_path))
        self.sock = connection


def _fleet_status() -> Mapping[str, object]:
    endpoint = _fleet_socket()
    if not endpoint.is_socket():
        raise RuntimeError(_FLEET_UNAVAILABLE)
    connection = UnixHTTPConnection(endpoint, _HTTP_TIMEOUT_SECONDS)
    try:
        connection.request(_HTTP_GET, _FLEET_STATUS_PATH, headers={_HTTP_ACCEPT: _JSON_MEDIA_TYPE})
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError(_FLEET_UNAVAILABLE)
        raw = cast(object, json.loads(response.read().decode(_UTF8)))
    except (OSError, http.client.HTTPException, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError(_FLEET_UNAVAILABLE) from exc
    finally:
        connection.close()
    envelope = _mapping(raw, _FLEET_UNAVAILABLE)
    if envelope.get(_FIELD_API_VERSION) != _FLEET_API_VERSION or envelope.get(_FIELD_KIND) != _FLEET_KIND:
        raise RuntimeError(_FLEET_API_MISMATCH)
    return envelope


def _mapping(value: object, error: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise RuntimeError(error)
    return cast(Mapping[str, object], value)


def _required_string(value: Mapping[str, object], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str):
        raise RuntimeError(_RECORD_INVALID)
    return result


def _optional_string(value: Mapping[str, object], key: str) -> str | None:
    result = value.get(key)
    if result is not None and not isinstance(result, str):
        raise RuntimeError(_RECORD_INVALID)
    return result


def _sequence(value: object, error: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise RuntimeError(error)
    return cast(Sequence[object], value)


def _has_nonzero_counts(rows: Sequence[object], field: str) -> bool:
    for row in rows:
        count = _mapping(row, _FLEET_UNAVAILABLE).get(field)
        if not isinstance(count, int) or isinstance(count, bool) or count != 0:
            return True
    return False


def _require_fresh(value: object, *, maximum_age_seconds: int) -> None:
    if not isinstance(value, str):
        raise RuntimeError(_FLEET_STALE)
    try:
        observed = datetime.fromisoformat(value.replace(_UTC_Z, _UTC_OFFSET))
    except ValueError as exc:
        raise RuntimeError(_FLEET_STALE) from exc
    if observed.tzinfo is None:
        raise RuntimeError(_FLEET_STALE)
    age = (datetime.now(UTC) - observed.astimezone(UTC)).total_seconds()
    if age < 0 or age > maximum_age_seconds:
        raise RuntimeError(_FLEET_STALE)


def _assert_fleet_quiescent() -> Mapping[str, object]:
    envelope = _fleet_status()
    _require_fresh(envelope.get(_FIELD_GENERATED_AT), maximum_age_seconds=_FLEET_STALE_SECONDS)
    raw_data = _mapping(envelope.get(_FIELD_DATA), _FLEET_UNAVAILABLE)
    if raw_data.get(_FIELD_CONTROLLER_MODE) != _FLEET_AUTHORITY_MODE:
        raise RuntimeError(_FLEET_NOT_READY)
    ready = _mapping(raw_data.get(_FIELD_READY), _FLEET_UNAVAILABLE)
    pressure = _mapping(raw_data.get(_FIELD_PRESSURE), _FLEET_UNAVAILABLE)
    if ready.get(_FIELD_OK) is not True or pressure.get(_FIELD_ADMISSION_ALLOWED) is not True:
        raise RuntimeError(_FLEET_NOT_READY)
    _require_fresh(raw_data.get(_FIELD_LAST_SUCCESSFUL_TICK), maximum_age_seconds=_FLEET_STALE_SECONDS)
    queues = _sequence(raw_data.get(_FIELD_QUEUES), _FLEET_UNAVAILABLE)
    scoped_queues = _sequence(raw_data.get(_FIELD_SCOPE_QUEUES), _FLEET_UNAVAILABLE)
    ingest_check = _mapping(raw_data.get(_FIELD_INGEST_CHECK), _FLEET_UNAVAILABLE)
    instances = _sequence(raw_data.get(_FIELD_INSTANCES), _FLEET_UNAVAILABLE)
    operations = _mapping(raw_data.get(_FIELD_OPERATIONS), _FLEET_UNAVAILABLE)
    if (
        _has_nonzero_counts(queues, _FIELD_JOBS)
        or _has_nonzero_counts(instances, _FIELD_COUNT)
        or ingest_check.get(_FIELD_OK) is not True
        or _has_nonzero_counts(scoped_queues, _FIELD_JOBS)
        or operations.get(_FIELD_RETRYING) != 0
        or operations.get(_FIELD_DEAD) != 0
    ):
        raise RuntimeError(_FLEET_NOT_QUIESCENT)
    return envelope


def _tart_list() -> tuple[Mapping[str, object], ...]:
    try:
        # Tart owns VM inventory through its CLI; the vendor exposes no Python API.
        result = subprocess.run(
            (_TART_BINARY, _TART_LIST_COMMAND, _TART_FORMAT_OPTION, _JSON_FORMAT),
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding=_UTF8,
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(_TART_UNAVAILABLE) from exc
    if result.returncode != 0:
        raise RuntimeError(_TART_UNAVAILABLE)
    try:
        rows = _sequence(json.loads(result.stdout), _TART_UNAVAILABLE)
    except json.JSONDecodeError as exc:
        raise RuntimeError(_TART_UNAVAILABLE) from exc
    parsed: list[Mapping[str, object]] = []
    for row in rows:
        current = _mapping(row, _TART_UNAVAILABLE)
        if not isinstance(current.get(_FIELD_TART_NAME), str):
            raise RuntimeError(_TART_UNAVAILABLE)
        parsed.append(current)
    return tuple(parsed)


def _vm_names(rows: Sequence[Mapping[str, object]]) -> set[str]:
    return {cast(str, row[_FIELD_TART_NAME]) for row in rows}


def _record_path(state: Path) -> Path:
    return state / _PROOF_RECORD


def _read_record(state: Path) -> ProofOwnership | None:
    path = _record_path(state)
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise RuntimeError(_RECORD_INVALID)
    try:
        raw = json.loads(path.read_text(encoding=_UTF8))
        value = _mapping(raw, _RECORD_INVALID)
        schema_version = value.get(_FIELD_SCHEMA)
        cpu = value.get(_FIELD_CPU)
        memory_mib = value.get(_FIELD_MEMORY)
        phase = Phase(_required_string(value, _FIELD_PHASE))
        installer_value = _optional_string(value, _FIELD_INSTALLER_RESULT)
        cleanup_value = _optional_string(value, _FIELD_CLEANUP_RESULT)
        installer_result = InstallerResult(installer_value) if installer_value is not None else None
        cleanup_result = CleanupResult(cleanup_value) if cleanup_value is not None else None
        cleanup_observed_at = _optional_string(value, _FIELD_CLEANUP_OBSERVED)
        cleanup_failed_at = _optional_string(value, _FIELD_CLEANUP_FAILED)
        if (
            not isinstance(schema_version, int)
            or isinstance(schema_version, bool)
            or schema_version != _RECORD_SCHEMA_VERSION
            or not isinstance(cpu, int)
            or isinstance(cpu, bool)
            or not isinstance(memory_mib, int)
            or isinstance(memory_mib, bool)
            or (cleanup_result is CleanupResult.FAILURE) != (cleanup_failed_at is not None)
        ):
            raise RuntimeError(_RECORD_INVALID)
        run_id = _required_string(value, _FIELD_RUN_ID)
        run_attempt = _required_string(value, _FIELD_RUN_ATTEMPT)
        vm_name = _required_string(value, _FIELD_VM_NAME)
        base_image = _required_string(value, _FIELD_BASE_IMAGE)
        expected_vm_name = _VM_NAME_PATTERN.format(prefix=_TART_INVENTORY_PREFIX, run_id=run_id, attempt=run_attempt)
        if not run_id or not run_attempt or vm_name != expected_vm_name or not base_image:
            raise RuntimeError(_RECORD_INVALID)
        if cpu < 1 or memory_mib < 1:
            raise RuntimeError(_RECORD_INVALID)
        return ProofOwnership(
            schema_version=schema_version,
            run_id=run_id,
            run_attempt=run_attempt,
            vm_name=vm_name,
            base_image=base_image,
            cpu=cpu,
            memory_mib=memory_mib,
            phase=phase,
            created_at=_required_string(value, _FIELD_CREATED),
            updated_at=_required_string(value, _FIELD_UPDATED),
            installer_result=installer_result,
            cleanup_result=cleanup_result,
            cleanup_observed_at=cleanup_observed_at,
            cleanup_failed_at=cleanup_failed_at,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(_RECORD_INVALID) from exc


def _write_record(state: Path, record: ProofOwnership) -> None:
    path = _record_path(state)
    payload = json.dumps(asdict(record), sort_keys=True, indent=_JSON_INDENT) + _NEWLINE
    descriptor, temporary = tempfile.mkstemp(prefix=_PROOF_RECORD, dir=state)
    temporary_path = Path(temporary)
    try:
        os.fchmod(descriptor, _LOCK_MODE)
        with os.fdopen(descriptor, _FILE_MODE, encoding=_UTF8) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
        directory_fd = os.open(state, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _exclusive_record(state: Path) -> int:
    descriptor = os.open(state / _LOCK_FILE, os.O_CREAT | os.O_RDWR, _LOCK_MODE)
    os.fchmod(descriptor, _LOCK_MODE)
    fcntl.flock(descriptor, _LOCK_EXCLUSIVE)
    return descriptor


def _measure_host(proof_cpu: int, proof_memory_mib: int) -> Mapping[str, object]:
    if proof_cpu < 1 or proof_memory_mib < 1:
        raise RuntimeError(_HOST_RESOURCE_INPUT_INVALID)
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage(str(Path.home()))
    cpus = psutil.cpu_count() or 0
    load = os.getloadavg()[0] if hasattr(os, _LOAD_AVERAGE_ATTRIBUTE) else 0.0
    available_mib = int(memory.available // 1024**2)
    free_gib = int(disk.free // 1024**3)
    if (
        available_mib < proof_memory_mib + _HOST_MEMORY_RESERVE_MIB
        or free_gib < _HOST_DISK_MIN_GIB
        or cpus < proof_cpu + _HOST_CPU_RESERVE
        or load / cpus > _HOST_LOAD_PER_CPU_MAX
    ):
        raise RuntimeError(_HOST_PRESSURE)
    return {
        _HOST_REPORT_AVAILABLE_MEMORY: available_mib,
        _HOST_REPORT_USED_SWAP: int(swap.used // 1024**2),
        _HOST_REPORT_FREE_DISK: free_gib,
        _HOST_REPORT_CPU_COUNT: cpus,
        _HOST_REPORT_LOAD_PER_CPU: load / cpus,
    }


def _assert_inventory_clear(record: ProofOwnership | None) -> None:
    names = _vm_names(_tart_list())
    if record is not None and record.phase != Phase.SETTLED:
        if record.vm_name in names:
            raise RuntimeError(_TART_VM_PRESENT)
    unowned = {name for name in names if name.startswith(_TART_INVENTORY_PREFIX)}
    if unowned:
        raise RuntimeError(_TART_UNKNOWN_VM)


def _wait_for_disposal(record: ProofOwnership | None) -> None:
    deadline = time.monotonic() + _FLEET_DISPOSAL_TIMEOUT_SECONDS
    retryable = {_FLEET_NOT_QUIESCENT, _TART_VM_PRESENT}
    last_observation: RuntimeError | None = None
    while True:
        try:
            _assert_fleet_quiescent()
            _assert_inventory_clear(record)
            return
        except RuntimeError as exc:
            if str(exc) not in retryable:
                raise
            last_observation = exc
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(f"{_FLEET_DISPOSAL_TIMEOUT}: {last_observation}") from last_observation
        time.sleep(min(_FLEET_DISPOSAL_POLL_SECONDS, remaining))


def _recover_record(state: Path, record: ProofOwnership) -> ProofOwnership:
    inventory = _tart_list()
    names = _vm_names(inventory)
    if record.vm_name in names:
        vm = next(row for row in inventory if row.get(_FIELD_TART_NAME) == record.vm_name)
        running = vm.get(_TART_RUNNING_KEY)
        if not isinstance(running, bool):
            raise RuntimeError(_TART_UNAVAILABLE)
        if running:
            _run_owned_tart((_TART_STOP_COMMAND, record.vm_name))
        _run_owned_tart((_TART_DELETE_COMMAND, record.vm_name))
        names = _vm_names(_tart_list())
        if record.vm_name in names:
            raise RuntimeError(_TART_VM_PRESENT)
    recovered = ProofOwnership(
        schema_version=_RECORD_SCHEMA_VERSION,
        run_id=record.run_id,
        run_attempt=record.run_attempt,
        vm_name=record.vm_name,
        base_image=record.base_image,
        cpu=record.cpu,
        memory_mib=record.memory_mib,
        phase=Phase.SETTLED,
        created_at=record.created_at,
        updated_at=_now(),
        installer_result=record.installer_result,
        cleanup_result=record.cleanup_result or CleanupResult.RECOVERED,
        cleanup_observed_at=_now(),
        cleanup_failed_at=record.cleanup_failed_at,
    )
    _write_record(state, recovered)
    return recovered


def _run_owned_tart(arguments: tuple[str, ...]) -> None:
    try:
        # Tart owns stop/delete lifecycle through its CLI; the vendor exposes no Python API.
        result = subprocess.run(
            (_TART_BINARY, *arguments),
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(_TART_UNAVAILABLE) from exc
    if result.returncode != 0:
        raise RuntimeError(_TART_VM_PRESENT)


def admit(proof_cpu: int, proof_memory_mib: int) -> None:
    state = _host_root()
    lock = _exclusive_record(state)
    try:
        record = _read_record(state)
        if record is not None and record.phase != Phase.SETTLED:
            record = _recover_record(state, record)
        _wait_for_disposal(record)
        host = _measure_host(proof_cpu, proof_memory_mib)
    finally:
        os.close(lock)
    report = {
        _REPORT_ADMITTED: True,
        _REPORT_FLEET: _REPORT_FLEET_READY,
        _REPORT_HOST: host,
        _REPORT_RECOVERY: None if record is None else record.cleanup_result,
    }
    print(json.dumps(report, sort_keys=True), flush=True)


def begin_proof(run_id: str, run_attempt: str, vm_name: str, base_image: str, cpu: int, memory_mib: int) -> None:
    state = _host_root()
    lock = _exclusive_record(state)
    try:
        record = _read_record(state)
        if record is not None and record.phase != Phase.SETTLED:
            raise RuntimeError(_RECORD_EXISTS)
        _wait_for_disposal(record)
        _measure_host(cpu, memory_mib)
        expected_vm_name = _VM_NAME_PATTERN.format(prefix=_TART_INVENTORY_PREFIX, run_id=run_id, attempt=run_attempt)
        if vm_name != expected_vm_name or not run_id or not run_attempt or not base_image or cpu < 1 or memory_mib < 1:
            raise RuntimeError(_RECORD_MISMATCH)
        now = _now()
        intent = ProofOwnership(
            schema_version=_RECORD_SCHEMA_VERSION,
            run_id=run_id,
            run_attempt=run_attempt,
            vm_name=vm_name,
            base_image=base_image,
            cpu=cpu,
            memory_mib=memory_mib,
            phase=Phase.CREATE_INTENT,
            created_at=now,
            updated_at=now,
        )
        _write_record(state, intent)
    finally:
        os.close(lock)
    print(json.dumps(asdict(intent), sort_keys=True), flush=True)


def mark_created(vm_name: str) -> None:
    state = _host_root()
    lock = _exclusive_record(state)
    try:
        record = _read_record(state)
        if record is None or record.vm_name != vm_name or record.phase != Phase.CREATE_INTENT:
            raise RuntimeError(_RECORD_MISMATCH)
        if vm_name not in _vm_names(_tart_list()):
            raise RuntimeError(_TART_VM_MISSING)
        created = ProofOwnership(
            schema_version=record.schema_version,
            run_id=record.run_id,
            run_attempt=record.run_attempt,
            vm_name=record.vm_name,
            base_image=record.base_image,
            cpu=record.cpu,
            memory_mib=record.memory_mib,
            phase=Phase.CREATED,
            created_at=record.created_at,
            updated_at=_now(),
            installer_result=record.installer_result,
            cleanup_result=record.cleanup_result,
            cleanup_observed_at=record.cleanup_observed_at,
        )
        _write_record(state, created)
    finally:
        os.close(lock)
    print(json.dumps(asdict(created), sort_keys=True), flush=True)


def record_installer_outcome(vm_name: str, result: InstallerResult) -> None:
    state = _host_root()
    lock = _exclusive_record(state)
    try:
        record = _read_record(state)
        if record is None or record.vm_name != vm_name or record.phase == Phase.SETTLED:
            raise RuntimeError(_RECORD_MISMATCH)
        if record.installer_result is not None and record.installer_result != result:
            raise RuntimeError(_RECORD_MISMATCH)
        settled_outcome = ProofOwnership(
            schema_version=record.schema_version,
            run_id=record.run_id,
            run_attempt=record.run_attempt,
            vm_name=record.vm_name,
            base_image=record.base_image,
            cpu=record.cpu,
            memory_mib=record.memory_mib,
            phase=record.phase,
            created_at=record.created_at,
            updated_at=_now(),
            installer_result=result,
            cleanup_result=record.cleanup_result,
            cleanup_observed_at=record.cleanup_observed_at,
            cleanup_failed_at=record.cleanup_failed_at,
        )
        _write_record(state, settled_outcome)
    finally:
        os.close(lock)
    print(json.dumps(asdict(settled_outcome), sort_keys=True), flush=True)


def record_cleanup_failure(vm_name: str) -> None:
    state = _host_root()
    lock = _exclusive_record(state)
    try:
        record = _read_record(state)
        if record is None or record.vm_name != vm_name or record.phase == Phase.SETTLED:
            raise RuntimeError(_RECORD_MISMATCH)
        failed_at = record.cleanup_failed_at or _now()
        failed_cleanup = ProofOwnership(
            schema_version=record.schema_version,
            run_id=record.run_id,
            run_attempt=record.run_attempt,
            vm_name=record.vm_name,
            base_image=record.base_image,
            cpu=record.cpu,
            memory_mib=record.memory_mib,
            phase=record.phase,
            created_at=record.created_at,
            updated_at=_now(),
            installer_result=record.installer_result,
            cleanup_result=CleanupResult.FAILURE,
            cleanup_observed_at=record.cleanup_observed_at,
            cleanup_failed_at=failed_at,
        )
        _write_record(state, failed_cleanup)
    finally:
        os.close(lock)
    print(json.dumps(asdict(failed_cleanup), sort_keys=True), flush=True)


def settle_proof(vm_name: str, result: InstallerResult) -> None:
    state = _host_root()
    lock = _exclusive_record(state)
    try:
        record = _read_record(state)
        if record is None or record.vm_name != vm_name or record.phase not in (Phase.CREATE_INTENT, Phase.CREATED):
            raise RuntimeError(_RECORD_MISMATCH)
        if record.vm_name in _vm_names(_tart_list()):
            raise RuntimeError(_TART_VM_PRESENT)
        if record.installer_result is not None and record.installer_result != result:
            raise RuntimeError(_RECORD_MISMATCH)
        settled = ProofOwnership(
            schema_version=_RECORD_SCHEMA_VERSION,
            run_id=record.run_id,
            run_attempt=record.run_attempt,
            vm_name=record.vm_name,
            base_image=record.base_image,
            cpu=record.cpu,
            memory_mib=record.memory_mib,
            phase=Phase.SETTLED,
            created_at=record.created_at,
            updated_at=_now(),
            installer_result=record.installer_result or result,
            cleanup_result=CleanupResult.SUCCESS,
            cleanup_observed_at=_now(),
            cleanup_failed_at=None,
        )
        _write_record(state, settled)
    finally:
        os.close(lock)
    print(json.dumps(asdict(settled), sort_keys=True), flush=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest=_FIELD_COMMAND, required=True)
    validate = commands.add_parser(_VALIDATE_INPUTS_COMMAND)
    validate.add_argument(_OPTION_PREFIX + _RUNNER_DESTINATION_ARGUMENT, required=True)
    validate.add_argument(_OPTION_PREFIX + _BASE_ARGUMENT, required=True)
    validate.add_argument(_OPTION_PREFIX + _CPU_ARGUMENT, type=int, required=True)
    validate.add_argument(_OPTION_PREFIX + _MEMORY_ARGUMENT, type=int, required=True)
    admit_command = commands.add_parser(_ADMIT_COMMAND)
    admit_command.add_argument(_OPTION_PREFIX + _CPU_ARGUMENT, type=int, required=True)
    admit_command.add_argument(_OPTION_PREFIX + _MEMORY_ARGUMENT, type=int, required=True)
    begin = commands.add_parser(_BEGIN_COMMAND)
    begin.add_argument(_OPTION_PREFIX + _RUN_ID_ARGUMENT, required=True)
    begin.add_argument(_OPTION_PREFIX + _ATTEMPT_ARGUMENT, required=True)
    begin.add_argument(_OPTION_PREFIX + _VM_ARGUMENT, required=True)
    begin.add_argument(_OPTION_PREFIX + _BASE_ARGUMENT, required=True)
    begin.add_argument(_OPTION_PREFIX + _CPU_ARGUMENT, type=int, required=True)
    begin.add_argument(_OPTION_PREFIX + _MEMORY_ARGUMENT, type=int, required=True)
    created = commands.add_parser(_CREATED_COMMAND)
    created.add_argument(_OPTION_PREFIX + _VM_ARGUMENT, required=True)
    outcome = commands.add_parser(_OUTCOME_COMMAND)
    outcome.add_argument(_OPTION_PREFIX + _VM_ARGUMENT, required=True)
    outcome.add_argument(
        _OPTION_PREFIX + _RESULT_ARGUMENT,
        choices=tuple(result.value for result in InstallerResult),
        required=True,
    )
    cleanup_failed = commands.add_parser(_CLEANUP_FAILED_COMMAND)
    cleanup_failed.add_argument(_OPTION_PREFIX + _VM_ARGUMENT, required=True)
    settle = commands.add_parser(_SETTLE_COMMAND)
    settle.add_argument(_OPTION_PREFIX + _VM_ARGUMENT, required=True)
    settle.add_argument(
        _OPTION_PREFIX + _RESULT_ARGUMENT,
        choices=tuple(result.value for result in InstallerResult),
        required=True,
    )
    return parser


def _handle_validate_inputs(args: argparse.Namespace) -> None:
    validate_inputs(
        cast(str, args.runner_destination), cast(str, args.base_image), cast(int, args.cpu), cast(int, args.memory_mib)
    )


def _handle_admit(args: argparse.Namespace) -> None:
    admit(cast(int, args.cpu), cast(int, args.memory_mib))


def _handle_begin(args: argparse.Namespace) -> None:
    begin_proof(
        cast(str, args.run_id),
        cast(str, args.run_attempt),
        cast(str, args.vm_name),
        cast(str, args.base_image),
        cast(int, args.cpu),
        cast(int, args.memory_mib),
    )


def _handle_created(args: argparse.Namespace) -> None:
    mark_created(cast(str, args.vm_name))


def _handle_outcome(args: argparse.Namespace) -> None:
    record_installer_outcome(cast(str, args.vm_name), InstallerResult(cast(str, args.result)))


def _handle_cleanup_failed(args: argparse.Namespace) -> None:
    record_cleanup_failure(cast(str, args.vm_name))


def _handle_settle(args: argparse.Namespace) -> None:
    settle_proof(cast(str, args.vm_name), InstallerResult(cast(str, args.result)))


_GUARD_HANDLERS: dict[GuardCommand, Callable[[argparse.Namespace], None]] = {
    GuardCommand.VALIDATE_INPUTS: _handle_validate_inputs,
    GuardCommand.ADMIT: _handle_admit,
    GuardCommand.BEGIN: _handle_begin,
    GuardCommand.CREATED: _handle_created,
    GuardCommand.OUTCOME: _handle_outcome,
    GuardCommand.CLEANUP_FAILED: _handle_cleanup_failed,
    GuardCommand.SETTLE: _handle_settle,
}


def main(argv: list[str] | None = None) -> int:
    configure_logging(_LOG_APPLICATION_NAME)
    args = _parser().parse_args(argv)
    try:
        _GUARD_HANDLERS[GuardCommand(args.command)](args)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        logger.error(
            _REFUSED_EVENT,
            command=args.command,
            error_kind=type(exc).__name__,
            reason=str(exc),
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
