"""Explicit application entry through the original enclosure loop and retained phase owners."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import signal
import stat
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

from tools.ci.enclosure_actions import Key as MutationKey
from tools.ci.enclosure_actions import NativeMutation
from tools.ci.enclosure_admission import ACTUAL_SOURCE_ROOT, SourceAdmission, _verify_file
from tools.ci.enclosure_contract import (
    NANOSECONDS,
    STATIC_DIGEST,
    Action,
    AdmittedDeadline,
    Deadline,
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
from tools.ci.enclosure_exchange import HelperCollection, HelperStartup, collect_helper_startup, run_privileged
from tools.ci.enclosure_guest import Purpose
from tools.ci.enclosure_guest_evidence import GuestFileRead
from tools.ci.enclosure_host import inspect_host_substrate
from tools.ci.enclosure_inputs import FIXED_INPUT_DIRECTORY, FixedInputIntake
from tools.ci.enclosure_journal import ActionResult, Outcome
from tools.ci.enclosure_journal import Key as JournalKey
from tools.ci.enclosure_native import NativeRead
from tools.ci.enclosure_owner import MANIFEST_LIMIT, QUALIFICATION_INTAKE_NAME, RunOwner, _write_private_file
from tools.ci.enclosure_owner import Key as OwnerKey
from tools.ci.enclosure_privileged import PrivilegedCommands, ReadScope

if TYPE_CHECKING:
    from tools.ci.enclosure_manager import ManagerObserver
    from tools.ci.enclosure_payload_driver import PayloadDrive
    from tools.ci.enclosure_phases import BindingPhases

STATIC_DIRECTORY: Final = Path("docs/local/design/architecture/runtime-acceptance")
RECOVERY_FILE: Final = "p4-recovery.json"
UTF8: Final = "utf-8"
ERROR_INTAKE: Final = "the explicit supervisor requires the selected protected realization and exact candidate source"
ERROR_PROVISION: Final = "the original provisioning exchange did not establish its declared preflight boundary"
ERROR_UNFINISHED: Final = (
    "complete independent eligibility, conditional release and workflow upload are not yet composed; "
    "available physical facts cannot supply final acceptance"
)
ERROR_EXPORT: Final = "the declared named enclosure export did not complete within its original allowance"
RUNNER_TEMP: Final = "RUNNER_TEMP"
WORKFLOW_LINT: Final = "/.github/workflows/lint-test.yaml"
WORKFLOW_RELEASE: Final = "/.github/workflows/release.yaml"
WORKFLOW_SEPARATOR: Final = "@"
WITNESS_SUFFIX: Final = ".p4-witness.json"
RECOVERY_SUFFIX: Final = ".p4-recovery.json"
JSON_SEPARATORS: Final = (",", ":")
OWNED_DESCRIPTOR: Final = "/proc/{pid}/fd/{descriptor}"
QUALIFICATION_Q2_FILE: Final = "qualification-Q2.json"
ERROR_QUALIFICATION_UNFINISHED: Final = (
    "Q3 through Q8 source composition remains incomplete; later vectors were not run"
)
ERROR_QUALIFICATION: Final = "qualification source or its original finite vector allowance is inconsistent"
ERROR_INTERRUPTED: Final = "the original supervisor observed termination; no later vector is admitted"
QUALIFICATION_Q2: Final = "Q2"

type ExportWriter = Callable[[Path, bytes], None]


class ExportField(StrEnum):
    """The declared outside report map and local, separately observed write receipts."""

    REPORTS = "reports"
    EXPORTS = "exports"
    LINT_TEST = "lint_test"
    RELEASE_CANDIDATE = "release_candidate"
    PRIMARY = "primary"
    WITNESS = "witness"
    RECOVERY = "recovery"
    STATUS = "status"
    PATH = "path"
    BYTES = "bytes"
    SHA256 = "sha256"
    END_NS = "end_ns"
    FINISHED_NS = "finished_ns"
    STAGE = "stage"
    SCHEMA_VERSION = "schema_version"
    SOURCE_COMMIT = "source_commit"
    SOURCE_TREE = "source_tree"
    RUN_IDENTITY = "run_identity"
    STATIC_LOCK_SHA256 = "static_lock_sha256"
    REALIZATION_SHA256 = "realization_sha256"
    INNER_REPORT_SHA256 = "inner_report_sha256"
    WITNESS_SHA256 = "witness_sha256"
    FUNCTIONAL_OUTCOME = "functional_outcome"
    CLEANUP_OUTCOME = "cleanup_outcome"
    RESOURCE_RELEASE_OUTCOME = "resource_release_outcome"
    LOCAL_EXPORT_READBACK = "local_export_readback"
    ROLLING_INPUT_OBSERVATION_REFS = "rolling_input_observation_refs"
    ORIGINAL_REPORT_BASE64 = "original_report_bytes_base64"
    ORIGINAL_REPORT_READ = "original_report_read"
    READ_ERROR = "read_error"
    READ_STARTED_NS = "read_started_ns"
    READ_FINISHED_NS = "read_finished_ns"
    READ_LIMIT = "read_limit"
    BEFORE = "before"
    AFTER = "after"
    NAMED_LEAF = "named_leaf"
    ERROR = "error"
    RECOVERY_RECORD = "recovery_record"
    INPUT_VALIDATION = "input_validation"


class ExportState(StrEnum):
    """Local export state never supplies application acceptance or a later upload result."""

    FINAL = "final"
    UNPROVEN = "retained-unproven"
    NOT_ATTEMPTED = "not-attempted"
    UNAVAILABLE = "unavailable"
    READ_BACK = "read-back"
    PRIMARY_PENDING = "primary-readback-pending"
    FAILED = "failed"
    LATE = "late-readback"


class QualificationField(StrEnum):
    """Declared finite-vector records remain separate from a complete qualification verdict."""

    OUTER_BUDGET = "outer_budget_seconds"
    RESERVE = "closure_export_reserve_seconds"
    VECTORS = "vectors"
    VECTOR_ORDER = "vector_order"
    ID = "id"
    BUDGET = "budget_seconds"
    STATE = "state"
    STARTED_NS = "started_ns"
    FINISHED_NS = "finished_ns"
    END_NS = "end_ns"
    ERROR = "error"
    SOURCE_FACTS = "source_facts"
    HOST_FACTS = "host_facts"
    INPUT_FACTS = "input_facts"
    RECORDS = "qualification_vectors"
    READ_PROCESSES = "read_only_processes"
    PID = "pid"
    EXIT_STATUS = "exit_status"
    PHASES = "phases"
    GUEST_ADMISSION = "guest_admission"
    CONFIGURED = "configured"
    MANIFEST_SHA256 = "manifest_sha256"


class QualificationState(StrEnum):
    """An unexecuted vector never inherits success from an earlier vector or imported contract."""

    NOT_RUN = "not_run"
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


def _error(error: BaseException | None) -> JsonObject | None:
    if error is None:
        return None
    return {
        "error_class": type(error).__name__,
        "detail": str(error),
        "notes": list(getattr(error, "__notes__", ())),
    }


@dataclass
class SupervisorRun:
    """The actual handles outlive a failed stage; no restart or replacement constructor is offered."""

    owner: RunOwner
    package: StaticPackage
    realization_bytes: bytes
    report_path: Path
    write_export: ExportWriter
    startups: list[HelperStartup] = field(default_factory=list)
    collections: list[HelperCollection] = field(default_factory=list)
    manager: ManagerObserver | None = None
    phases: BindingPhases | None = None
    payload: PayloadDrive | None = None
    provision: ActionResult | None = None
    primary_error: BaseException | None = None
    finalization_errors: list[BaseException] = field(default_factory=list)
    payload_inputs: JsonObject | None = None
    termination: JsonObject | None = None
    exports: JsonObject = field(default_factory=dict)
    purpose: Purpose = Purpose.APPLICATION
    intake: FixedInputIntake | None = None
    input_directory: Path | None = None
    initial_deadline: AdmittedDeadline | None = None
    read_commands: PrivilegedCommands | None = None
    qualification_vectors: list[JsonObject] = field(default_factory=list)
    active_vector: JsonObject | None = None

    def original_report(self) -> GuestFileRead | None:
        """Keep the original captured bytes even when ensuing extraction/validation fails."""
        if self.phases is not None:
            if self.phases.extracted_report is not None:
                return self.phases.extracted_report
            for completion in reversed(self.phases.payload_completions):
                if completion.report is not None:
                    return completion.report
        return None

    def record(self) -> JsonObject:
        phases = self.phases
        return {
            "schema_version": 1,
            "stage": "retained-source-prefix",
            "status": "retained-unproven",
            OwnerKey.PURPOSE: self.purpose.value,
            "binding": self.owner.journal.owner_record,
            "workflow": self.owner.workflow.record(),
            "manifest_sha256": hashlib.sha256(self.owner.manifest_bytes).hexdigest(),
            "provision": self.provision.record(Action.PROVISION) if self.provision is not None else None,
            "phases": {action.value: receipt.record(action) for action, receipt in phases.results.items()}
            if phases is not None
            else {},
            "payload": self.payload.record() if self.payload is not None else None,
            "physical_witness_sha256": hashlib.sha256(phases.p4_witness_bytes).hexdigest()
            if phases is not None and phases.p4_witness_bytes is not None
            else None,
            "payload_input_validation": self.payload_inputs,
            "termination": self.termination,
            "helpers": [collection.record() for collection in self.collections],
            "primary_error": _error(self.primary_error),
            "finalization_errors": [_error(error) for error in self.finalization_errors],
            "retained_run": str(self.owner.directory),
            "resource_release_outcome": "not-attempted",
            "local_export_readback": dict(self.exports),
            "unfinished_source": ERROR_QUALIFICATION_UNFINISHED
            if self.purpose is Purpose.QUALIFICATION
            else ERROR_UNFINISHED,
            QualificationField.RECORDS: list[JsonValue](self.qualification_vectors),
            QualificationField.READ_PROCESSES: [
                {QualificationField.PID: process.pid, QualificationField.EXIT_STATUS: process.returncode}
                for process in self.read_commands.processes
            ]
            if self.read_commands is not None
            else [],
            OwnerKey.OFFLINE_INPUTS: dict(self.intake.facts) if self.intake is not None else None,
        }


# A bounded report is not permission to cancel an unresolved original native startup.
# Keep its owning loop/objects until interpreter exit rather than Runner's blanket task cancellation.
_RETAINED: list[tuple[asyncio.AbstractEventLoop, SupervisorRun]] = []


def _encoded(record: JsonObject) -> bytes:
    return json.dumps(record, sort_keys=True, separators=JSON_SEPARATORS, allow_nan=False).encode(UTF8)


def _export_destination(run: SupervisorRun) -> Path:
    """Match the existing report argument to this workflow's exact static primary map."""
    workflow = run.owner.workflow.workflow_ref.partition(WORKFLOW_SEPARATOR)[0]
    if workflow.endswith(WORKFLOW_LINT):
        key = ExportField.LINT_TEST
    elif workflow.endswith(WORKFLOW_RELEASE):
        key = ExportField.RELEASE_CANDIDATE
    else:
        raise ValueError(ERROR_EXPORT)
    root = Path(os.environ[RUNNER_TEMP]).resolve(strict=True)
    exports = object_value(
        object_value(parse_object(run.package.recipe_bytes)[ExportField.REPORTS])[ExportField.EXPORTS]
    )
    expected = root / text(object_value(exports[key]), ExportField.PRIMARY)
    # The output is the declared workflow address, never an inner report path.
    # Do not follow a symlinked subdirectory outside that workflow's export tree.
    if run.report_path.absolute() != expected or expected.parent.resolve() != expected.parent:
        raise ValueError(ERROR_EXPORT)
    return expected


