"""Explicit application entry through the original enclosure loop and retained phase owners."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal
import stat
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final

from tools.ci.enclosure_actions import Key as MutationKey
from tools.ci.enclosure_actions import NativeMutation
from tools.ci.enclosure_admission import ACTUAL_SOURCE_ROOT, SourceAdmission, _verify_file
from tools.ci.enclosure_contract import (
    NANOSECONDS,
    Action,
    AdmittedDeadline,
    Deadline,
    Field,
    JsonObject,
    Phase,
    StaticPackage,
    object_value,
    parse_object,
    positive_integer,
    text,
)
from tools.ci.enclosure_exchange import HelperCollection, HelperStartup, collect_helper_startup, run_privileged
from tools.ci.enclosure_guest import Purpose
from tools.ci.enclosure_journal import ActionResult, Outcome
from tools.ci.enclosure_owner import MANIFEST_LIMIT, RunOwner, _write_private_file
from tools.ci.enclosure_owner import Key as OwnerKey

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
    "complete independent eligibility, conditional release and workflow export are not yet composed; "
    "available physical facts cannot supply final acceptance"
)


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

    def record(self) -> JsonObject:
        phases = self.phases
        return {
            "schema_version": 1,
            "stage": "retained-source-prefix",
            "status": "retained-unproven",
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
            "local_export_readback": "not-attempted",
            "unfinished_source": ERROR_UNFINISHED,
        }


# A bounded report is not permission to cancel an unresolved original native startup.
# Keep its owning loop/objects until interpreter exit rather than Runner's blanket task cancellation.
_RETAINED: list[tuple[asyncio.AbstractEventLoop, SupervisorRun]] = []


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


async def _provision(run: SupervisorRun, deadline: AdmittedDeadline, cap: int) -> None:
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

    run.provision = await run_privileged(run.owner, Action.PROVISION, deadline, cap, None, observed, run.startups)
    if run.provision.status is not Outcome.SUCCEEDED:
        raise ValueError(ERROR_PROVISION)


async def _application(
    run: SupervisorRun,
    selected: frozenset[str],
    validate_payload: Callable[[bytes, bytes, StaticPackage], JsonObject],
) -> None:
    original = AdmittedDeadline(run.owner.journal.deadline.end_ns, None, None)
    budget = object_value(parse_object(run.package.recipe_bytes)[Field.BUDGET_SECONDS])
    cap = positive_integer(budget, Field.NORMAL_COMMAND_MAX)
    boot_cap = positive_integer(budget, Field.GUEST_BOOT_OR_CONFIGURATION_MAX)
    await _provision(run, original, cap)
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
        result = await phases.perform(action, original, limit, None, selected=selected)
        if result.status is not Outcome.SUCCEEDED:
            raise RuntimeError(f"original enclosure action did not succeed: {action}")
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


async def _finish(run: SupervisorRun) -> JsonObject:
    budget = object_value(parse_object(run.package.recipe_bytes)[Field.BUDGET_SECONDS])
    export_ns = positive_integer(budget, Field.EXPORT_MAX) * NANOSECONDS
    original = AdmittedDeadline(run.owner.journal.deadline.end_ns, None, None)
    closure = AdmittedDeadline(original.outer_end_ns, None, original.outer_end_ns - export_ns)
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
    return run.record()


async def _drive(
    run: SupervisorRun,
    selected: frozenset[str],
    validate_payload: Callable[[bytes, bytes, StaticPackage], JsonObject],
) -> JsonObject:
    try:
        await _application(run, selected, validate_payload)
    except BaseException as error:
        run.primary_error = error
    return await _finish(run)


def run_supervisor(
    manifest: Path,
    source_root: Path,
    source_commit: str,
    source_tree: str,
    selected: frozenset[str],
    validate_payload: Callable[[bytes, bytes, StaticPackage], JsonObject],
) -> JsonObject:
    """Explicit application source entry only; ordinary roleless CI never reaches this path."""
    started_ns = time.monotonic_ns()
    if source_root.resolve(strict=True) != ACTUAL_SOURCE_ROOT or os.geteuid() != 0:
        raise ValueError(ERROR_INTAKE)
    package = StaticPackage.load(ACTUAL_SOURCE_ROOT / STATIC_DIRECTORY, ACTUAL_SOURCE_ROOT)
    budget = object_value(parse_object(package.recipe_bytes)[Field.BUDGET_SECONDS])
    deadline = Deadline(
        started_ns,
        started_ns + positive_integer(budget, Field.RUNTIME_OUTER_MAX) * NANOSECONDS,
        positive_integer(budget, Field.CLOSURE_EXPORT_RESERVE) * NANOSECONDS,
    )
    realization = _realization(manifest, AdmittedDeadline(deadline.end_ns, None, None))
    record = parse_object(realization)
    if record.get("candidate_commit") != source_commit or record.get("candidate_tree") != source_tree:
        raise ValueError(ERROR_INTAKE)
    owner = RunOwner.create(
        package,
        source_commit,
        source_tree,
        hashlib.sha256(realization).hexdigest(),
        deadline,
        Purpose.APPLICATION,
        realization_bytes=realization,
        selected=selected,
    )
    run = SupervisorRun(owner, package, realization)
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
