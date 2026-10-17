"""One-connection system-manager observations for the acceptance enclosure."""

from __future__ import annotations

import asyncio
import json
import math
import time
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol, cast

from dbus_next.aio.message_bus import MessageBus
from dbus_next.constants import BusType, MessageType
from dbus_next.message import Message
from dbus_next.signature import Variant

from tools.ci.enclosure_contract import JsonObject, JsonValue
from tools.ci.enclosure_journal import BOOT_ID
from tools.ci.enclosure_population import Invalidation, PopulationObserver

UTF8: Final = "utf-8"
EMPTY: Final = ""
NANOSECONDS: Final = 1_000_000_000
BUS_PATH: Final = "/org/freedesktop/DBus"
MANAGER_PATH: Final = "/org/freedesktop/systemd1"
SYSTEMD_NAME: Final = "org.freedesktop.systemd1"
ACTIVE: Final = "active"
JOB_DONE: Final = "done"
PATH_SEPARATOR: Final = "/"
BOOT_IDENTITY_ERROR: Final = "the original boot identity changed or is unavailable"
CALL_ERROR: Final = "invalid or failed native manager reply for {member}: {error}"
BODY_ERROR: Final = "malformed native manager signal or property"
CONNECTION_ERROR: Final = "the original manager observation connection is unavailable or invalidated"
BINDING_ERROR: Final = "the original manager object or invocation binding disagrees"
EVENT_LIMIT: Final = 4096
EVENT_BYTES_LIMIT: Final = 4 * 1024 * 1024
JSON_SEPARATORS: Final = (",", ":")
OWNER_MATCH: Final = "type='signal',sender='org.freedesktop.DBus',interface='org.freedesktop.DBus',member='NameOwnerChanged',arg0='org.freedesktop.systemd1'"
PROPERTIES_MATCH: Final = "type='signal',sender='org.freedesktop.systemd1',interface='org.freedesktop.DBus.Properties'"
MANAGER_MATCH: Final = "type='signal',sender='org.freedesktop.systemd1',interface='org.freedesktop.systemd1.Manager'"
UNIT_REFERENCE_PROPERTIES: Final = (
    "Requires",
    "Wants",
    "Requisite",
    "BindsTo",
    "Upholds",
    "PartOf",
    "ConsistsOf",
    "OnSuccess",
    "OnFailure",
    "RequiredBy",
    "WantedBy",
    "RequisiteOf",
    "BoundBy",
    "UpheldBy",
    "Triggers",
    "TriggeredBy",
    "Before",
    "After",
)


class Interface(StrEnum):
    """The native interfaces admitted by this observation client."""

    BUS = "org.freedesktop.DBus"
    PROPERTIES = "org.freedesktop.DBus.Properties"
    MANAGER = "org.freedesktop.systemd1.Manager"
    UNIT = "org.freedesktop.systemd1.Unit"
    SERVICE = "org.freedesktop.systemd1.Service"
    SLICE = "org.freedesktop.systemd1.Slice"
    JOB = "org.freedesktop.systemd1.Job"


class Member(StrEnum):
    """Closed read/subscription calls and native signals; no workload mutation API."""

    GET_ID = "GetId"
    GET_NAME_OWNER = "GetNameOwner"
    ADD_MATCH = "AddMatch"
    SUBSCRIBE = "Subscribe"
    GET_UNIT = "GetUnit"
    GET_JOB = "GetJob"
    GET_ALL = "GetAll"
    OWNER_CHANGED = "NameOwnerChanged"
    PROPERTIES_CHANGED = "PropertiesChanged"
    UNIT_NEW = "UnitNew"
    UNIT_REMOVED = "UnitRemoved"
    JOB_NEW = "JobNew"
    JOB_REMOVED = "JobRemoved"


class Signature(StrEnum):
    """Wire signatures used at these native protocol boundaries."""

    EMPTY = ""
    STRING = "s"
    OBJECT = "o"
    UINT = "u"
    PROPERTIES = "a{sv}"
    OWNER = "sss"
    PROPERTY_CHANGE = "sa{sv}as"
    UNIT_EVENT = "so"
    JOB_NEW = "uos"
    JOB_REMOVED = "uoss"