def _write_export(run: SupervisorRun, key: ExportField, path: Path, data: bytes, end_ns: int) -> None:
    """One existing writer invocation, with its actual return and original cutoff retained."""
    if time.monotonic_ns() >= end_ns:
        raise TimeoutError(ERROR_EXPORT)
    try:
        run.write_export(path, data)
    except Exception as error:
        run.exports[key] = {
            ExportField.STATUS: ExportState.FAILED.value,
            ExportField.PATH: str(path),
            ExportField.ERROR: _error(error),
        }
        run.finalization_errors.append(error)
        return
    finished = time.monotonic_ns()
    run.exports[key] = {
        ExportField.STATUS: ExportState.READ_BACK.value if finished < end_ns else ExportState.LATE.value,
        ExportField.PATH: str(path),
        ExportField.BYTES: len(data),
        ExportField.SHA256: hashlib.sha256(data).hexdigest(),
        ExportField.END_NS: end_ns,
        ExportField.FINISHED_NS: finished,
    }
    if finished >= end_ns:
        raise TimeoutError(ERROR_EXPORT)


def _export(run: SupervisorRun) -> None:
    """Export the available immutable prefix, without release or final eligibility credit."""
    budget = object_value(parse_object(run.package.recipe_bytes)[Field.BUDGET_SECONDS])
    original = AdmittedDeadline(run.owner.journal.deadline.end_ns, None, None)
    end_ns = original.command_end(positive_integer(budget, Field.EXPORT_MAX))
    path = _export_destination(run)
    phases = run.phases
    witness = phases.p4_witness_bytes if phases is not None else None
    if witness is not None:
        _write_export(run, ExportField.WITNESS, path.with_name(path.name + WITNESS_SUFFIX), witness, end_ns)
    else:
        run.exports[ExportField.WITNESS] = {ExportField.STATUS: ExportState.UNAVAILABLE.value}
    read = run.original_report()
    recovery: JsonObject = {
        ExportField.RECOVERY_RECORD: run.record(),
        ExportField.ORIGINAL_REPORT_BASE64: base64.b64encode(read.data).decode(UTF8) if read is not None else None,
        ExportField.ORIGINAL_REPORT_READ: {
            ExportField.SHA256: read.sha256,
            ExportField.BYTES: len(read.data),
            ExportField.READ_ERROR: _error(read.read_error),
            ExportField.READ_STARTED_NS: read.started_ns,
            ExportField.READ_FINISHED_NS: read.finished_ns,
            ExportField.END_NS: read.end_ns,
            ExportField.READ_LIMIT: read.read_limit,
            ExportField.BEFORE: cast(JsonObject, asdict(read.before)),
            ExportField.AFTER: cast(JsonObject, asdict(read.after)) if read.after is not None else None,
            ExportField.NAMED_LEAF: cast(JsonObject, asdict(read.named_leaf)) if read.named_leaf is not None else None,
        }
        if read is not None
        else None,
    }
    _write_export(run, ExportField.RECOVERY, path.with_name(path.name + RECOVERY_SUFFIX), _encoded(recovery), end_ns)
    binding = run.owner.journal.binding
    aggregate: JsonObject = {
        ExportField.SCHEMA_VERSION: 1,
        ExportField.STAGE: ExportState.FINAL.value,
        ExportField.STATUS: ExportState.UNPROVEN.value,
        ExportField.SOURCE_COMMIT: binding.candidate_commit,
        ExportField.SOURCE_TREE: binding.candidate_tree,
        ExportField.RUN_IDENTITY: run.owner.journal.owner_record,
        ExportField.STATIC_LOCK_SHA256: STATIC_DIGEST,
        ExportField.REALIZATION_SHA256: binding.realization_digest,
        ExportField.INNER_REPORT_SHA256: read.sha256 if read is not None else None,
        ExportField.WITNESS_SHA256: hashlib.sha256(witness).hexdigest() if witness is not None else None,
        ExportField.FUNCTIONAL_OUTCOME: ExportState.UNPROVEN.value,
        ExportField.CLEANUP_OUTCOME: ExportState.UNPROVEN.value,
        ExportField.RESOURCE_RELEASE_OUTCOME: ExportState.NOT_ATTEMPTED.value,
        ExportField.LOCAL_EXPORT_READBACK: {**run.exports, ExportField.PRIMARY: ExportState.PRIMARY_PENDING.value},
        ExportField.ROLLING_INPUT_OBSERVATION_REFS: None,
        ExportField.INPUT_VALIDATION: run.payload_inputs,
        ExportField.RECOVERY_RECORD: run.record(),
    }
    # The primary cannot attest to its own later readback. The returned outer
    # receipt records that actual result; no file here claims remote upload.
    _write_export(run, ExportField.PRIMARY, path, _encoded(aggregate), end_ns)
    # Update this controller's already-owned recovery prefix with actual local
    # outcomes. This is another evidence revision, never a second native action
    # or another attempt to write a failed workflow artifact.
    if time.monotonic_ns() >= end_ns:
        raise TimeoutError(ERROR_EXPORT)
    directory = Path(OWNED_DESCRIPTOR.format(pid=os.getpid(), descriptor=run.owner.journal.directory_fd))
    run.write_export(directory / RECOVERY_FILE, _encoded(run.record()))
    if time.monotonic_ns() >= end_ns:
        raise TimeoutError(ERROR_EXPORT)


