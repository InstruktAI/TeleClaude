"""Initial concrete phase observations owned by the original outside supervisor."""

from __future__ import annotations

import asyncio
import time
from enum import StrEnum
from typing import Final

from tools.ci.enclosure_actions import Authority, Key, NativeMutation
from tools.ci.enclosure_contract import (
    Action,
    AdmittedDeadline,
    JsonObject,
    JsonValue,
    Phase,
    parse_object,
    positive_integer,
    text,
)
from tools.ci.enclosure_exchange import run_privileged
from tools.ci.enclosure_journal import ActionResult, Outcome
from tools.ci.enclosure_manager import (
    ACTIVE,
    AcceptedJob,
    Interface,
    JobBoundary,
    ManagerObserver,
    Member,
    Property,
    UnitRead,
)
from tools.ci.enclosure_owner import Key as OwnerKey
from tools.ci.enclosure_owner import RunOwner
from tools.ci.enclosure_population import Invalidation, PopulationObserver

UTF8: Final = "utf-8"
JOB_PREFIX: Final = "/org/freedesktop/systemd1/job/{identifier}"
ERROR_PHASE: Final = "the original supervisor cannot yet establish this phase: {action}"
ERROR_BINDING: Final = "the original supervisor's parent, invocation, job or population evidence disagrees"
DELEGATE: Final = "Delegate"
SLICE_SUFFIX: Final = ".slice"


class Evidence(StrEnum):
    """Observation evidence stays separate from helper/native call acknowledgments."""

    NATIVE_RECEIPT = "native_receipt"
    PHASE = "phase"
    IDENTITY = "identity"
    PARENT = "parent"
    GUEST = "guest"
    POPULATION = "population"
    RAW = "raw"
    POPULATED = "populated"
    READ_STARTED_NS = "read_started_ns"
    READ_FINISHED_NS = "read_finished_ns"
    SEQUENCE = "sequence"
    JOBS = "jobs"
    OBSERVED_NS = "observed_ns"
    OBJECT_PATH = "object_path"
    BUS_ID = "bus_id"
    MANAGER_OWNER = "manager_owner"
    BOOT_ID = "boot_id"


def _unit(read: UnitRead) -> JsonObject:
    return {
        Key.UNIT_NAME: read.name,
        Evidence.OBJECT_PATH: read.object_path,
        Interface.UNIT.value: dict(read.unit),
        Evidence.SEQUENCE: read.sequence,
        Evidence.OBSERVED_NS: read.observed_ns,
        (Interface.SLICE.value if read.name.endswith(SLICE_SUFFIX) else Interface.SERVICE.value): dict(read.specific),
    }