class Property(StrEnum):
    """Identity and lifecycle facts with continuous checks on the original objects."""

    ACTIVE_STATE = "ActiveState"
    CONTROL_GROUP = "ControlGroup"
    INVOCATION_ID = "InvocationID"
    JOB = "Job"
    NAMES = "Names"
    ID = "Id"
    UNIT = "Unit"
    JOB_TYPE = "JobType"
    STATE = "State"
    VERSION = "Version"
    UNIT_PATH = "UnitPath"


@dataclass(frozen=True)
class ManagerRead:
    """Properties of the original subscribed manager, positioned in its native event stream."""

    identity: ManagerIdentity
    version: str
    unit_paths: tuple[str, ...]
    begin_sequence: int
    sequence: int
    observed_ns: int


class DisconnectLifecycle(Protocol):
    """Typed boundary for the pinned library's unannotated connection lifecycle."""

    def disconnect(self) -> None:
        """Close the original connection without reconnecting."""

    async def wait_for_disconnect(self) -> None:
        """Observe its actual terminal result."""


@dataclass(frozen=True)
class ManagerIdentity:
    """Bus, manager and kernel identities observed before parent binding."""

    bus_id: str
    manager_owner: str
    boot_id: str


@dataclass(frozen=True)
class UnitRead:
    """Properties read from one original native object, with observation position."""

    name: str
    object_path: str
    unit: Mapping[str, JsonValue]
    specific: Mapping[str, JsonValue]
    begin_sequence: int
    sequence: int
    observed_ns: int


@dataclass(frozen=True)
class NativeEvent:
    """Bounded ordered signal evidence, never a substitute for an action receipt."""

    sequence: int
    observed_ns: int
    object_path: str
    interface: str
    member: str
    signature: str
    body: tuple[JsonValue, ...]


@dataclass(frozen=True)
class JobRead:
    """One accepted native job, observed without treating an absent successor as settlement."""

    identifier: int
    object_path: str
    unit_name: str
    unit_path: str
    properties: Mapping[str, JsonValue]
    begin_sequence: int
    sequence: int
    observed_ns: int


@dataclass(frozen=True)
class AcceptedJob:
    """The exact native job address acknowledged by one admitted manager call."""

    identifier: int
    object_path: str
    unit_name: str
    unit_path: str
    job_type: str


@dataclass(frozen=True)
class SettledJob:
    """An acknowledged job's actual ordered lifecycle on the original subscription."""

    accepted: AcceptedJob
    new_sequence: int
    removed_sequence: int
    result: str


@dataclass(frozen=True)
class JobBoundary:
    """A finite reconciliation point, not a fence against future accepted activation."""

    settled: tuple[SettledJob, ...]
    sequence: int
    observed_ns: int


