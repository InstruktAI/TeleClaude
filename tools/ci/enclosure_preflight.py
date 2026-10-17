"""Finite native machine/job preconditions before any provisioning effect."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from tools.ci.enclosure_contract import (
    AdmittedDeadline,
    Field,
    JsonObject,
    JsonValue,
    object_value,
    parse_object,
    positive_integer,
    text,
)
from tools.ci.enclosure_native import NativeQuery, query_native

BUSCTL: Final = "/usr/bin/busctl"
OPTIONS: Final = ("--system", "--json=short", "--no-pager", "--auto-start=no", "--allow-interactive-authorization=no")
CALL: Final = "call"
SYSTEMD: Final = "org.freedesktop.systemd1"
MANAGER_PATH: Final = "/org/freedesktop/systemd1"
MANAGER: Final = "org.freedesktop.systemd1.Manager"
PROPERTIES: Final = "org.freedesktop.DBus.Properties"
UNIT_INTERFACE: Final = "org.freedesktop.systemd1.Unit"
UNIT_PREFIX: Final = "/org/freedesktop/systemd1/unit/"
JOB_PREFIX: Final = "/org/freedesktop/systemd1/job/"
ROOT_PATH: Final = "/"
MACHINE_PREFIX: Final = "systemd-nspawn@"
MACHINE_PATTERN: Final = "systemd-nspawn@*.service"
MACHINE_TEMPLATE: Final = "systemd-nspawn@.service"
SERVICE_SUFFIX: Final = ".service"
MACHINES_TARGET: Final = "machines.target"
ENABLED_STATES: Final = frozenset({"enabled", "enabled-runtime"})
ACTIVATION_TYPES: Final = frozenset({"start", "restart"})
EMPTY: Final = ""
ZERO: Final = "0"
STRINGS: Final = "ss"
ARRAYS: Final = "asas"
LIST_UNITS_SIGNATURE: Final = "a(ssssssouso)"
LIST_JOBS_SIGNATURE: Final = "a(usssoo)"
LIST_FILES_SIGNATURE: Final = "a(ss)"
VARIANT: Final = "v"
BOOLEAN: Final = "b"
TRANSIENT: Final = "Transient"
TRANSIENT_STATE: Final = "transient"
NANOSECONDS: Final = 1_000_000_000
TIMEOUT: Final = "--timeout={seconds}s"
ERROR_DATA: Final = "the native initial machine/job read is malformed, incomplete or late"
ERROR_BLOCKED: Final = (
    "initial owned-name collision or foreign machine/pending activation blocks this provisioning boundary"
)


class Member(StrEnum):
    """Read-only fixed native calls, separate from the original continuous observer's interface."""

    UNITS = "ListUnitsByPatterns"
    JOBS = "ListJobs"
    FILES = "ListUnitFilesByPatterns"
    GET = "Get"


class Key(StrEnum):
    """Native receipt and precondition facts; no exclusive-origin or admission-fence assertion."""

    TYPE = "type"
    DATA = "data"
    MEMBER = "member"
    OBJECT_PATH = "object_path"
    ARGUMENTS = "arguments"
    REPLY = "reply"
    STARTED_NS = "started_ns"
    OBSERVED_NS = "observed_ns"
    NAME = "name"
    LOAD_STATE = "load_state"
    ACTIVE_STATE = "active_state"
    SUB_STATE = "sub_state"
    FOLLOWING = "following"
    JOB_ID = "job_id"
    JOB_TYPE = "job_type"
    JOB_PATH = "job_path"
    UNIT_PATH = "unit_path"
    STATE = "state"
    TRANSIENT = "transient"
    UNITS = "units"
    FILES = "files"
    JOBS = "jobs"
    RECEIPTS = "receipts"
    COLLISIONS = "collisions"
    FOREIGN_ENABLED = "foreign_enabled"
    FOREIGN_TRANSIENT = "foreign_transient"
    FOREIGN_PENDING = "foreign_pending"
    MACHINES_PENDING = "machines_pending"


