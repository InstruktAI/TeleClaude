"""Initial concrete phase observations owned by the original outside supervisor."""

from __future__ import annotations

import asyncio
import time
from enum import StrEnum
from typing import Final

from tools.ci.enclosure_actions import JOB_START, Authority, Key, NativeMutation
from tools.ci.enclosure_activation import ActivationSources, inspect_activation_sources
from tools.ci.enclosure_configuration import InstanceConfiguration, inspect_instance_configuration
from tools.ci.enclosure_contract import (
    Action,
    AdmittedDeadline,
    JsonObject,
    JsonValue,
    Phase,
    StaticPackage,
    object_value,
    parse_object,
    positive_integer,
    text,
)
from tools.ci.enclosure_exchange import HelperUncertain, run_privileged
from tools.ci.enclosure_graph import DependencyGraph, inspect_dependency_graph
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
    CONFIGURATION = "configuration"
    DEPENDENCY_GRAPH = "dependency_graph"
    ACTIVATION_SOURCES = "activation_sources"
    JOB_RESULT = "job_result"


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

    def __init__(self, owner: RunOwner, manager: ManagerObserver, package: StaticPackage) -> None:
        if manager.identity.boot_id != owner.journal.binding.controller.boot_id:
            raise ValueError(ERROR_BINDING)
        self.owner = owner
        self.manager = manager
        self.package = package
        self.population: PopulationObserver | None = None
        self.parent: UnitRead | None = None
        self.guest: UnitRead | None = None
        self._accepted: list[AcceptedJob] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self.uncertain: HelperUncertain | None = None
        self.configuration: InstanceConfiguration | None = None
        self.graph: DependencyGraph | None = None
        self.activation_sources: ActivationSources | None = None

    async def perform(
        self, action: Action, deadline: AdmittedDeadline, maximum_seconds: int, qualification_vector: str | None
    ) -> ActionResult:
        """Compose the actual separate helper with this process's original observations, without a new observer."""
        if action not in (Action.CREATE_PARENT, Action.START_GUEST):
            raise ValueError(ERROR_PHASE.format(action=action))
        if self.uncertain is not None:
            raise self.uncertain

        async def observe(mutation: NativeMutation, end_ns: int) -> ActionResult:
            return await self.observe(mutation, end_ns, deadline)

        try:
            return await run_privileged(self.owner, action, deadline, maximum_seconds, qualification_vector, observe)
        except HelperUncertain as error:
            # Preserve the original startup/Process even if an outer caller only renders the raised diagnostic.
            self.uncertain = error
            raise

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

    def _job_scope(self) -> frozenset[str]:
        record = parse_object(self.owner.manifest_bytes)
        names = {text(record, OwnerKey.PARENT_UNIT), text(record, OwnerKey.GUEST_UNIT)}
        names.update(job.unit_name for job in self._accepted)
        if self.graph is not None:
            names.update(node.read.name for node in self.graph.nodes)
        return frozenset(names)

    async def _settle(self, mutation: NativeMutation, name: str, end_ns: int) -> JobBoundary:
        evidence = mutation.evidence
        rows = evidence.get(Key.ACCEPTED_JOBS)
        if (
            evidence.get(Key.AUTHORITY) != Authority.HOST
            or evidence.get(Key.UNIT_NAME) != name
            or not isinstance(rows, list)
            or not rows
        ):
            raise ValueError(ERROR_BINDING)
        jobs: list[AcceptedJob] = []
        for value in rows:
            row = object_value(value)
            identifier = positive_integer(row, Key.JOB_IDENTIFIER)
            job = AcceptedJob(
                identifier,
                text(row, Key.JOB_PATH),
                text(row, Key.UNIT_NAME),
                text(row, Key.UNIT_PATH),
                text(row, Key.JOB_TYPE),
            )
            if (
                job.object_path != JOB_PREFIX.format(identifier=identifier)
                or identifier > 0xFFFFFFFF
                or any(prior.identifier == identifier for prior in (*self._accepted, *jobs))
            ):
                raise ValueError(ERROR_BINDING)
            jobs.append(job)
        anchor = jobs[0]
        if (
            anchor.unit_name != name
            or anchor.identifier != evidence.get(Key.JOB_IDENTIFIER)
            or anchor.object_path != evidence.get(Key.JOB_PATH)
            or anchor.job_type != JOB_START
        ):
            raise ValueError(ERROR_BINDING)
        self._accepted.extend(jobs)
        units = self._job_scope()
        # Native receipt alone is insufficient. Await the original subscription's terminal job signal.
        while True:
            sequence = self.manager.sequence
            removed = {
                (event.body[0], event.body[1]) for event in self.manager.events if event.member == Member.JOB_REMOVED
            }
            if all((job.identifier, job.object_path) in removed for job in jobs):
                return self.manager.reconcile_jobs(units, tuple(self._accepted))
            await self.manager.wait_for_change(sequence, end_ns)

    async def observe(self, mutation: NativeMutation, end_ns: int, deadline: AdmittedDeadline) -> ActionResult:
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
            initial = await self.manager.read_unit(
                name, Interface.SLICE, end_ns, original_path=text(mutation.evidence, Key.UNIT_PATH)
            )
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
            if self.guest.object_path != text(mutation.evidence, Key.UNIT_PATH):
                self.manager.invalidate(Invalidation.INVOCATION_CHANGED)
                raise ValueError(ERROR_BINDING)
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
        if mutation.action is Action.START_GUEST and self.guest is not None:
            self.configuration = inspect_instance_configuration(
                self.owner,
                self.package,
                current_parent,
                self.guest,
                AdmittedDeadline(deadline.outer_end_ns, deadline.vector_end_ns, end_ns),
            )
            self.graph = await inspect_dependency_graph(
                self.manager,
                self.package,
                self.configuration,
                AdmittedDeadline(deadline.outer_end_ns, deadline.vector_end_ns, end_ns),
                tuple(self._accepted),
            )
            metadata = await self.manager.read_manager(end_ns)
            self.activation_sources = inspect_activation_sources(
                self.package,
                self.graph,
                metadata,
                frozenset({self.parent.name, self.guest.name}),
                AdmittedDeadline(deadline.outer_end_ns, deadline.vector_end_ns, end_ns),
            )
        sample = self.population.sample(end_ns)
        if self.manager.faults or sample.faults or sample.populated is None:
            raise ValueError(ERROR_BINDING)
        jobs = self.manager.reconcile_jobs(self._job_scope(), tuple(self._accepted))
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
                Key.UNIT_PATH: job.accepted.unit_path,
                Key.JOB_TYPE: job.accepted.job_type,
                Evidence.JOB_RESULT: job.result,
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
                Evidence.CONFIGURATION: self.configuration.record() if self.configuration is not None else None,
                Evidence.DEPENDENCY_GRAPH: self.graph.record() if self.graph is not None else None,
                Evidence.ACTIVATION_SOURCES: self.activation_sources.record()
                if self.activation_sources is not None
                else None,
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