class ManagerObserver:
    """Never reconnect or replace a bound original object after observation loss."""

    def __init__(self, expected_units: frozenset[str]) -> None:
        if not expected_units or any(not name for name in expected_units):
            raise ValueError(BINDING_ERROR)
        self._expected_units = expected_units
        self._watched_paths: set[str] = set()
        self._bus: MessageBus | None = None
        self._identity: ManagerIdentity | None = None
        self._disconnect_task: asyncio.Task[None] | None = None
        self._population: PopulationObserver | None = None
        self._parent: UnitRead | None = None
        self._guest: UnitRead | None = None
        self._sequence = 0
        self._events: list[NativeEvent] = []
        self._event_bytes = 0
        self._faults: dict[Invalidation, int] = {}
        self._connect_attempted = False
        self._changed = asyncio.Event()

    @property
    def sequence(self) -> int:
        """Position readiness waits in the original stream, without a new subscription."""
        return self._sequence

    async def wait_for_change(self, sequence: int, deadline_ns: int) -> None:
        """Await an original signal or sticky loss; never poll or renew the supplied cutoff."""
        if sequence == self._sequence and not self._faults:
            self._changed.clear()
            async with asyncio.timeout(_remaining(deadline_ns)):
                await self._changed.wait()
        if self._faults:
            raise RuntimeError(CONNECTION_ERROR)

    @property
    def identity(self) -> ManagerIdentity:
        """Expose only a positively established original identity."""
        if self._identity is None:
            raise RuntimeError(CONNECTION_ERROR)
        return self._identity

    @property
    def faults(self) -> Mapping[Invalidation, int]:
        """Return a copy of irreversible continuity losses."""
        return dict(self._faults)

    @property
    def events(self) -> tuple[NativeEvent, ...]:
        """Read the bounded stream prefix without resetting its history."""
        return tuple(self._events)

    def invalidate(self, cause: Invalidation) -> None:
        """Propagate every original-connection loss to the original population observer."""
        if cause not in self._faults:
            self._faults[cause] = time.monotonic_ns()
        self._changed.set()
        if self._population is not None:
            self._population.invalidate(cause)

    async def connect(self, deadline_ns: int) -> ManagerIdentity:
        """Subscribe before binding; a second connection attempt is never admitted."""
        if self._connect_attempted:
            raise RuntimeError(CONNECTION_ERROR)
        self._connect_attempted = True
        boot = BOOT_ID.read_text(encoding=UTF8).strip()
        if not boot:
            raise ValueError(BOOT_IDENTITY_ERROR)
        bus = MessageBus(bus_type=BusType.SYSTEM)
        self._bus = bus
        bus.add_message_handler(self._on_message)
        try:
            async with asyncio.timeout(_remaining(deadline_ns)):
                await bus.connect()
            self._disconnect_task = asyncio.create_task(self._watch_disconnect(bus))
            for rule in (OWNER_MATCH, PROPERTIES_MATCH, MANAGER_MATCH):
                await self._call(
                    Interface.BUS, BUS_PATH, Member.ADD_MATCH, Signature.STRING, [rule], Signature.EMPTY, deadline_ns
                )
            bus_id = await self._call(
                Interface.BUS, BUS_PATH, Member.GET_ID, Signature.EMPTY, [], Signature.STRING, deadline_ns
            )
            owner = await self._call(
                Interface.BUS,
                BUS_PATH,
                Member.GET_NAME_OWNER,
                Signature.STRING,
                [SYSTEMD_NAME],
                Signature.STRING,
                deadline_ns,
            )
            identity = ManagerIdentity(_single_text(bus_id), _single_text(owner), boot)
            self._identity = identity
            await self._call(
                Interface.MANAGER, MANAGER_PATH, Member.SUBSCRIBE, Signature.EMPTY, [], Signature.EMPTY, deadline_ns
            )
            await self.check_identity(deadline_ns)
            return identity
        except BaseException:
            self.invalidate(Invalidation.BUS_DISCONNECTED)
            cast(DisconnectLifecycle, bus).disconnect()
            raise

    async def _watch_disconnect(self, bus: MessageBus) -> None:
        try:
            await cast(DisconnectLifecycle, bus).wait_for_disconnect()
        except Exception:
            self.invalidate(Invalidation.BUS_DISCONNECTED)
        else:
            self.invalidate(Invalidation.BUS_DISCONNECTED)

    async def _call(
        self,
        interface: Interface,
        path: str,
        member: Member,
        signature: Signature,
        body: list[JsonValue],
        expected: Signature,
        deadline_ns: int,
    ) -> Message:
        bus = self._bus
        if bus is None or self._faults:
            raise RuntimeError(CONNECTION_ERROR)
        destination = Interface.BUS.value if interface is Interface.BUS else SYSTEMD_NAME
        message = Message(
            destination=destination,
            path=path,
            interface=interface.value,
            member=member.value,
            signature=signature.value,
            body=body,
        )
        try:
            async with asyncio.timeout(_remaining(deadline_ns)):
                reply = await bus.call(message)
        except BaseException:
            self.invalidate(Invalidation.BUS_DISCONNECTED)
            raise
        if self._faults:
            raise RuntimeError(CONNECTION_ERROR)
        if reply is None or reply.message_type is not MessageType.METHOD_RETURN or reply.signature != expected:
            self.invalidate(Invalidation.MALFORMED_STREAM)
            raise ValueError(CALL_ERROR.format(member=member, error=reply.error_name if reply is not None else EMPTY))
        if (
            self._identity is not None
            and interface is not Interface.BUS
            and reply.sender != self.identity.manager_owner
        ):
            self.invalidate(Invalidation.MANAGER_CHANGED)
            raise ValueError(BINDING_ERROR)
        return reply

    async def check_identity(self, deadline_ns: int) -> None:
        """Check the same connection's original identities; disagreement is irreversible."""
        identity = self.identity
        try:
            boot = BOOT_ID.read_text(encoding=UTF8).strip()
        except OSError:
            self.invalidate(Invalidation.MANAGER_CHANGED)
            raise
        bus = await self._call(
            Interface.BUS, BUS_PATH, Member.GET_ID, Signature.EMPTY, [], Signature.STRING, deadline_ns
        )
        owner = await self._call(
            Interface.BUS,
            BUS_PATH,
            Member.GET_NAME_OWNER,
            Signature.STRING,
            [SYSTEMD_NAME],
            Signature.STRING,
            deadline_ns,
        )
        if (
            boot != identity.boot_id
            or _single_text(bus) != identity.bus_id
            or _single_text(owner) != identity.manager_owner
        ):
            self.invalidate(Invalidation.MANAGER_CHANGED)
            raise ValueError(BINDING_ERROR)

    async def read_manager(self, deadline_ns: int) -> ManagerRead:
        """Read running-manager metadata through the existing original connection and GetAll boundary."""
        if self._identity is None or self._faults:
            raise RuntimeError(CONNECTION_ERROR)
        begin = self._sequence
        reply = await self._call(
            Interface.PROPERTIES,
            MANAGER_PATH,
            Member.GET_ALL,
            Signature.STRING,
            [Interface.MANAGER.value],
            Signature.PROPERTIES,
            deadline_ns,
        )
        try:
            properties = _properties(reply)
            version = properties.get(Property.VERSION)
            paths = properties.get(Property.UNIT_PATH)
            if (
                not isinstance(version, str)
                or not version
                or not isinstance(paths, list)
                or not paths
                or any(not isinstance(path, str) or not path.startswith(PATH_SEPARATOR) for path in paths)
            ):
                raise ValueError(BODY_ERROR)
        except ValueError:
            self.invalidate(Invalidation.MALFORMED_STREAM)
            raise
        # GetAll also contains the manager environment; retain only the metadata this admission consumes.
        return ManagerRead(
            self.identity, version, tuple(cast(list[str], paths)), begin, self._sequence, time.monotonic_ns()
        )

    def reconcile_jobs(self, units: frozenset[str], accepted: tuple[AcceptedJob, ...]) -> JobBoundary:
        """Match every scoped native activation to its original call receipt and ordered terminal signal."""
        if self._identity is None or self._faults:
            raise RuntimeError(CONNECTION_ERROR)
        acknowledged_names = frozenset(job.unit_name for job in accepted)
        if not units or not units <= self._expected_units | acknowledged_names:
            raise ValueError(BINDING_ERROR)
        expected: dict[int, AcceptedJob] = {}
        for job in accepted:
            if (
                type(job.identifier) is not int
                or job.identifier <= 0
                or not job.object_path.startswith(PATH_SEPARATOR)
                or job.unit_name not in units
                or not job.unit_path.startswith(PATH_SEPARATOR)
                or not job.job_type
                or job.identifier in expected
            ):
                raise ValueError(BINDING_ERROR)
            expected[job.identifier] = job
        self._expected_units |= acknowledged_names
        started: dict[int, int] = {}
        settled: dict[int, SettledJob] = {}
        for event in self._events:
            if (
                event.interface != Interface.MANAGER
                or event.member not in (Member.JOB_NEW, Member.JOB_REMOVED)
                or event.body[2] not in units
            ):
                continue
            identifier, path, unit_name = event.body[:3]
            if (
                type(identifier) is not int
                or identifier not in expected
                or path != expected[identifier].object_path
                or unit_name != expected[identifier].unit_name
                or identifier in settled
            ):
                self.invalidate(Invalidation.UNKNOWN_ACTIVATOR)
                raise ValueError(BINDING_ERROR)
            if event.member == Member.JOB_NEW:
                if identifier in started:
                    self.invalidate(Invalidation.UNKNOWN_ACTIVATOR)
                    raise ValueError(BINDING_ERROR)
                started[identifier] = event.sequence
            else:
                result = event.body[3]
                if identifier not in started or result != JOB_DONE:
                    self.invalidate(Invalidation.UNKNOWN_ACTIVATOR)
                    raise ValueError(BINDING_ERROR)
                settled[identifier] = SettledJob(expected[identifier], started[identifier], event.sequence, JOB_DONE)
        if set(settled) != set(expected):
            # An unfinished acknowledged job remains unresolved; a later explicit boundary may see its signal.
            raise ValueError(BINDING_ERROR)
        return JobBoundary(tuple(settled[job.identifier] for job in accepted), self._sequence, time.monotonic_ns())

    async def read_referenced_unit(self, source: UnitRead, name: str, deadline_ns: int) -> UnitRead:
        """Extend this same observer's scope only along actual native unit relationships, retaining earlier signals."""
        if source.name not in self._expected_units or source.object_path not in self._watched_paths:
            raise ValueError(BINDING_ERROR)
        references: set[str] = set()
        for key in UNIT_REFERENCE_PROPERTIES:
            value = source.unit.get(key)
            if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
                self.invalidate(Invalidation.MALFORMED_STREAM)
                raise ValueError(BODY_ERROR)
            references.update(item for item in value if isinstance(item, str))
        if name not in references:
            raise ValueError(BINDING_ERROR)
        self._expected_units = self._expected_units | frozenset({name})
        return await self.read_unit(name, None, deadline_ns)

    async def read_unit(
        self, name: str, specific: Interface | None, deadline_ns: int, *, original_path: str | None = None
    ) -> UnitRead:
        """Read an object and both interfaces; a bound object is never replaced by name."""
        if name not in self._expected_units or specific not in (None, Interface.SERVICE, Interface.SLICE):
            raise ValueError(BINDING_ERROR)
        if self._identity is None or self._faults:
            raise RuntimeError(CONNECTION_ERROR)
        found = await self._call(
            Interface.MANAGER, MANAGER_PATH, Member.GET_UNIT, Signature.STRING, [name], Signature.OBJECT, deadline_ns
        )
        path = _single_text(found)
        self._watched_paths.add(path)
        begin_sequence = self._sequence
        if original_path is not None and path != original_path:
            self.invalidate(Invalidation.PARENT_REPLACED)
            raise ValueError(BINDING_ERROR)
        unit = await self._call(
            Interface.PROPERTIES,
            path,
            Member.GET_ALL,
            Signature.STRING,
            [Interface.UNIT.value],
            Signature.PROPERTIES,
            deadline_ns,
        )
        details: JsonObject = {}
        if specific is not None:
            detail = await self._call(
                Interface.PROPERTIES,
                path,
                Member.GET_ALL,
                Signature.STRING,
                [specific.value],
                Signature.PROPERTIES,
                deadline_ns,
            )
            details = _properties(detail)
        return UnitRead(name, path, _properties(unit), details, begin_sequence, self._sequence, time.monotonic_ns())

    async def read_unit_job(self, unit: UnitRead, deadline_ns: int) -> JobRead | None:
        """Resolve the exact job from a scoped unit snapshot through GetJob and native Job properties."""
        if unit.name not in self._expected_units:
            raise ValueError(BINDING_ERROR)
        reference = unit.unit.get(Property.JOB)
        if not isinstance(reference, list) or len(reference) != 2:
            self.invalidate(Invalidation.MALFORMED_STREAM)
            raise ValueError(BODY_ERROR)
        identifier, path = reference
        if type(identifier) is not int or identifier < 0 or not isinstance(path, str):
            self.invalidate(Invalidation.MALFORMED_STREAM)
            raise ValueError(BODY_ERROR)
        if identifier == 0:
            if path != PATH_SEPARATOR:
                self.invalidate(Invalidation.MALFORMED_STREAM)
                raise ValueError(BODY_ERROR)
            return None
        found = await self._call(
            Interface.MANAGER, MANAGER_PATH, Member.GET_JOB, Signature.UINT, [identifier], Signature.OBJECT, deadline_ns
        )
        if _single_text(found) != path:
            self.invalidate(Invalidation.UNKNOWN_ACTIVATOR)
            raise ValueError(BINDING_ERROR)
        reply = await self._call(
            Interface.PROPERTIES,
            path,
            Member.GET_ALL,
            Signature.STRING,
            [Interface.JOB.value],
            Signature.PROPERTIES,
            deadline_ns,
        )
        properties = _properties(reply)
        if (
            type(properties.get(Property.ID)) is not int
            or properties[Property.ID] != identifier
            or properties.get(Property.UNIT) != [unit.name, unit.object_path]
            or not isinstance(properties.get(Property.JOB_TYPE), str)
            or not properties[Property.JOB_TYPE]
            or not isinstance(properties.get(Property.STATE), str)
            or not properties[Property.STATE]
        ):
            self.invalidate(Invalidation.UNKNOWN_ACTIVATOR)
            raise ValueError(BINDING_ERROR)
        return JobRead(
            identifier,
            path,
            unit.name,
            unit.object_path,
            properties,
            unit.begin_sequence,
            self._sequence,
            time.monotonic_ns(),
        )

    async def bind_parent(
        self, name: str, population: PopulationObserver, deadline_ns: int, *, initial: UnitRead | None = None
    ) -> UnitRead:
        """Bind one active original parent to the already-open native observation handles."""
        if self._parent is not None or self._population is not None:
            raise ValueError(BINDING_ERROR)
        parent = await self.read_unit(
            name, Interface.SLICE, deadline_ns, original_path=initial.object_path if initial is not None else None
        )
        if (
            parent.unit.get(Property.ACTIVE_STATE) != ACTIVE
            or parent.specific.get(Property.CONTROL_GROUP) != population.control_group
            or (
                initial is not None
                and (
                    initial.name != name
                    or initial.unit.get(Property.ACTIVE_STATE) != ACTIVE
                    or initial.specific.get(Property.CONTROL_GROUP) != population.control_group
                )
            )
        ):
            self.invalidate(Invalidation.PARENT_DEACTIVATED)
            raise ValueError(BINDING_ERROR)
        self._parent = parent
        self._population = population
        for event in self._events:
            if event.sequence > (initial.begin_sequence if initial is not None else parent.begin_sequence):
                self._check_bound_event(event, parent, True)
        for fault in self._faults:
            population.invalidate(fault)
        if self._faults:
            raise RuntimeError(CONNECTION_ERROR)
        return parent

    async def bind_guest(self, name: str, deadline_ns: int) -> UnitRead:
        """Bind the positively started guest's object and nonempty invocation once."""
        if self._parent is None or self._guest is not None:
            raise ValueError(BINDING_ERROR)
        guest = await self.read_unit(name, Interface.SERVICE, deadline_ns)
        invocation = guest.unit.get(Property.INVOCATION_ID)
        parent_group = self._parent.specific.get(Property.CONTROL_GROUP)
        guest_group = guest.specific.get(Property.CONTROL_GROUP)
        if (
            not isinstance(invocation, list)
            or len(invocation) != 16
            or any(type(value) is not int or not 0 <= value <= 255 for value in invocation)
            or not any(invocation)
            or guest.unit.get(Property.ACTIVE_STATE) != ACTIVE
            or not isinstance(parent_group, str)
            or not isinstance(guest_group, str)
            or not guest_group.startswith(parent_group + PATH_SEPARATOR)
        ):
            raise ValueError(BINDING_ERROR)
        self._guest = guest
        for event in self._events:
            if event.sequence > guest.begin_sequence:
                self._check_bound_event(event, guest, False)
        if self._faults:
            raise RuntimeError(CONNECTION_ERROR)
        return guest

    async def read_active_boundary(self, deadline_ns: int) -> tuple[UnitRead, UnitRead]:
        """Read the active originals at an explicit phase frontier, retaining the first binding as the comparison basis."""
        original_parent, original_guest = self._parent, self._guest
        if original_parent is None or original_guest is None or self._population is None:
            raise ValueError(BINDING_ERROR)
        parent = await self.read_unit(
            original_parent.name, Interface.SLICE, deadline_ns, original_path=original_parent.object_path
        )
        guest = await self.read_unit(
            original_guest.name, Interface.SERVICE, deadline_ns, original_path=original_guest.object_path
        )
        if parent.unit.get(Property.ACTIVE_STATE) != ACTIVE:
            self.invalidate(Invalidation.PARENT_DEACTIVATED)
        if parent.specific.get(Property.CONTROL_GROUP) != self._population.control_group:
            self.invalidate(Invalidation.PARENT_REPLACED)
        if guest.unit.get(Property.INVOCATION_ID) != original_guest.unit.get(Property.INVOCATION_ID):
            self.invalidate(Invalidation.INVOCATION_CHANGED)
        if guest.specific.get(Property.CONTROL_GROUP) != original_guest.specific.get(Property.CONTROL_GROUP):
            self.invalidate(Invalidation.MOVED)
        if self._faults:
            raise RuntimeError(CONNECTION_ERROR)
        if guest.unit.get(Property.ACTIVE_STATE) != ACTIVE:
            raise ValueError(BINDING_ERROR)
        return parent, guest

    def _on_message(self, message: Message) -> None:
        """Contain malformed signal handling as a sticky loss rather than a dropped callback."""
        if message.message_type is not MessageType.SIGNAL:
            return
        try:
            self._signal(message)
        except Exception:
            self.invalidate(Invalidation.MALFORMED_STREAM)

    def _signal(self, message: Message) -> None:
        if message.interface == Interface.BUS and message.member == Member.OWNER_CHANGED:
            if message.sender != Interface.BUS or message.signature != Signature.OWNER:
                raise ValueError(BODY_ERROR)
            body = _body(message)
            if len(body) != 3 or not all(isinstance(value, str) for value in body):
                raise ValueError(BODY_ERROR)
            if body[0] == SYSTEMD_NAME:
                self.invalidate(Invalidation.MANAGER_CHANGED)
            return
        if self._identity is None or message.sender != self.identity.manager_owner:
            return
        if message.interface not in (Interface.MANAGER, Interface.PROPERTIES):
            return
        if message.interface == Interface.PROPERTIES and message.path not in self._watched_paths:
            return
        body = _body(message)
        if message.interface == Interface.MANAGER:
            if message.member in (Member.UNIT_NEW, Member.UNIT_REMOVED):
                if (
                    message.signature != Signature.UNIT_EVENT
                    or len(body) != 2
                    or not isinstance(body[0], str)
                    or not body[0]
                    or not isinstance(body[1], str)
                    or not body[1].startswith(PATH_SEPARATOR)
                ):
                    raise ValueError(BODY_ERROR)
            elif message.member in (Member.JOB_NEW, Member.JOB_REMOVED):
                expected = Signature.JOB_NEW if message.member == Member.JOB_NEW else Signature.JOB_REMOVED
                if (
                    message.signature != expected
                    or len(body) != (3 if message.member == Member.JOB_NEW else 4)
                    or type(body[0]) is not int
                    or not 0 < body[0] <= 0xFFFFFFFF
                    or not isinstance(body[1], str)
                    or not body[1].startswith(PATH_SEPARATOR)
                    or not isinstance(body[2], str)
                    or not body[2]
                    or (message.member == Member.JOB_REMOVED and (not isinstance(body[3], str) or not body[3]))
                ):
                    raise ValueError(BODY_ERROR)
        encoded_size = len(json.dumps(body, separators=JSON_SEPARATORS, allow_nan=False).encode(UTF8))
        self._sequence += 1
        if len(self._events) >= EVENT_LIMIT or self._event_bytes + encoded_size > EVENT_BYTES_LIMIT:
            self.invalidate(Invalidation.OVERFLOW)
            return
        event = NativeEvent(
            self._sequence,
            time.monotonic_ns(),
            message.path or EMPTY,
            message.interface,
            message.member or EMPTY,
            message.signature,
            tuple(body),
        )
        self._event_bytes += encoded_size
        self._events.append(event)
        self._changed.set()
        for bound, is_parent in ((self._parent, True), (self._guest, False)):
            if bound is None:
                continue
            self._check_bound_event(event, bound, is_parent)

    def _check_bound_event(self, event: NativeEvent, bound: UnitRead, is_parent: bool) -> None:
        if event.interface == Interface.MANAGER and event.member == Member.UNIT_REMOVED:
            if event.body[0] == bound.name or event.body[1] == bound.object_path:
                self.invalidate(Invalidation.PARENT_REPLACED if is_parent else Invalidation.INVOCATION_CHANGED)
        if event.interface == Interface.PROPERTIES and event.object_path == bound.object_path:
            self._property_signal(event, bound, is_parent)

    def _property_signal(self, message: NativeEvent, bound: UnitRead, is_parent: bool) -> None:
        if message.member != Member.PROPERTIES_CHANGED or message.signature != Signature.PROPERTY_CHANGE:
            raise ValueError(BODY_ERROR)
        body = message.body
        if (
            len(body) != 3
            or not isinstance(body[0], str)
            or not isinstance(body[1], dict)
            or not isinstance(body[2], list)
        ):
            raise ValueError(BODY_ERROR)
        changed = body[1]
        invalidated = body[2]
        for key in (Property.ACTIVE_STATE, Property.CONTROL_GROUP, Property.INVOCATION_ID):
            if key in invalidated:
                self.invalidate(Invalidation.MALFORMED_STREAM)
        specific = Interface.SLICE if is_parent else Interface.SERVICE
        if (
            body[0] == specific
            and Property.CONTROL_GROUP in changed
            and changed[Property.CONTROL_GROUP] != bound.specific.get(Property.CONTROL_GROUP)
        ):
            self.invalidate(Invalidation.MOVED)
        if body[0] != Interface.UNIT:
            return
        if is_parent and Property.ACTIVE_STATE in changed and changed[Property.ACTIVE_STATE] != ACTIVE:
            self.invalidate(Invalidation.PARENT_DEACTIVATED)
        if (
            not is_parent
            and Property.INVOCATION_ID in changed
            and changed[Property.INVOCATION_ID] != bound.unit.get(Property.INVOCATION_ID)
        ):
            self.invalidate(Invalidation.INVOCATION_CHANGED)

    async def close(self, deadline_ns: int) -> None:
        """End the original connection explicitly; later proof cannot resume it."""
        self.invalidate(Invalidation.BUS_DISCONNECTED)
        if self._bus is not None:
            cast(DisconnectLifecycle, self._bus).disconnect()
        if self._disconnect_task is not None:
            async with asyncio.timeout(_remaining(deadline_ns)):
                await asyncio.shield(self._disconnect_task)