@dataclass(frozen=True)
class InitialMachines:
    """An explicitly positioned initial snapshot, never settlement or a fence against future activation."""

    units: tuple[JsonObject, ...]
    files: tuple[JsonObject, ...]
    jobs: tuple[JsonObject, ...]
    receipts: tuple[JsonObject, ...]
    collisions: tuple[str, ...]
    foreign_enabled: tuple[str, ...]
    foreign_transient: tuple[str, ...]
    foreign_pending: tuple[int, ...]
    machines_pending: tuple[int, ...]
    started_ns: int
    observed_ns: int

    def record(self) -> JsonObject:
        """Keep all current facts, including blockers, distinct from the original observer's later history."""
        return {
            Key.UNITS: list[JsonValue](self.units),
            Key.FILES: list[JsonValue](self.files),
            Key.JOBS: list[JsonValue](self.jobs),
            Key.RECEIPTS: list[JsonValue](self.receipts),
            Key.COLLISIONS: list[JsonValue](self.collisions),
            Key.FOREIGN_ENABLED: list[JsonValue](self.foreign_enabled),
            Key.FOREIGN_TRANSIENT: list[JsonValue](self.foreign_transient),
            Key.FOREIGN_PENDING: list[JsonValue](self.foreign_pending),
            Key.MACHINES_PENDING: list[JsonValue](self.machines_pending),
            Key.STARTED_NS: self.started_ns,
            Key.OBSERVED_NS: self.observed_ns,
        }


class InitialMachinesBlocked(RuntimeError):
    """Preserve the actual initial receipts when a concrete precondition fails."""

    def __init__(self, snapshot: InitialMachines) -> None:
        super().__init__(ERROR_BLOCKED)
        self.snapshot = snapshot


def _machine(name: str) -> bool:
    return name.startswith(MACHINE_PREFIX) and name.endswith(SERVICE_SUFFIX) and name != MACHINE_TEMPLATE


def _unit_path(value: JsonValue) -> str:
    if not isinstance(value, str) or not value.startswith(UNIT_PREFIX) or value == UNIT_PREFIX:
        raise ValueError(ERROR_DATA)
    return value


def _read(
    member: Member,
    signature: str,
    arguments: tuple[str, ...],
    expected: str,
    query: NativeQuery,
    deadline: AdmittedDeadline,
    cap: int,
    receipts: list[JsonObject],
    *,
    path: str = MANAGER_PATH,
) -> list[JsonValue]:
    end = deadline.command_end(cap)
    started = time.monotonic_ns()
    seconds = (end - started) / NANOSECONDS
    interface = PROPERTIES if member is Member.GET else MANAGER
    raw = query_native(
        (
            BUSCTL,
            *OPTIONS,
            TIMEOUT.format(seconds=seconds),
            CALL,
            SYSTEMD,
            path,
            interface,
            member.value,
            signature,
            *arguments,
        ),
        query,
        AdmittedDeadline(deadline.outer_end_ns, deadline.vector_end_ns, end),
        cap,
    )
    response = parse_object(raw)
    data = response.get(Key.DATA)
    if response.get(Key.TYPE) != expected or not isinstance(data, list):
        raise ValueError(ERROR_DATA)
    receipts.append(
        {
            Key.MEMBER: member.value,
            Key.OBJECT_PATH: path,
            Key.ARGUMENTS: list[JsonValue](arguments),
            Field.SHA256: hashlib.sha256(raw).hexdigest(),
            Key.REPLY: response,
            Key.STARTED_NS: started,
            Key.OBSERVED_NS: time.monotonic_ns(),
        }
    )
    return data


def _array(data: list[JsonValue]) -> list[JsonValue]:
    if len(data) != 1 or not isinstance(data[0], list):
        raise ValueError(ERROR_DATA)
    return data[0]


def _loaded(value: JsonValue) -> JsonObject:
    if (
        not isinstance(value, list)
        or len(value) != 10
        or any(not isinstance(item, str) for item in (*value[:7], *value[8:]))
    ):
        raise ValueError(ERROR_DATA)
    name, _description, load, active, sub, following, path, job, job_type, job_path = value
    if (
        not isinstance(name, str)
        or not name
        or Path(name).name != name
        or type(job) is not int
        or not 0 <= job <= 0xFFFFFFFF
        or (job == 0 and (job_type != EMPTY or job_path != ROOT_PATH))
        or (job != 0 and job_path != JOB_PREFIX + str(job))
    ):
        raise ValueError(ERROR_DATA)
    return {
        Key.NAME: name,
        Key.LOAD_STATE: load,
        Key.ACTIVE_STATE: active,
        Key.SUB_STATE: sub,
        Key.FOLLOWING: following,
        Key.UNIT_PATH: _unit_path(path),
        Key.JOB_ID: job,
        Key.JOB_TYPE: job_type,
        Key.JOB_PATH: job_path,
    }


