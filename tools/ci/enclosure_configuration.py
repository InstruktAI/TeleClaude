"""Effective pre-mask instance configuration through the original manager connection."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from tools.ci.enclosure_actions import Template
from tools.ci.enclosure_contract import (
    AdmittedDeadline,
    Field,
    JsonObject,
    JsonValue,
    Parameter,
    StaticPackage,
    object_value,
    parse_object,
    text,
)
from tools.ci.enclosure_host import Key as HostKey
from tools.ci.enclosure_host import Kind, _locked_file
from tools.ci.enclosure_manager import ACTIVE, Property, UnitRead
from tools.ci.enclosure_owner import Key as OwnerKey
from tools.ci.enclosure_owner import RunOwner

ROOT: Final = Path("/")
EMPTY: Final = ""
LOADED: Final = "loaded"
NO_RESTART: Final = "no"
NOTIFY: Final = "notify"
MIXED: Final = "mixed"
SUPERVISOR: Final = "supervisor"
MACHINES_TARGET: Final = "machines.target"
VENDOR_TEMPLATE: Final = "usr/lib/systemd/system/systemd-nspawn@.service"
NSPAWN: Final = "systemd-nspawn"
NSPAWN_OPTIONS: Final = (
    "--quiet",
    "--keep-unit",
    "--boot",
    "--link-journal=try-guest",
    "--network-veth",
    "-U",
    "--settings=override",
)
MACHINE_OPTION: Final = "--machine={name}"
MODULE_UNITS: Final = frozenset({"modprobe@tun.service", "modprobe@loop.service", "modprobe@dm_mod.service"})
ERROR_CONFIGURATION: Final = "the original instance's effective pre-mask configuration differs from the declared recipe"


class Key(StrEnum):
    """Native effective properties and positioned evidence of this bounded configuration read."""

    UNIT_DESTINATIONS = "unit_destinations"
    ID = "Id"
    NAMES = "Names"
    LOAD_STATE = "LoadState"
    SOURCE_PATH = "SourcePath"
    FRAGMENT_PATH = "FragmentPath"
    DROP_IN_PATHS = "DropInPaths"
    TRANSIENT = "Transient"
    NEED_RELOAD = "NeedDaemonReload"
    STOP_WHEN_UNNEEDED = "StopWhenUnneeded"
    ON_SUCCESS = "OnSuccess"
    ON_FAILURE = "OnFailure"
    REQUIRES = "Requires"
    WANTS = "Wants"
    REQUISITE = "Requisite"
    BINDS_TO = "BindsTo"
    UPHOLDS = "Upholds"
    PART_OF = "PartOf"
    REQUIRED_BY = "RequiredBy"
    WANTED_BY = "WantedBy"
    REQUISITE_OF = "RequisiteOf"
    BOUND_BY = "BoundBy"
    UPHELD_BY = "UpheldBy"
    TRIGGERS = "Triggers"
    TRIGGERED_BY = "TriggeredBy"
    BEFORE = "Before"
    AFTER = "After"
    REQUIRES_MOUNTS_FOR = "RequiresMountsFor"
    SLICE = "Slice"
    TYPE = "Type"
    KILL_MODE = "KillMode"
    RESTART = "Restart"
    FORCE_RESTART = "RestartForceExitStatus"
    TIMEOUT_STOP = "TimeoutStopUSec"
    DELEGATE = "Delegate"
    DELEGATE_SUBGROUP = "DelegateSubgroup"
    EXEC_START = "ExecStart"
    EXEC_START_PRE = "ExecStartPre"
    EXEC_START_POST = "ExecStartPost"
    EXEC_STOP = "ExecStop"
    EXEC_STOP_POST = "ExecStopPost"
    EXEC_RELOAD = "ExecReload"
    EXEC_CONDITION = "ExecCondition"
    BEGIN_SEQUENCE = "begin_sequence"
    SEQUENCE = "sequence"
    OBSERVED_NS = "observed_ns"
    PARENT_UNIT = "parent_unit"
    PARENT_OBJECT_PATH = "parent_object_path"
    GUEST_UNIT = "guest_unit"
    GUEST_OBJECT_PATH = "guest_object_path"
    FILES = "files"


RELATIONSHIPS: Final = (
    Key.REQUIRES,
    Key.WANTS,
    Key.REQUISITE,
    Key.BINDS_TO,
    Key.UPHOLDS,
    Key.PART_OF,
    Key.REQUIRED_BY,
    Key.WANTED_BY,
    Key.REQUISITE_OF,
    Key.BOUND_BY,
    Key.UPHELD_BY,
    Key.TRIGGERS,
    Key.TRIGGERED_BY,
    Key.BEFORE,
    Key.AFTER,
    Key.ON_SUCCESS,
    Key.ON_FAILURE,
)
EMPTY_EXEC: Final = (
    Key.EXEC_START_PRE,
    Key.EXEC_START_POST,
    Key.EXEC_STOP,
    Key.EXEC_STOP_POST,
    Key.EXEC_RELOAD,
    Key.EXEC_CONDITION,
)
NO_ACTIVATORS: Final = (Key.WANTED_BY, Key.REQUIRED_BY, Key.REQUISITE_OF, Key.BOUND_BY, Key.UPHELD_BY, Key.TRIGGERED_BY)


@dataclass(frozen=True)
class InstanceConfiguration:
    """Positive instance properties and actual graph edges; no admission seal or complete creator census."""

    parent: UnitRead
    guest: UnitRead
    files: tuple[JsonObject, ...]
    begin_sequence: int
    sequence: int
    observed_ns: int

    def record(self) -> JsonObject:
        """Reference the same native unit reads already retained in the action evidence, without duplicating them."""
        return {
            Key.PARENT_UNIT: self.parent.name,
            Key.PARENT_OBJECT_PATH: self.parent.object_path,
            Key.GUEST_UNIT: self.guest.name,
            Key.GUEST_OBJECT_PATH: self.guest.object_path,
            Property.INVOCATION_ID: self.guest.unit.get(Property.INVOCATION_ID),
            Key.FILES: list[JsonValue](self.files),
            Key.BEGIN_SEQUENCE: self.begin_sequence,
            Key.SEQUENCE: self.sequence,
            Key.OBSERVED_NS: self.observed_ns,
        }


def _strings(read: UnitRead, key: Key) -> frozenset[str]:
    value = read.unit.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(ERROR_CONFIGURATION)
    names = frozenset(text_value for text_value in value if isinstance(text_value, str))
    if len(names) != len(value):
        raise ValueError(ERROR_CONFIGURATION)
    return names


def _common(read: UnitRead, fragment: str, drop_in: tuple[str, ...]) -> None:
    if (
        read.unit.get(Key.ID) != read.name
        or _strings(read, Key.NAMES) != frozenset({read.name})
        or read.unit.get(Key.LOAD_STATE) != LOADED
        or read.unit.get(Property.ACTIVE_STATE) != ACTIVE
        or read.unit.get(Key.SOURCE_PATH) != EMPTY
        or read.unit.get(Key.FRAGMENT_PATH) != fragment
        or _strings(read, Key.DROP_IN_PATHS) != frozenset(drop_in)
        or read.unit.get(Key.TRANSIENT) is not False
        or read.unit.get(Key.NEED_RELOAD) is not False
        or _strings(read, Key.ON_SUCCESS)
        or _strings(read, Key.ON_FAILURE)
    ):
        raise ValueError(ERROR_CONFIGURATION)
    for key in RELATIONSHIPS:
        _strings(read, key)


def _vendor(package: StaticPackage) -> JsonObject:
    rows = parse_object(package.lock_bytes)[HostKey.ACTIVATION_SOURCES]
    if not isinstance(rows, list):
        raise ValueError(ERROR_CONFIGURATION)
    found = [
        object_value(value)
        for value in rows
        if object_value(value).get(HostKey.SCOPE) == HostKey.HOST
        and object_value(value).get(Field.PATH) == VENDOR_TEMPLATE
    ]
    if len(found) != 1 or found[0].get(HostKey.KIND) != Kind.FILE:
        raise ValueError(ERROR_CONFIGURATION)
    return found[0]


def _start_command(guest: UnitRead, machine: str) -> None:
    commands = guest.specific.get(Key.EXEC_START)
    if not isinstance(commands, list) or len(commands) != 1:
        raise ValueError(ERROR_CONFIGURATION)
    command = commands[0]
    argv = [NSPAWN, *NSPAWN_OPTIONS, MACHINE_OPTION.format(name=machine)]
    if (
        not isinstance(command, list)
        or len(command) != 10
        or command[0] != NSPAWN
        or command[1] != argv
        or command[2] is not False
        or any(guest.specific.get(key) != [] for key in EMPTY_EXEC)
    ):
        raise ValueError(ERROR_CONFIGURATION)


def inspect_instance_configuration(
    owner: RunOwner,
    package: StaticPackage,
    parent: UnitRead,
    guest: UnitRead,
    deadline: AdmittedDeadline,
) -> InstanceConfiguration:
    """Consume the original observer's positioned reads; check fixed bytes/effective predicates before masking."""
    end_ns = deadline.effective_end()
    if time.monotonic_ns() >= end_ns:
        raise TimeoutError(ERROR_CONFIGURATION)
    record = parse_object(owner.manifest_bytes)
    if parent.name != text(record, OwnerKey.PARENT_UNIT) or guest.name != text(record, OwnerKey.GUEST_UNIT):
        raise ValueError(ERROR_CONFIGURATION)
    destinations = object_value(parse_object(package.recipe_bytes)[Key.UNIT_DESTINATIONS])
    parameters = {Parameter.RUN_TOKEN.value: owner.journal.binding.run_token}
    paths = {template: text(destinations, template).format_map(parameters) for template in Template}
    _common(parent, paths[Template.PARENT], ())
    _common(guest, str(ROOT / VENDOR_TEMPLATE), (paths[Template.INSTANCE],))
    if (
        parent.unit.get(Key.STOP_WHEN_UNNEEDED) is not False
        or parent.specific.get(Key.DELEGATE) is not False
        or guest.specific.get(Key.SLICE) != parent.name
        or guest.specific.get(Key.RESTART) != NO_RESTART
        or guest.specific.get(Key.FORCE_RESTART) != [[], []]
        or guest.specific.get(Key.TYPE) != NOTIFY
        or guest.specific.get(Key.KILL_MODE) != MIXED
        or guest.specific.get(Key.DELEGATE) is not True
        or guest.specific.get(Key.DELEGATE_SUBGROUP) != SUPERVISOR
        or type(guest.specific.get(Key.TIMEOUT_STOP)) is not int
        or guest.specific[Key.TIMEOUT_STOP] != 240_000_000
        or _strings(guest, Key.WANTS) != MODULE_UNITS
        or _strings(guest, Key.PART_OF) != frozenset({MACHINES_TARGET})
        or guest.unit.get(Key.REQUIRES_MOUNTS_FOR) != [text(record, OwnerKey.ROOTFS)]
        or any(_strings(guest, key) for key in NO_ACTIVATORS)
    ):
        raise ValueError(ERROR_CONFIGURATION)
    _start_command(guest, Path(text(record, OwnerKey.ROOTFS)).name)
    files: list[JsonObject] = []
    rendered = package.render(
        run_token=owner.journal.binding.run_token,
        candidate_sha=owner.journal.binding.candidate_commit,
        candidate_tree=owner.journal.binding.candidate_tree,
        selection=EMPTY,
    )
    vendor = _vendor(package)
    _locked_file(vendor, deadline)
    files.append(
        {Field.PATH: str(ROOT / VENDOR_TEMPLATE), Field.SHA256: vendor[Field.SHA256], Field.BYTES: vendor[Field.BYTES]}
    )
    for template in Template:
        data = rendered[template]
        row: JsonObject = {
            Field.PATH: str(Path(paths[template]).relative_to(ROOT)),
            HostKey.KIND: Kind.FILE.value,
            Field.SHA256: hashlib.sha256(data).hexdigest(),
            Field.BYTES: len(data),
        }
        _locked_file(row, deadline)
        files.append({**row, Field.PATH: paths[template]})
    if time.monotonic_ns() >= end_ns:
        raise ValueError(ERROR_CONFIGURATION)
    return InstanceConfiguration(
        parent,
        guest,
        tuple(files),
        min(parent.begin_sequence, guest.begin_sequence),
        max(parent.sequence, guest.sequence),
        time.monotonic_ns(),
    )
