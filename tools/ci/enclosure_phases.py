"""Initial concrete phase observations owned by the original outside supervisor."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import asdict
from enum import StrEnum
from pathlib import Path
from typing import Final

from tools.ci.enclosure_actions import JOB_START, Authority, Key, NativeMutation
from tools.ci.enclosure_activation import ActivationSources, inspect_activation_sources, inspect_start_sources
from tools.ci.enclosure_activation import Key as ActivationKey
from tools.ci.enclosure_configuration import (
    InstanceConfiguration,
    MaskedInstanceConfiguration,
    inspect_instance_configuration,
    inspect_masked_instance_configuration,
    read_runtime_mask,
)
from tools.ci.enclosure_contract import (
    Action,
    AdmittedDeadline,
    Field,
    JsonObject,
    JsonValue,
    Phase,
    StaticPackage,
    object_value,
    parse_object,
    positive_integer,
    text,
)
from tools.ci.enclosure_exchange import HelperExitFailed, HelperStartup, HelperUncertain, run_privileged
from tools.ci.enclosure_graph import DependencyGraph, inspect_dependency_graph
from tools.ci.enclosure_guest import GuestContext
from tools.ci.enclosure_guest_binding import GuestBinding
from tools.ci.enclosure_guest_evidence import (
    EvidenceLeaf,
    GuestFileRead,
    GuestSetupEvidence,
    read_guest_evidence,
    validate_setup_journal,
)
from tools.ci.enclosure_guest_manifest import compose_payload_manifest, compose_setup_manifest, narrow_setup_manifest
from tools.ci.enclosure_journal import CLOSURE_ACTIONS, ActionResult, Outcome
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
from tools.ci.enclosure_payload_completion import (
    PayloadCompletion,
    capture_payload_completion,
    validate_shutdown_journal,
)
from tools.ci.enclosure_payload_driver import PayloadDrive, drive_payload
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
    HELPER = "helper"
    START_SOURCES = "start_sources"
    PRE_MASK_GRAPH = "pre_mask_graph"
    PRE_MASK_ACTIVATION_SOURCES = "pre_mask_activation_sources"
    HELPERS = "helpers"
    RECEIPT_STATUS = "receipt_status"
    MASK_TOMBSTONE = "mask_tombstone"


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
        self.helper_failure: HelperExitFailed | None = None
        self.configuration: InstanceConfiguration | None = None
        self.graph: DependencyGraph | None = None
        self.activation_sources: ActivationSources | None = None
        self._startups: list[HelperStartup] = []
        self.start_sources: dict[Action, JsonObject] = {}
        self.masked_sources: JsonObject | None = None
        self.masked_configuration: MaskedInstanceConfiguration | None = None
        self.masked_graph: DependencyGraph | None = None
        self.masked_activation_sources: ActivationSources | None = None
        self.results: dict[Action, ActionResult] = {}
        self.seal: ActionResult | None = None
        self.seal_boundary: JobBoundary | None = None
        self.completion_failure: BaseException | None = None
        self.guest_binding: GuestBinding | None = None
        self.guest_admission: JsonObject | None = None
        self.prepared_guest_manifest: bytes | None = None
        self.guest_setup_read: GuestFileRead | None = None
        self.guest_setup_evidence: GuestSetupEvidence | None = None
        self.configured: ActionResult | None = None
        self.active_guest_manifest: bytes | None = None
        self.prepared_payload_manifest: bytes | None = None
        self.payload_started: ActionResult | None = None
        self.payload_start_receipt: NativeMutation | None = None
        self.payload_completions: list[PayloadCompletion] = []
        self.payload_observations: list[JsonObject] = []
        self.automatic_cleanup_read: GuestFileRead | None = None
        self.shutdown_requested: ActionResult | None = None

    @property
    def startups(self) -> tuple[HelperStartup, ...]:
        """Expose the original startup collection for same-loop bounded closure/final reporting, without adopting a new task."""
        return tuple(self._startups)

    async def run_payload(self, original: AdmittedDeadline) -> PayloadDrive:
        """Drive the configured guest on this original loop; the result grants no P4 or release authority."""
        return await drive_payload(self, original)

    async def perform(
        self,
        action: Action,
        deadline: AdmittedDeadline,
        maximum_seconds: int,
        qualification_vector: str | None,
        *,
        selected: frozenset[str] | None = None,
    ) -> ActionResult:
        """Compose the actual separate helper with this process's original observations, without a new observer."""
        if action not in (
            Action.CREATE_PARENT,
            Action.START_GUEST,
            Action.MASK_GUEST,
            Action.GUEST_SETUP,
            Action.START_PAYLOAD,
            Action.POWEROFF,
        ) or ((action in (Action.GUEST_SETUP, Action.START_PAYLOAD, Action.POWEROFF)) != (self.seal is not None)):
            raise ValueError(ERROR_PHASE.format(action=action))
        if action is Action.POWEROFF and (self.payload_started is None or self.automatic_cleanup_read is None):
            raise ValueError(ERROR_BINDING)
        if self.uncertain is not None:
            raise self.uncertain
        if self.helper_failure is not None:
            raise self.helper_failure
        if self.completion_failure is not None:
            raise self.completion_failure
        if any(result.status is not Outcome.SUCCEEDED for result in self.results.values()):
            raise ValueError(ERROR_BINDING)
        # Preserve outer closure time before any read; do not subtract it from the original vector/command ends.
        end_ns = AdmittedDeadline(
            deadline.outer_end_ns,
            deadline.vector_end_ns,
            min(
                deadline.effective_end(),
                self.owner.journal.deadline.end_ns
                - (0 if action in CLOSURE_ACTIONS else self.owner.journal.deadline.reserve_ns),
            ),
        ).command_end(maximum_seconds)
        action_deadline = AdmittedDeadline(deadline.outer_end_ns, deadline.vector_end_ns, end_ns)
        await self.manager.check_identity(end_ns)
        if action in (Action.MASK_GUEST, Action.GUEST_SETUP, Action.START_PAYLOAD, Action.POWEROFF):
            self._helper_frontier(None)
            self._require_source_closure(masked=action is not Action.MASK_GUEST)
        else:
            metadata = await self.manager.read_manager(end_ns)
            sources = inspect_start_sources(self.owner, self.package, metadata, action, action_deadline)
            self.start_sources[action] = sources
            if sources[ActivationKey.UNCLASSIFIED]:
                raise ValueError(ERROR_BINDING)
        guest_root_fd, manifest_digest, previous_digest = await self._prepare_guest_input(
            action, action_deadline, deadline, qualification_vector, selected
        )
        await self.manager.check_identity(end_ns)

        async def observe(mutation: NativeMutation, end_ns: int, startup: HelperStartup) -> ActionResult:
            return await self.observe(mutation, end_ns, action_deadline, startup)

        try:
            result = await run_privileged(
                self.owner,
                action,
                action_deadline,
                maximum_seconds,
                qualification_vector,
                observe,
                self._startups,
                guest_root_fd=guest_root_fd,
                guest_manifest_digest=manifest_digest,
                previous_manifest_digest=previous_digest,
            )
            self.results[action] = result
            if time.monotonic_ns() >= end_ns:
                raise TimeoutError(ERROR_BINDING)
            if action is Action.MASK_GUEST and result.status is Outcome.SUCCEEDED:
                self._helper_frontier(None)
                if result.evidence.get(Evidence.PHASE) != Phase.ADMISSION_SEALED:
                    raise ValueError(ERROR_BINDING)
                # Ack/EOF/exit awaited the original loop after the callback's reconciliation.
                boundary = self.manager.reconcile_jobs(self._job_scope(), tuple(self._accepted))
                if time.monotonic_ns() >= end_ns:
                    raise TimeoutError(ERROR_BINDING)
                # Only the actual durable receipt plus positive helper exit exposes this seal to the supervisor.
                self.seal_boundary = boundary
                self.seal = result
            if action is Action.GUEST_SETUP and result.status is Outcome.SUCCEEDED:
                self._expose_configured(result, action_deadline)
            if action is Action.START_PAYLOAD and result.status is Outcome.SUCCEEDED:
                await self._expose_payload(result, action_deadline)
            if action is Action.POWEROFF and result.status is Outcome.SUCCEEDED:
                await self._expose_shutdown(result, action_deadline)
            return result
        except HelperUncertain as error:
            # Preserve the original startup/Process even if an outer caller only renders the raised diagnostic.
            self.uncertain = error
            raise
        except HelperExitFailed as error:
            self.helper_failure = error
            raise
        except BaseException as error:
            # Keep a known receipt separate from failed/late supervision; neither permits another normal action.
            self.completion_failure = error
            raise

    async def _prepare_guest_input(
        self,
        action: Action,
        admitted: AdmittedDeadline,
        original: AdmittedDeadline,
        vector: str | None,
        selected: frozenset[str] | None,
    ) -> tuple[int | None, str | None, str | None]:
        if action is Action.POWEROFF:
            if self.guest_binding is None or self.prepared_payload_manifest is None:
                raise ValueError(ERROR_BINDING)
            self.guest_binding.require_root_view(admitted)
            return self.guest_binding.root_fd, hashlib.sha256(self.prepared_payload_manifest).hexdigest(), None
        if action not in (Action.GUEST_SETUP, Action.START_PAYLOAD):
            return None, None, None
        try:
            binding = await self.admit_guest(admitted)
            previous = None
            if action is Action.GUEST_SETUP:
                if selected is None or self.seal is None:
                    raise ValueError(ERROR_BINDING)
                data = compose_setup_manifest(self.owner, self.package, binding, self.seal, selected, admitted, vector)
                self.prepared_guest_manifest = data
            else:
                if self.configured is None or self.active_guest_manifest is None or self.guest_setup_evidence is None:
                    raise ValueError(ERROR_BINDING)
                data = compose_payload_manifest(self.owner, self.active_guest_manifest, original)
                self.prepared_payload_manifest = data
                previous = self.guest_setup_evidence.manifest_sha256
            return binding.root_fd, hashlib.sha256(data).hexdigest(), previous
        except BaseException as error:
            self.completion_failure = error
            raise

    async def _expose_payload(self, result: ActionResult, deadline: AdmittedDeadline) -> None:
        if result.evidence.get(Evidence.PHASE) != Phase.PAYLOAD_STARTED:
            raise ValueError(ERROR_BINDING)
        # The known native start survives later observation/functional/shutdown failures.
        self.payload_started = result
        native = object_value(result.evidence[Evidence.NATIVE_RECEIPT])
        end = min(deadline.effective_end(), positive_integer(native, Key.COMMAND_END_NS))
        await self._payload_observation(AdmittedDeadline(deadline.outer_end_ns, deadline.vector_end_ns, end), None)

    async def _expose_shutdown(self, result: ActionResult, deadline: AdmittedDeadline) -> None:
        if result.evidence.get(Evidence.PHASE) != Phase.SHUTDOWN_REQUESTED:
            raise ValueError(ERROR_BINDING)
        self.shutdown_requested = result
        await self._payload_observation(deadline, None)

    async def wait_for_payload_exit(self, deadline: AdmittedDeadline) -> JsonObject:
        """Wait on the original native stream; terminal state and any missing/failed evidence remain actual facts."""
        if self.payload_started is None or deadline.outer_end_ns != self.owner.journal.deadline.end_ns:
            raise ValueError(ERROR_BINDING)
        budget = object_value(parse_object(self.package.recipe_bytes)[Field.BUDGET_SECONDS])
        cap = positive_integer(budget, Field.NORMAL_COMMAND_MAX)
        while True:
            # Waiting from the pre-read position cannot lose a terminal event received during the read.
            sequence = self.manager.sequence
            end = deadline.command_end(cap)
            observed = await self._payload_observation(
                AdmittedDeadline(deadline.outer_end_ns, deadline.vector_end_ns, end), None
            )
            guest = object_value(object_value(observed[Evidence.GUEST])[Interface.UNIT.value])
            if guest.get(Property.ACTIVE_STATE) in ("inactive", "failed"):
                return observed
            while True:
                await self.manager.wait_for_change(sequence, deadline.effective_end())
                self._helper_frontier(None)
                self.manager.reconcile_jobs(self._job_scope(), tuple(self._accepted))
                if self.guest is None:
                    raise ValueError(ERROR_BINDING)
                relevant = any(
                    event.sequence > sequence and event.object_path == self.guest.object_path
                    for event in self.manager.events
                )
                sequence = self.manager.sequence
                if relevant:
                    break

    def _expose_configured(self, result: ActionResult, deadline: AdmittedDeadline) -> None:
        self._guest_completion_frontier(result, deadline, Phase.GUEST_CONFIGURED)
        self.configured = result

    def _guest_completion_frontier(self, result: ActionResult, deadline: AdmittedDeadline, phase: Phase) -> None:
        """Keep helper completion and the final original-stream frontier separate from the durable phase receipt."""
        self._helper_frontier(None)
        if self.guest_binding is None or result.evidence.get(Evidence.PHASE) != phase:
            raise ValueError(ERROR_BINDING)
        self.guest_binding.require_original(deadline)
        self.manager.reconcile_jobs(self._job_scope(), tuple(self._accepted))
        if time.monotonic_ns() >= deadline.effective_end():
            raise TimeoutError(ERROR_BINDING)

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

    async def admit_guest(self, deadline: AdmittedDeadline) -> GuestBinding:
        """Bind the sealed guest's actual original leader/root view before composing its protected manifest."""
        if self.uncertain is not None:
            raise self.uncertain
        if self.helper_failure is not None:
            raise self.helper_failure
        if self.completion_failure is not None:
            raise self.completion_failure
        if (
            self.seal is None
            or self.seal.status is not Outcome.SUCCEEDED
            or self.seal.evidence.get(Evidence.PHASE) != Phase.ADMISSION_SEALED
            or self.population is None
            or self.masked_configuration is None
            or deadline.outer_end_ns != self.owner.journal.deadline.end_ns
        ):
            raise ValueError(ERROR_BINDING)
        budget = object_value(parse_object(self.package.recipe_bytes)[Field.BUDGET_SECONDS])
        end_ns = AdmittedDeadline(
            deadline.outer_end_ns,
            deadline.vector_end_ns,
            min(deadline.effective_end(), self.owner.journal.deadline.end_ns - self.owner.journal.deadline.reserve_ns),
        ).command_end(positive_integer(budget, Field.NORMAL_COMMAND_MAX))
        admitted = AdmittedDeadline(deadline.outer_end_ns, deadline.vector_end_ns, end_ns)
        try:
            self._helper_frontier(None)
            self._require_source_closure(masked=True)
            self.owner.journal.binding.controller.require_alive()
            await self.manager.check_identity(end_ns)
            _, guest = await self.manager.read_active_boundary(end_ns)
            if self.guest_binding is None:
                rootfs = Path(text(parse_object(self.owner.manifest_bytes), OwnerKey.ROOTFS))
                registration = await self.manager.read_machine(rootfs.name, end_ns)
                self.guest_binding = GuestBinding.capture(
                    registration, guest, rootfs, self.manager.identity.boot_id, admitted
                )
            binding = self.guest_binding
            parent, guest = await self.manager.read_active_boundary(end_ns)
            await self.manager.check_identity(end_ns)
            binding.require_original(admitted)
            mask = read_runtime_mask(Path(text(self.masked_configuration.mask, Field.PATH)), admitted)
            sample = self.population.sample(end_ns)
            helpers = self._helper_frontier(None)
            boundary = self.manager.reconcile_jobs(self._job_scope(), tuple(self._accepted))
            if time.monotonic_ns() >= end_ns:
                raise TimeoutError(ERROR_BINDING)
            self.guest_admission = {
                "guest_binding": binding.record(),
                Evidence.PARENT: _unit(parent),
                Evidence.GUEST: _unit(guest),
                Evidence.MASK_TOMBSTONE: mask,
                Evidence.HELPERS: helpers,
                Evidence.SEQUENCE: boundary.sequence,
                Evidence.OBSERVED_NS: boundary.observed_ns,
                Evidence.POPULATION: {
                    Evidence.RAW: sample.raw.decode(UTF8),
                    Evidence.POPULATED: sample.populated,
                    Evidence.READ_STARTED_NS: sample.read_started_ns,
                    Evidence.READ_FINISHED_NS: sample.read_finished_ns,
                    Evidence.SEQUENCE: sample.last_notification_sequence,
                },
            }
            if time.monotonic_ns() >= end_ns:
                raise TimeoutError(ERROR_BINDING)
            # No await after the final original-stream reconciliation before exposing this binding.
            return binding
        except BaseException as error:
            self.completion_failure = error
            raise

    def _job_scope(self) -> frozenset[str]:
        record = parse_object(self.owner.manifest_bytes)
        names = {text(record, OwnerKey.PARENT_UNIT), text(record, OwnerKey.GUEST_UNIT)}
        names.update(job.unit_name for job in self._accepted)
        if self.graph is not None:
            names.update(self.graph.creators)
        if self.masked_graph is not None:
            names.update(self.masked_graph.creators)
        return frozenset(names)

    def _helper_frontier(self, current: HelperStartup | None) -> list[JsonValue]:
        """Account for each original startup and native Process without taking the current helper's journal flock."""
        loop = asyncio.get_running_loop()
        if self._loop is not loop or self.population is None or self.population.faults or self.manager.faults:
            raise ValueError(ERROR_BINDING)
        if current is not None and (
            current not in self._startups
            or current.action not in (Action.MASK_GUEST, Action.GUEST_SETUP, Action.START_PAYLOAD, Action.POWEROFF)
        ):
            raise ValueError(ERROR_BINDING)
        facts: list[JsonValue] = []
        for startup in self._startups:
            if (
                startup.task.get_loop() is not loop
                or startup.task.cancelled()
                or not startup.task.done()
                or startup.task.exception() is not None
                or startup.process is None
                or startup.task.result() is not startup.process
                or startup.identity is None
                or startup.identity.pid != startup.process.pid
                or startup.identity.uid != 0
                or startup.identity.boot_id != self.owner.journal.binding.controller.boot_id
            ):
                raise ValueError(ERROR_BINDING)
            receipt = self.results.get(startup.action)
            if startup is current:
                if receipt is not None or startup.process.returncode is not None:
                    raise ValueError(ERROR_BINDING)
                startup.identity.require_alive()
            elif receipt is None or receipt.status is not Outcome.SUCCEEDED or startup.process.returncode != 0:
                raise ValueError(ERROR_BINDING)
            facts.append(
                {
                    **startup.record(),
                    Evidence.RECEIPT_STATUS: receipt.status.value if receipt is not None else None,
                }
            )
        return facts

    def _require_source_closure(self, *, masked: bool) -> None:
        """Old and current source unknowns remain blocking; current pending creator jobs supply no settlement proof."""
        if self.configuration is None or self.graph is None or self.activation_sources is None:
            raise ValueError(ERROR_BINDING)
        if self.graph.unclassified or self.activation_sources.unclassified:
            raise ValueError(ERROR_BINDING)
        if masked:
            if self.masked_configuration is None or self.masked_graph is None or self.masked_activation_sources is None:
                raise ValueError(ERROR_BINDING)
            if self.masked_graph.unclassified or self.masked_activation_sources.unclassified:
                raise ValueError(ERROR_BINDING)
            creators = frozenset(self.masked_graph.creators)
            if any(node.current_job is not None for node in self.masked_graph.nodes if node.read.name in creators):
                raise ValueError(ERROR_BINDING)

    async def read_masked_sources(self, mutation: NativeMutation, deadline: AdmittedDeadline) -> JsonObject:
        """Compose original post-mask observations and retained history without advancing admission or certifying creators."""
        if (
            mutation.action is not Action.MASK_GUEST
            or self.configuration is None
            or self.graph is None
            or self.activation_sources is None
            or self.population is None
            or deadline.outer_end_ns != self.owner.journal.deadline.end_ns
        ):
            raise ValueError(ERROR_BINDING)
        end_ns = min(
            deadline.effective_end(), self.owner.journal.deadline.end_ns - self.owner.journal.deadline.reserve_ns
        )
        deadline = AdmittedDeadline(deadline.outer_end_ns, deadline.vector_end_ns, end_ns)
        if time.monotonic_ns() >= end_ns:
            raise TimeoutError(ERROR_BINDING)
        self.owner.journal.binding.controller.require_alive()
        await self.manager.check_identity(end_ns)
        parent, guest = await self.manager.read_active_boundary(end_ns)
        configuration = inspect_masked_instance_configuration(
            self.owner, self.configuration, parent, guest, mutation, deadline
        )
        self.masked_configuration = configuration
        evidence: JsonObject = {
            Evidence.NATIVE_RECEIPT: dict(mutation.evidence),
            Evidence.CONFIGURATION: configuration.record(),
            Evidence.PARENT: _unit(parent),
            Evidence.GUEST: _unit(guest),
            Evidence.PRE_MASK_GRAPH: self.graph.record(),
            Evidence.PRE_MASK_ACTIVATION_SOURCES: self.activation_sources.record(),
        }
        self.masked_sources = evidence
        graph = await inspect_dependency_graph(
            self.manager,
            self.package,
            configuration.current,
            deadline,
            tuple(self._accepted),
            masked=configuration,
            previous=self.graph,
        )
        self.masked_graph = graph
        evidence[Evidence.DEPENDENCY_GRAPH] = graph.record()
        metadata = await self.manager.read_manager(end_ns)
        activation = inspect_activation_sources(
            self.package,
            graph,
            metadata,
            self.owner,
            deadline,
            configuration=configuration.current,
            previous=self.graph,
        )
        self.masked_activation_sources = activation
        evidence[Evidence.ACTIVATION_SOURCES] = activation.record()
        await self.manager.check_identity(end_ns)
        sample = self.population.sample(end_ns)
        if self.manager.faults or sample.faults or sample.populated is None:
            raise ValueError(ERROR_BINDING)
        jobs = self.manager.reconcile_jobs(self._job_scope() | frozenset(graph.creators), tuple(self._accepted))
        evidence[Evidence.JOBS] = [
            {
                Key.JOB_IDENTIFIER: job.accepted.identifier,
                Key.JOB_PATH: job.accepted.object_path,
                Key.UNIT_NAME: job.accepted.unit_name,
                Evidence.JOB_RESULT: job.result,
                Evidence.SEQUENCE: [job.new_sequence, job.removed_sequence],
            }
            for job in jobs.settled
        ]
        evidence[Evidence.POPULATION] = {
            Evidence.RAW: sample.raw.decode(UTF8),
            Evidence.POPULATED: sample.populated,
            Evidence.READ_STARTED_NS: sample.read_started_ns,
            Evidence.READ_FINISHED_NS: sample.read_finished_ns,
            Evidence.SEQUENCE: sample.last_notification_sequence,
        }
        return evidence

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

    async def observe(
        self, mutation: NativeMutation, end_ns: int, deadline: AdmittedDeadline, startup: HelperStartup
    ) -> ActionResult:
        """Establish only implemented original-object phases; no path or observer replacement on failure."""
        if mutation.action not in (
            Action.CREATE_PARENT,
            Action.START_GUEST,
            Action.MASK_GUEST,
            Action.GUEST_SETUP,
            Action.START_PAYLOAD,
            Action.POWEROFF,
        ):
            raise ValueError(ERROR_PHASE.format(action=mutation.action))
        if startup not in self._startups or startup.action is not mutation.action or startup.identity is None:
            raise ValueError(ERROR_BINDING)
        startup.identity.require_alive()
        self.owner.journal.binding.controller.require_alive()
        if time.monotonic_ns() >= end_ns or end_ns > self.owner.journal.deadline.end_ns:
            raise TimeoutError(ERROR_BINDING)
        await self.manager.check_identity(end_ns)
        if mutation.action is Action.GUEST_SETUP:
            return await self._configured(mutation, end_ns, deadline, startup)
        if mutation.action is Action.START_PAYLOAD:
            return await self._payload_start(mutation, end_ns, deadline, startup)
        if mutation.action is Action.POWEROFF:
            return await self._shutdown_receipt(mutation, end_ns, deadline, startup)
        if mutation.action is Action.MASK_GUEST:
            self._helper_frontier(startup)
            evidence = await self.read_masked_sources(
                mutation, AdmittedDeadline(deadline.outer_end_ns, deadline.vector_end_ns, end_ns)
            )
            self._require_source_closure(masked=True)
            if self.masked_configuration is None:
                raise ValueError(ERROR_BINDING)
            evidence[Evidence.MASK_TOMBSTONE] = read_runtime_mask(
                Path(text(self.masked_configuration.mask, Field.PATH)),
                AdmittedDeadline(deadline.outer_end_ns, deadline.vector_end_ns, end_ns),
            )
            evidence[Evidence.HELPERS] = self._helper_frontier(startup)
            evidence[Evidence.HELPER] = startup.record()
            evidence[Evidence.PHASE] = Phase.ADMISSION_SEALED.value
            return ActionResult(Outcome.SUCCEEDED, evidence)

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
        current_guest = None
        if self.guest is not None:
            current_parent, current_guest = await self.manager.read_active_boundary(end_ns)
        else:
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
        if mutation.action is Action.START_GUEST and current_guest is not None:
            self.configuration = inspect_instance_configuration(
                self.owner,
                self.package,
                current_parent,
                current_guest,
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
                self.owner,
                AdmittedDeadline(deadline.outer_end_ns, deadline.vector_end_ns, end_ns),
                configuration=self.configuration,
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
                Evidence.HELPER: startup.record(),
                Evidence.START_SOURCES: self.start_sources.get(mutation.action),
                Evidence.PHASE: phase.value,
                Evidence.IDENTITY: identity,
                Evidence.PARENT: _unit(current_parent),
                Evidence.GUEST: _unit(current_guest) if current_guest is not None else None,
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

    async def _configured(
        self, mutation: NativeMutation, end_ns: int, deadline: AdmittedDeadline, startup: HelperStartup
    ) -> ActionResult:
        """Consume actual protected setup data while the original supervisor owns observation and the helper owns its flock."""
        if self.guest_binding is None or self.prepared_guest_manifest is None or self.population is None:
            raise ValueError(ERROR_BINDING)
        self._helper_frontier(startup)
        self._require_source_closure(masked=True)
        native = mutation.evidence
        producer_end = positive_integer(native, Key.COMMAND_END_NS)
        if (
            native.get(Key.AUTHORITY) != Authority.GUEST
            or native.get(Key.UNIT_NAME) != "tc-ra-guest-setup.service"
            or type(native.get(Key.EXIT_STATUS)) is not int
            or native[Key.EXIT_STATUS] != 0
            or producer_end > end_ns
        ):
            raise ValueError(ERROR_BINDING)
        admitted = AdmittedDeadline(deadline.outer_end_ns, deadline.vector_end_ns, producer_end)
        manifest = narrow_setup_manifest(self.prepared_guest_manifest, producer_end)
        self.guest_binding.require_original(admitted)
        read = read_guest_evidence(
            self.guest_binding.root_fd,
            self.guest_binding.facts.root_uid,
            self.guest_binding.facts.root_uid,
            EvidenceLeaf.SETUP,
            admitted,
        )
        self.guest_setup_read = read
        setup = validate_setup_journal(read, manifest, self.package)
        self.guest_setup_evidence = setup
        self.active_guest_manifest = manifest
        if (
            native.get("manifest_sha256") != setup.manifest_sha256
            or setup.facts.system_manager.start_ticks != self.guest_binding.facts.controller.start_ticks
        ):
            raise ValueError(ERROR_BINDING)
        parent, guest = await self.manager.read_active_boundary(producer_end)
        await self.manager.check_identity(producer_end)
        self.guest_binding.require_original(admitted)
        sample = self.population.sample(producer_end)
        if sample.faults or sample.populated is not True:
            raise ValueError(ERROR_BINDING)
        helpers = self._helper_frontier(startup)
        boundary = self.manager.reconcile_jobs(self._job_scope(), tuple(self._accepted))
        if time.monotonic_ns() >= producer_end:
            raise TimeoutError(ERROR_BINDING)
        return ActionResult(
            Outcome.SUCCEEDED,
            {
                Evidence.PHASE: Phase.GUEST_CONFIGURED.value,
                Evidence.NATIVE_RECEIPT: dict(native),
                "setup_manifest_sha256": setup.manifest_sha256,
                "setup_journal_sha256": read.sha256,
                "setup_facts": parse_object(json.dumps(asdict(setup.facts), allow_nan=False).encode(UTF8)),
                "setup_completed_ns": setup.completed_ns,
                "setup_command_count": setup.command_count,
                "guest_binding": self.guest_binding.record(),
                "setup_journal_read": {
                    Evidence.READ_STARTED_NS: read.started_ns,
                    Evidence.READ_FINISHED_NS: read.finished_ns,
                    "end_ns": read.end_ns,
                    "file_identity": parse_object(json.dumps(asdict(read.before), allow_nan=False).encode(UTF8)),
                },
                Evidence.PARENT: _unit(parent),
                Evidence.GUEST: _unit(guest),
                Evidence.HELPERS: helpers,
                Evidence.SEQUENCE: boundary.sequence,
                Evidence.OBSERVED_NS: boundary.observed_ns,
                Evidence.POPULATION: {Evidence.RAW: sample.raw.decode(UTF8), Evidence.POPULATED: sample.populated},
            },
        )

    async def _payload_start(
        self, mutation: NativeMutation, end_ns: int, deadline: AdmittedDeadline, startup: HelperStartup
    ) -> ActionResult:
        """Native Type=exec start completion is separate from payload admission, report and functional completion."""
        if self.guest_binding is None or self.prepared_payload_manifest is None or self.population is None:
            raise ValueError(ERROR_BINDING)
        native = mutation.evidence
        digest = hashlib.sha256(self.prepared_payload_manifest).hexdigest()
        if (
            native.get(Key.AUTHORITY) != Authority.GUEST
            or native.get(Key.UNIT_NAME) != "tc-ra-payload.service"
            or type(native.get(Key.EXIT_STATUS)) is not int
            or native[Key.EXIT_STATUS] != 0
            or native.get("manifest_sha256") != digest
            or positive_integer(native, Key.COMMAND_END_NS) > end_ns
        ):
            raise ValueError(ERROR_BINDING)
        payload_end = GuestContext(self.prepared_payload_manifest, self.package).payload_deadline().effective_end()
        self.payload_start_receipt = mutation
        end = min(end_ns, deadline.effective_end(), positive_integer(native, Key.COMMAND_END_NS))
        observation = await self._payload_observation(
            AdmittedDeadline(deadline.outer_end_ns, deadline.vector_end_ns, end), startup
        )
        self.active_guest_manifest = self.prepared_payload_manifest
        return ActionResult(
            Outcome.SUCCEEDED,
            {
                Evidence.PHASE: Phase.PAYLOAD_STARTED.value,
                Evidence.NATIVE_RECEIPT: dict(native),
                "payload_manifest_sha256": digest,
                "payload_end_ns": payload_end,
                "payload_observation": observation,
            },
        )

    async def _payload_observation(self, deadline: AdmittedDeadline, startup: HelperStartup | None) -> JsonObject:
        """Observe the original active-to-terminal lifecycle without requiring work to outlive its supervisor."""
        if self.guest_binding is None or self.prepared_payload_manifest is None or self.population is None:
            raise ValueError(ERROR_BINDING)
        end = deadline.effective_end()
        await self.manager.check_identity(end)
        parent, guest = await self.manager.read_active_boundary(end, allow_terminal=True)
        self.guest_binding.require_root_view(deadline)
        self._require_source_closure(masked=True)
        completion = None
        if guest.unit.get(Property.ACTIVE_STATE) != ACTIVE:
            completion = capture_payload_completion(
                self.guest_binding, self.prepared_payload_manifest, self.package, deadline
            )
            self.payload_completions.append(completion)
            self._retain_automatic_cleanup(completion)
            self.guest_binding.require_root_view(deadline)
        sample = self.population.sample(end)
        if sample.faults or sample.populated is None:
            raise ValueError(ERROR_BINDING)
        helpers = self._helper_frontier(startup)
        boundary = self.manager.reconcile_jobs(self._job_scope(), tuple(self._accepted))
        evidence: JsonObject = {
            Evidence.PARENT: _unit(parent),
            Evidence.GUEST: _unit(guest),
            Evidence.HELPERS: helpers,
            Evidence.SEQUENCE: boundary.sequence,
            Evidence.OBSERVED_NS: boundary.observed_ns,
            Evidence.POPULATION: {Evidence.RAW: sample.raw.decode(UTF8), Evidence.POPULATED: sample.populated},
            "completion_capture": completion.record() if completion is not None else None,
            "normal_service_exit": guest.unit.get(Property.ACTIVE_STATE) == "inactive"
            and guest.specific.get("Result") == "success"
            and type(guest.specific.get("ExecMainCode")) is int
            and guest.specific["ExecMainCode"] == 1
            and type(guest.specific.get("ExecMainStatus")) is int
            and guest.specific["ExecMainStatus"] == 0
            and type(guest.specific.get("NRestarts")) is int
            and guest.specific["NRestarts"] == 0,
        }
        self.payload_observations.append(evidence)
        if time.monotonic_ns() >= end:
            raise TimeoutError(ERROR_BINDING)
        return evidence

    def _retain_automatic_cleanup(self, completion: PayloadCompletion) -> None:
        if completion.shutdown is None or self.prepared_payload_manifest is None:
            return
        try:
            validate_shutdown_journal(completion.shutdown, self.prepared_payload_manifest, self.package)
        except (OSError, ValueError, RuntimeError, KeyError):
            # The original raw bytes/error remain in PayloadCompletion, separately from report validity.
            return
        if self.automatic_cleanup_read is None:
            self.automatic_cleanup_read = completion.shutdown
        elif self.automatic_cleanup_read.sha256 != completion.shutdown.sha256:
            raise ValueError(ERROR_BINDING)

    async def _shutdown_receipt(
        self, mutation: NativeMutation, end_ns: int, deadline: AdmittedDeadline, startup: HelperStartup
    ) -> ActionResult:
        if self.automatic_cleanup_read is None or self.prepared_payload_manifest is None:
            raise ValueError(ERROR_BINDING)
        native = mutation.evidence
        if (
            native.get(Key.AUTHORITY) != Authority.GUEST
            or native.get(Key.UNIT_NAME) != "tc-ra-poweroff.service"
            or native.get("receipt_mode") != "consumed-automatic-cleanup"
            or native.get("manifest_sha256") != hashlib.sha256(self.prepared_payload_manifest).hexdigest()
            or native.get("shutdown_journal_sha256") != self.automatic_cleanup_read.sha256
            or positive_integer(native, Key.COMMAND_END_NS) > end_ns
        ):
            raise ValueError(ERROR_BINDING)
        observed = await self._payload_observation(
            AdmittedDeadline(deadline.outer_end_ns, deadline.vector_end_ns, end_ns), startup
        )
        return ActionResult(
            Outcome.SUCCEEDED,
            {
                Evidence.PHASE: Phase.SHUTDOWN_REQUESTED.value,
                Evidence.NATIVE_RECEIPT: dict(native),
                "original_guest_request": [parse_object(row) for row in self.automatic_cleanup_read.data.splitlines()],
                "payload_observation": observed,
            },
        )

    def close_population(self) -> None:
        """End observation explicitly; callers owe retention/release decisions separately."""
        if self.population is not None:
            if self._loop is not None:
                self._loop.remove_reader(self.population.fileno())
                self._loop = None
            self.population.close()