def _job(value: JsonValue) -> JsonObject:
    if (
        not isinstance(value, list)
        or len(value) != 6
        or any(not isinstance(item, str) or not item for item in value[1:])
    ):
        raise ValueError(ERROR_DATA)
    identifier, name, job_type, state, path, unit_path = value
    if type(identifier) is not int or not 0 < identifier <= 0xFFFFFFFF or path != JOB_PREFIX + str(identifier):
        raise ValueError(ERROR_DATA)
    return {
        Key.JOB_ID: identifier,
        Key.NAME: name,
        Key.JOB_TYPE: job_type,
        Key.STATE: state,
        Key.JOB_PATH: path,
        Key.UNIT_PATH: _unit_path(unit_path),
    }


def inspect_initial_machines(
    owned_units: frozenset[str],
    query: NativeQuery,
    deadline: AdmittedDeadline,
    cap: int,
) -> InitialMachines:
    """Read existing units/files/jobs once; never load a proposed unit or infer a future fence from absence."""
    started = time.monotonic_ns()
    if not owned_units or any(not name or Path(name).name != name for name in owned_units):
        raise ValueError(ERROR_DATA)
    receipts: list[JsonObject] = []
    patterns = (MACHINE_PATTERN, MACHINES_TARGET, *sorted(owned_units))
    arguments = (ZERO, str(len(patterns)), *patterns)
    units = tuple(
        _loaded(value)
        for value in _array(
            _read(Member.UNITS, ARRAYS, arguments, LIST_UNITS_SIGNATURE, query, deadline, cap, receipts)
        )
    )
    files: list[JsonObject] = []
    for value in _array(_read(Member.FILES, ARRAYS, arguments, LIST_FILES_SIGNATURE, query, deadline, cap, receipts)):
        if (
            not isinstance(value, list)
            or len(value) != 2
            or any(not isinstance(item, str) or not item for item in value)
        ):
            raise ValueError(ERROR_DATA)
        path, state = value
        if not isinstance(path, str) or not Path(path).is_absolute():
            raise ValueError(ERROR_DATA)
        files.append({Field.PATH: path, Key.NAME: Path(path).name, Key.STATE: state})
    jobs = tuple(
        _job(value)
        for value in _array(_read(Member.JOBS, EMPTY, (), LIST_JOBS_SIGNATURE, query, deadline, cap, receipts))
    )
    transient: set[str] = set()
    for unit in units:
        name = unit[Key.NAME]
        if not isinstance(name, str) or not _machine(name):
            continue
        data = _read(
            Member.GET,
            STRINGS,
            (UNIT_INTERFACE, TRANSIENT),
            VARIANT,
            query,
            deadline,
            cap,
            receipts,
            path=_unit_path(unit[Key.UNIT_PATH]),
        )
        if len(data) != 1:
            raise ValueError(ERROR_DATA)
        value = object_value(data[0])
        if value.get(Key.TYPE) != BOOLEAN or type(value.get(Key.DATA)) is not bool:
            raise ValueError(ERROR_DATA)
        unit[Key.TRANSIENT] = value[Key.DATA]
        if value[Key.DATA] is True:
            transient.add(name)
    collisions = {text(row, Key.NAME) for row in (*units, *files, *jobs) if text(row, Key.NAME) in owned_units}
    enabled = {
        text(row, Key.NAME) for row in files if _machine(text(row, Key.NAME)) and text(row, Key.STATE) in ENABLED_STATES
    }
    transient.update(
        text(row, Key.NAME) for row in files if _machine(text(row, Key.NAME)) and row[Key.STATE] == TRANSIENT_STATE
    )
    foreign_pending = tuple(
        positive_integer(row, Key.JOB_ID)
        for row in jobs
        if _machine(text(row, Key.NAME)) and text(row, Key.NAME) not in owned_units
    )
    machines_pending = tuple(
        positive_integer(row, Key.JOB_ID)
        for row in jobs
        if row[Key.NAME] == MACHINES_TARGET and text(row, Key.JOB_TYPE) in ACTIVATION_TYPES
    )
    if time.monotonic_ns() >= deadline.effective_end():
        raise TimeoutError(ERROR_DATA)
    return InitialMachines(
        units,
        tuple(files),
        jobs,
        tuple(receipts),
        tuple(sorted(collisions)),
        tuple(sorted(enabled - owned_units)),
        tuple(sorted(transient - owned_units)),
        foreign_pending,
        machines_pending,
        started,
        time.monotonic_ns(),
    )


def require_initial_machines(snapshot: InitialMachines, *, container_installed: bool) -> None:
    """Preserve the recipe's extra foreign-enabled/transient/target check specifically for an absent-container install."""
    if (
        snapshot.collisions
        or snapshot.foreign_pending
        or (
            not container_installed
            and (snapshot.foreign_enabled or snapshot.foreign_transient or snapshot.machines_pending)
        )
    ):
        raise InitialMachinesBlocked(snapshot)