def _remaining(deadline_ns: int) -> float:
    remaining = (deadline_ns - time.monotonic_ns()) / NANOSECONDS
    if remaining <= 0:
        raise TimeoutError(CONNECTION_ERROR)
    return remaining


def _wire(value: object) -> JsonValue:
    if isinstance(value, Variant):
        return _wire(value.value)
    if isinstance(value, bytes):
        return list(value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, (list, tuple)):
        return [_wire(item) for item in cast(list[object] | tuple[object, ...], value)]
    if isinstance(value, dict):
        items = cast(dict[object, object], value)
        if all(isinstance(key, str) for key in items):
            return {cast(str, key): _wire(item) for key, item in items.items()}
    raise ValueError(BODY_ERROR)


def _body(message: Message) -> list[JsonValue]:
    value = _wire(message.body)
    if not isinstance(value, list):
        raise ValueError(BODY_ERROR)
    return value


def _single_text(message: Message) -> str:
    body = _body(message)
    if len(body) != 1 or not isinstance(body[0], str) or not body[0]:
        raise ValueError(BODY_ERROR)
    return body[0]


def _properties(message: Message) -> JsonObject:
    body = _body(message)
    if len(body) != 1 or not isinstance(body[0], dict):
        raise ValueError(BODY_ERROR)
    return body[0]