class BindingPhases:
    """Keep the original bus and cgroup handles in this process while its child holds the action flock."""

    def __init__(self, owner: RunOwner, manager: ManagerObserver) -> None:
        if manager.identity.boot_id != owner.journal.binding.controller.boot_id:
            raise ValueError(ERROR_BINDING)
        self.owner = owner
        self.manager = manager
        self.population: PopulationObserver | None = None
        self.parent: UnitRead | None = None
        self.guest: UnitRead | None = None
        self._accepted: list[AcceptedJob] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    async def perform(
        self, action: Action, deadline: AdmittedDeadline, maximum_seconds: int, qualification_vector: str | None
    ) -> ActionResult:
        """Compose the actual separate helper with this process's original observations, without a new observer."""
        if action not in (Action.CREATE_PARENT, Action.START_GUEST):
            raise ValueError(ERROR_PHASE.format(action=action))
        return await run_privileged(self.owner, action, deadline, maximum_seconds, qualification_vector, self.observe)

    def _population_ready(self) -> None:
        if self.population is not None:
            try:
                self.population.observe_notifications(self.owner.journal.deadline.end_ns)
            except Exception:
                self.population.invalidate(Invalidation.READ_FAILED)
                if self._loop is not None:
                    self._loop.remove_reader(self.population.fileno())
                    self._loop = None
            if time.monotonic_ns() >= self.owner.journal.deadline.end_ns and self._loop is not None:
                self.population.invalidate(Invalidation.DEADLINE_EXPIRED)
                self._loop.remove_reader(self.population.fileno())
                self._loop = None

    async def _settle(self, mutation: NativeMutation, name: str, end_ns: int) -> JobBoundary:
        evidence = mutation.evidence
        identifier = positive_integer(evidence, Key.JOB_IDENTIFIER)
        job = AcceptedJob(identifier, text(evidence, Key.JOB_PATH), name)
        if (
            evidence.get(Key.AUTHORITY) != Authority.HOST
            or evidence.get(Key.UNIT_NAME) != name
            or job.object_path != JOB_PREFIX.format(identifier=identifier)
            or identifier > 0xFFFFFFFF
            or job in self._accepted
        ):
            raise ValueError(ERROR_BINDING)
        self._accepted.append(job)
        record = parse_object(self.owner.manifest_bytes)
        units = frozenset({text(record, OwnerKey.PARENT_UNIT), text(record, OwnerKey.GUEST_UNIT)})
        # Native receipt alone is insufficient. Await the original subscription's terminal job signal.
        while True:
            sequence = self.manager.sequence
            removed = any(
                event.member == Member.JOB_REMOVED and event.body[:2] == (identifier, job.object_path)
                for event in self.manager.events
            )
            if removed:
                return self.manager.reconcile_jobs(units, tuple(self._accepted))
            await self.manager.wait_for_change(sequence, end_ns)

    async def observe(self, mutation: NativeMutation, end_ns: int) -> ActionResult:
        """Establish only implemented original-object phases; no path or observer replacement on failure."""
        if mutation.action not in (Action.CREATE_PARENT, Action.START_GUEST):
            raise ValueError(ERROR_PHASE.format(action=mutation.action))
        self.owner.journal.binding.controller.require_alive()
        if time.monotonic_ns() >= end_ns or end_ns > self.owner.journal.deadline.end_ns:
            raise TimeoutError(ERROR_BINDING)
        await self.manager.check_identity(end_ns)
        record = parse_object(self.owner.manifest_bytes)
        name = text(record, OwnerKey.PARENT_UNIT if mutation.action is Action.CREATE_PARENT else OwnerKey.GUEST_UNIT)
        jobs = await self._settle(mutation, name, end_ns)
        if mutation.action is Action.CREATE_PARENT:
            if self.parent is not None or self.population is not None:
                raise ValueError(ERROR_BINDING)
            initial = await self.manager.read_unit(name, Interface.SLICE, end_ns)
            if initial.unit.get(Property.ACTIVE_STATE) != ACTIVE or initial.specific.get(DELEGATE) is not False:
                raise ValueError(ERROR_BINDING)
            population = PopulationObserver(text(initial.specific, Property.CONTROL_GROUP))
            self.population = population
            self._loop = asyncio.get_running_loop()
            try:
                self._loop.add_reader(population.fileno(), self._population_ready)
            except BaseException:
                population.invalidate(Invalidation.READ_FAILED)
                raise
            self.parent = await self.manager.bind_parent(name, population, end_ns, initial=initial)
            phase = Phase.PARENT_BOUND
        else:
            if self.parent is None or self.population is None or self.guest is not None:
                raise ValueError(ERROR_BINDING)
            self.guest = await self.manager.bind_guest(name, end_ns)
            phase = Phase.GUEST_STARTED
        current_parent = await self.manager.read_unit(
            self.parent.name, Interface.SLICE, end_ns, original_path=self.parent.object_path
        )
        if (
            current_parent.unit.get(Property.ACTIVE_STATE) != ACTIVE
            or current_parent.specific.get(Property.CONTROL_GROUP) != self.population.control_group
            or current_parent.specific.get(DELEGATE) is not False
        ):
            self.manager.invalidate(Invalidation.PARENT_REPLACED)
            raise ValueError(ERROR_BINDING)
        sample = self.population.sample(end_ns)
        if self.manager.faults or sample.faults or sample.populated is None:
            raise ValueError(ERROR_BINDING)
        jobs = self.manager.reconcile_jobs(
            frozenset({text(record, OwnerKey.PARENT_UNIT), text(record, OwnerKey.GUEST_UNIT)}), tuple(self._accepted)
        )
        identity: JsonObject = {
            Evidence.BUS_ID: self.manager.identity.bus_id,
            Evidence.MANAGER_OWNER: self.manager.identity.manager_owner,
            Evidence.BOOT_ID: self.manager.identity.boot_id,
        }
        settled: list[JsonValue] = [
            {
                Key.JOB_IDENTIFIER: job.accepted.identifier,
                Key.JOB_PATH: job.accepted.object_path,
                Key.UNIT_NAME: job.accepted.unit_name,
                Evidence.SEQUENCE: [job.new_sequence, job.removed_sequence],
            }
            for job in jobs.settled
        ]
        return ActionResult(
            Outcome.SUCCEEDED,
            {
                Evidence.NATIVE_RECEIPT: dict(mutation.evidence),
                Evidence.PHASE: phase.value,
                Evidence.IDENTITY: identity,
                Evidence.PARENT: _unit(current_parent),
                Evidence.GUEST: _unit(self.guest) if self.guest is not None else None,
                Evidence.JOBS: settled,
                Evidence.POPULATION: {
                    Evidence.RAW: sample.raw.decode(UTF8),
                    Evidence.POPULATED: sample.populated,
                    Evidence.READ_STARTED_NS: sample.read_started_ns,
                    Evidence.READ_FINISHED_NS: sample.read_finished_ns,
                    Evidence.SEQUENCE: sample.last_notification_sequence,
                },
            },
        )

    def close_population(self) -> None:
        """End observation explicitly; callers owe retention/release decisions separately."""
        if self.population is not None:
            if self._loop is not None:
                self._loop.remove_reader(self.population.fileno())
                self._loop = None
            self.population.close()