def _realization(path: Path, deadline: AdmittedDeadline) -> bytes:
    """Read the selected record as bytes; its address and digest never assert review approval."""
    if time.monotonic_ns() >= deadline.effective_end():
        raise TimeoutError(ERROR_INTAKE)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MANIFEST_LIMIT:
            raise ValueError(ERROR_INTAKE)
        data = os.read(descriptor, MANIFEST_LIMIT + 1)
        after = os.fstat(descriptor)
        if len(data) != before.st_size or (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError(ERROR_INTAKE)
    finally:
        os.close(descriptor)
    if not data or len(data) > MANIFEST_LIMIT:
        raise ValueError(ERROR_INTAKE)
    _verify_file(path, {Field.SHA256: hashlib.sha256(data).hexdigest(), Field.BYTES: len(data)}, deadline)
    parse_object(data)
    return data


async def _provision(run: SupervisorRun, deadline: AdmittedDeadline, cap: int, vector: str | None) -> None:
    async def observed(native: NativeMutation, end: int, startup: HelperStartup) -> ActionResult:
        if (
            native.action is not Action.PROVISION
            or startup not in run.startups
            or startup.identity is None
            or native.evidence.get(MutationKey.COMMAND_END_NS) != end
            or time.monotonic_ns() >= end
        ):
            raise ValueError(ERROR_PROVISION)
        startup.identity.require_alive()
        run.owner.journal.binding.controller.require_alive()
        record = parse_object(run.owner.manifest_bytes)
        if native.evidence.get("rootfs") != record[OwnerKey.ROOTFS]:
            raise ValueError(ERROR_PROVISION)
        substrate = object_value(native.evidence["host_substrate"])
        if (
            substrate.get("container_installed") is not True
            or substrate.get("host_boot_id") != run.owner.journal.binding.controller.boot_id
            or native.evidence.get("host_network_active_state") != "active"
        ):
            raise ValueError(ERROR_PROVISION)
        # The existing producer owns actual substrate/staging checks; this receipt
        # records their completed result, never guest admission or physical closure.
        return ActionResult(
            Outcome.SUCCEEDED,
            {"phase": Phase.PREFLIGHT.value, "native_receipt": dict(native.evidence), "helper": startup.record()},
        )

    run.provision = await run_privileged(run.owner, Action.PROVISION, deadline, cap, vector, observed, run.startups)
    if run.provision.status is not Outcome.SUCCEEDED:
        raise ValueError(ERROR_PROVISION)


async def _configured_guest(
    run: SupervisorRun,
    original: AdmittedDeadline,
    selected: frozenset[str],
    vector: str | None,
) -> BindingPhases:
    """One real provision/parent/guest/setup composition serves the two declared purposes."""
    budget = object_value(parse_object(run.package.recipe_bytes)[Field.BUDGET_SECONDS])
    cap = positive_integer(budget, Field.NORMAL_COMMAND_MAX)
    boot_cap = positive_integer(budget, Field.GUEST_BOOT_OR_CONFIGURATION_MAX)
    await _provision(run, original, cap, vector)
    source = SourceAdmission(
        run.realization_bytes,
        ACTUAL_SOURCE_ROOT,
        run.package,
        run.owner.journal.binding,
    )
    library = source.verify_observer_library(run.owner, original)
    sys.path.insert(0, str(library))
    # This is the first observer import. Its actual wheel members were bound
    # above, and every later helper also checks the loaded-source inventory.
    from tools.ci.enclosure_manager import ManagerObserver  # noqa: PLC0415
    from tools.ci.enclosure_phases import BindingPhases  # noqa: PLC0415

    record = parse_object(run.owner.manifest_bytes)
    manager = ManagerObserver(frozenset({text(record, OwnerKey.PARENT_UNIT), text(record, OwnerKey.GUEST_UNIT)}))
    run.manager = manager
    end = min(original.command_end(cap), original.outer_end_ns - run.owner.journal.deadline.reserve_ns)
    await manager.connect(end)
    phases = BindingPhases(run.owner, manager, run.package)
    run.phases = phases
    if run.provision is None:
        raise ValueError(ERROR_PROVISION)
    phases.retain_provision(run.provision, tuple(run.startups))
    for action, limit in (
        (Action.CREATE_PARENT, cap),
        (Action.START_GUEST, boot_cap),
        (Action.MASK_GUEST, cap),
        (Action.GUEST_SETUP, boot_cap),
    ):
        result = await phases.perform(action, original, limit, vector, selected=selected)
        if result.status is not Outcome.SUCCEEDED:
            raise RuntimeError(f"original enclosure action did not succeed: {action}")
    return phases


async def _application(
    run: SupervisorRun,
    selected: frozenset[str],
    validate_payload: Callable[[bytes, bytes, StaticPackage], JsonObject],
) -> None:
    original = AdmittedDeadline(run.owner.journal.deadline.end_ns, None, None)
    budget = object_value(parse_object(run.package.recipe_bytes)[Field.BUDGET_SECONDS])
    phases = await _configured_guest(run, original, selected, None)
    run.payload = await phases.run_payload(original)
    run.collections.extend(run.payload.helpers)
    if run.payload.primary_error is not None:
        raise run.payload.primary_error
    if run.payload.closure_errors:
        raise run.payload.closure_errors[0]
    extraction = await phases.perform(Action.EXTRACT, original, positive_integer(budget, Field.EXPORT_MAX), None)
    if (
        extraction.status is not Outcome.SUCCEEDED
        or phases.extracted_report is None
        or phases.prepared_payload_manifest is None
    ):
        raise ValueError(ERROR_INTAKE)
    run.payload_inputs = validate_payload(phases.extracted_report.data, phases.prepared_payload_manifest, run.package)
    # These existing validators classify inputs; full creator/emitter/retention
    # eligibility is still owed. Never release or manufacture a final pass here.
    raise NotImplementedError(ERROR_UNFINISHED)


def _qualification_rows(package: StaticPackage) -> list[JsonObject]:
    declared = parse_object(package.qualification_bytes)
    values = declared[QualificationField.VECTORS]
    if not isinstance(values, list):
        raise ValueError(ERROR_QUALIFICATION)
    rows: list[JsonObject] = []
    for value in values:
        row = object_value(value)
        rows.append(
            {
                QualificationField.ID: text(row, QualificationField.ID),
                QualificationField.BUDGET: positive_integer(row, QualificationField.BUDGET),
                QualificationField.STATE: QualificationState.NOT_RUN.value,
            }
        )
    if [row[QualificationField.ID] for row in rows] != declared[QualificationField.VECTOR_ORDER]:
        raise ValueError(ERROR_QUALIFICATION)
    return rows


def _require_progress(run: SupervisorRun) -> None:
    if run.termination is not None:
        raise KeyboardInterrupt(ERROR_INTERRUPTED)


def _begin_vector(run: SupervisorRun, index: int) -> AdmittedDeadline:
    """Admit one declared vector against outer reserve; do not subtract reserve from its own cap."""
    _require_progress(run)
    row = run.qualification_vectors[index]
    budget = positive_integer(row, QualificationField.BUDGET)
    run.owner.journal.deadline.admit(budget)
    started = time.monotonic_ns()
    end = min(
        started + budget * NANOSECONDS,
        run.owner.journal.deadline.end_ns - run.owner.journal.deadline.reserve_ns,
    )
    row[QualificationField.STARTED_NS] = started
    row[QualificationField.END_NS] = end
    row[QualificationField.STATE] = QualificationState.STARTED.value
    run.active_vector = row
    if time.monotonic_ns() >= end:
        raise TimeoutError(ERROR_QUALIFICATION)
    return AdmittedDeadline(run.owner.journal.deadline.end_ns, end, None)


def _finish_vector(run: SupervisorRun, name: str, deadline: AdmittedDeadline) -> None:
    _require_progress(run)
    row = run.active_vector
    if row is None or deadline.effective_end() != row[QualificationField.END_NS]:
        raise ValueError(ERROR_QUALIFICATION)
    if time.monotonic_ns() >= deadline.effective_end():
        raise TimeoutError(ERROR_QUALIFICATION)
    row[QualificationField.FINISHED_NS] = time.monotonic_ns()
    row[QualificationField.STATE] = QualificationState.SUCCEEDED.value
    row[OwnerKey.BINDING] = run.owner.journal.owner_record
    row[QualificationField.MANIFEST_SHA256] = hashlib.sha256(run.owner.manifest_bytes).hexdigest()
    _write_private_file(run.owner.journal.directory_fd, name, _encoded(row))
    _require_progress(run)
    finished = time.monotonic_ns()
    if finished >= deadline.effective_end():
        raise TimeoutError(ERROR_QUALIFICATION)
    row[QualificationField.FINISHED_NS] = finished
    run.active_vector = None


async def _qualification(run: SupervisorRun) -> None:
    """Q1 reads precede actual Q2 effects; later unimplemented vectors supply no qualification pass."""
    if run.input_directory is None or run.initial_deadline is None:
        raise ValueError(ERROR_QUALIFICATION)
    _require_progress(run)
    first = run.initial_deadline
    active = run.active_vector
    if (
        active is None
        or active is not run.qualification_vectors[0]
        or active[QualificationField.ID] != ReadScope.QUALIFICATION_ADMISSION.value
        or first.outer_end_ns != run.owner.journal.deadline.end_ns
        or active[QualificationField.END_NS] != first.effective_end()
    ):
        raise ValueError(ERROR_QUALIFICATION)

    def progress() -> None:
        _require_progress(run)

    facts: JsonObject = {}
    active[QualificationField.INPUT_FACTS] = facts
    run.intake = FixedInputIntake.authenticate(run.package, run.input_directory, first, facts, progress)
    commands = PrivilegedCommands(run.owner, ReadScope.QUALIFICATION_ADMISSION, ACTUAL_SOURCE_ROOT, first)
    run.read_commands = commands

    def query(argv: tuple[str, ...], end_ns: int) -> NativeRead:
        _require_progress(run)
        return commands.query(argv, end_ns)

    source = SourceAdmission(run.realization_bytes, ACTUAL_SOURCE_ROOT, run.package, run.owner.journal.binding)
    active[QualificationField.SOURCE_FACTS] = list[JsonValue](source.verify(query, first))
    record = parse_object(run.owner.manifest_bytes)
    substrate = inspect_host_substrate(
        run.package,
        text(record, OwnerKey.IMAGE_VERSION),
        query,
        first,
        frozenset({text(record, OwnerKey.PARENT_UNIT), text(record, OwnerKey.GUEST_UNIT)}),
    )
    active[QualificationField.HOST_FACTS] = parse_object(_encoded(cast(JsonObject, asdict(substrate))))
    _finish_vector(run, QUALIFICATION_INTAKE_NAME, first)
    second = _begin_vector(run, 1)
    if run.active_vector is None or run.active_vector[QualificationField.ID] != QUALIFICATION_Q2:
        raise ValueError(ERROR_QUALIFICATION)
    phases = await _configured_guest(run, second, frozenset(), QUALIFICATION_Q2)
    run.active_vector[QualificationField.PHASES] = parse_object(_encoded(run.record()))[QualificationField.PHASES]
    run.active_vector[QualificationField.GUEST_ADMISSION] = phases.guest_admission
    run.active_vector[QualificationField.CONFIGURED] = (
        phases.configured.record(Action.GUEST_SETUP) if phases.configured is not None else None
    )
    _finish_vector(run, QUALIFICATION_Q2_FILE, second)
    raise NotImplementedError(ERROR_QUALIFICATION_UNFINISHED)


async def _finish(run: SupervisorRun) -> JsonObject:
    budget = object_value(parse_object(run.package.recipe_bytes)[Field.BUDGET_SECONDS])
    export_ns = positive_integer(budget, Field.EXPORT_MAX) * NANOSECONDS
    original = AdmittedDeadline(run.owner.journal.deadline.end_ns, None, None)
    closure_end = min(
        original.outer_end_ns - export_ns,
        time.monotonic_ns() + positive_integer(budget, Field.SHUTDOWN_MAX) * NANOSECONDS,
    )
    if run.payload is not None:
        closure_end = min(closure_end, run.payload.closure_end_ns)
    closure = AdmittedDeadline(original.outer_end_ns, None, closure_end)
    if run.read_commands is not None:
        for process in run.read_commands.processes:
            if process.returncode is not None:
                continue
            try:
                remaining = (closure.effective_end() - time.monotonic_ns()) / NANOSECONDS
                if remaining <= 0:
                    raise TimeoutError(ERROR_QUALIFICATION)
                process.wait(timeout=remaining)
            except BaseException as error:
                run.finalization_errors.append(error)
    collected = {id(item.startup) for item in run.collections}
    startups = run.phases.startups if run.phases is not None else tuple(run.startups)
    for startup in startups:
        if id(startup) in collected:
            continue
        try:
            run.collections.append(await collect_helper_startup(startup, run.owner, closure))
        except BaseException as error:
            run.finalization_errors.append(error)
    record = run.record()
    if time.monotonic_ns() >= original.effective_end():
        run.finalization_errors.append(TimeoutError("original outer allowance expired before recovery write"))
        return run.record()
    try:
        _write_private_file(
            run.owner.journal.directory_fd,
            RECOVERY_FILE,
            json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(UTF8),
        )
        if time.monotonic_ns() >= original.effective_end():
            raise TimeoutError("recovery write finished after the original outer allowance")
    except BaseException as error:
        run.finalization_errors.append(error)
    try:
        _export(run)
    except BaseException as error:
        run.finalization_errors.append(error)
    return run.record()


async def _drive(
    run: SupervisorRun,
    selected: frozenset[str],
    validate_payload: Callable[[bytes, bytes, StaticPackage], JsonObject],
) -> JsonObject:
    try:
        if run.purpose is Purpose.QUALIFICATION:
            await _qualification(run)
        else:
            await _application(run, selected, validate_payload)
    except BaseException as error:
        run.primary_error = error
        if run.active_vector is not None:
            run.active_vector[QualificationField.STATE] = QualificationState.FAILED.value
            run.active_vector[QualificationField.ERROR] = _error(error)
            run.active_vector[QualificationField.FINISHED_NS] = time.monotonic_ns()
    return await _finish(run)


def run_supervisor(
    manifest: Path,
    source_root: Path,
    source_commit: str | None,
    source_tree: str | None,
    selected: frozenset[str],
    validate_payload: Callable[[bytes, bytes, StaticPackage], JsonObject],
    report_path: Path,
    write_export: ExportWriter,
    *,
    purpose: Purpose = Purpose.APPLICATION,
) -> JsonObject:
    """Explicit declared outside role only; ordinary roleless CI never reaches this path."""
    started_ns = time.monotonic_ns()
    if source_root.resolve(strict=True) != ACTUAL_SOURCE_ROOT or os.geteuid() != 0:
        raise ValueError(ERROR_INTAKE)
    package = StaticPackage.load(ACTUAL_SOURCE_ROOT / STATIC_DIRECTORY, ACTUAL_SOURCE_ROOT)
    budget = object_value(parse_object(package.recipe_bytes)[Field.BUDGET_SECONDS])
    rows = _qualification_rows(package) if purpose is Purpose.QUALIFICATION else []
    if purpose is Purpose.QUALIFICATION:
        declaration = parse_object(package.qualification_bytes)
        outer_seconds = positive_integer(declaration, QualificationField.OUTER_BUDGET)
        reserve_seconds = positive_integer(declaration, QualificationField.RESERVE)
    else:
        outer_seconds = positive_integer(budget, Field.RUNTIME_OUTER_MAX)
        reserve_seconds = positive_integer(budget, Field.CLOSURE_EXPORT_RESERVE)
    deadline = Deadline(started_ns, started_ns + outer_seconds * NANOSECONDS, reserve_seconds * NANOSECONDS)
    initial = AdmittedDeadline(deadline.end_ns, None, None)
    if rows:
        deadline.admit(positive_integer(rows[0], QualificationField.BUDGET))
        initial = AdmittedDeadline(
            deadline.end_ns,
            min(
                deadline.end_ns - deadline.reserve_ns,
                started_ns + positive_integer(rows[0], QualificationField.BUDGET) * NANOSECONDS,
            ),
            None,
        )
        rows[0][QualificationField.STARTED_NS] = started_ns
        rows[0][QualificationField.END_NS] = initial.effective_end()
        rows[0][QualificationField.STATE] = QualificationState.STARTED.value
    realization = _realization(manifest, initial)
    record = parse_object(realization)
    candidate = text(record, JournalKey.CANDIDATE_COMMIT)
    tree = text(record, JournalKey.CANDIDATE_TREE)
    if (
        (source_commit is not None and source_commit != candidate)
        or (source_tree is not None and source_tree != tree)
        or (purpose is Purpose.APPLICATION and (source_commit is None or source_tree is None))
        or (purpose is Purpose.QUALIFICATION and selected)
    ):
        raise ValueError(ERROR_INTAKE)
    owner = RunOwner.create(
        package,
        candidate,
        tree,
        hashlib.sha256(realization).hexdigest(),
        deadline,
        purpose,
        realization_bytes=realization,
        selected=selected,
    )
    run = SupervisorRun(
        owner,
        package,
        realization,
        report_path,
        write_export,
        purpose=purpose,
        input_directory=manifest.parent / FIXED_INPUT_DIRECTORY if rows else None,
        initial_deadline=initial,
        qualification_vectors=rows,
        active_vector=rows[0] if rows else None,
    )
    loop = asyncio.new_event_loop()
    task = loop.create_task(_drive(run, selected, validate_payload))
    previous = signal.getsignal(signal.SIGTERM)

    def stop(_signum: int, _frame: object) -> None:
        # Cancel the progression, never its shielded original native startup.
        if run.termination is None:
            run.termination = {"signal": _signum, "observed_ns": time.monotonic_ns()}
            loop.call_soon_threadsafe(task.cancel)

    signal.signal(signal.SIGTERM, stop)
    try:
        result = loop.run_until_complete(task)
        return result
    finally:
        signal.signal(signal.SIGTERM, previous)
        # Keep original observations, descriptors, startup tasks and native process
        # handles through bounded final reporting. No loop-wide cancellation,
        # descriptor cleanup or parent removal supplies an uncertainty verdict.
        _RETAINED.append((loop, run))
