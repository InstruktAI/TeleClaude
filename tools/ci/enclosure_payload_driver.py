"""One application payload's original work wait, bounded closure and original-helper collection."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from tools.ci.enclosure_contract import (
    NANOSECONDS,
    Action,
    AdmittedDeadline,
    Field,
    JsonObject,
    object_value,
    parse_object,
    positive_integer,
    text,
)
from tools.ci.enclosure_exchange import HelperCollection, collect_helper_startup
from tools.ci.enclosure_guest import Purpose
from tools.ci.enclosure_journal import ActionResult, Outcome
from tools.ci.enclosure_owner import Key as OwnerKey

if TYPE_CHECKING:
    from tools.ci.enclosure_phases import BindingPhases

ERROR_DRIVER: Final = "the original configured application payload cannot enter this work/closure progression"
ERROR_PAYLOAD: Final = "the single payload start did not establish its admitted phase"
ERROR_SHUTDOWN: Final = "automatic cleanup supplied no acknowledged receipt for bounded consumption"


@dataclass(frozen=True)
class PayloadDrive:
    """Control observations and errors, without a functional, P4, release or export verdict."""

    work_end_ns: int
    closure_end_ns: int
    payload_receipt: ActionResult | None
    shutdown_receipt: ActionResult | None
    work_observation: JsonObject | None
    closure_observation: JsonObject | None
    primary_error: BaseException | None
    closure_errors: tuple[BaseException, ...]
    helpers: tuple[HelperCollection, ...]

    def record(self) -> JsonObject:
        return {
            "work_end_ns": self.work_end_ns,
            "closure_end_ns": self.closure_end_ns,
            "payload_receipt": self.payload_receipt.record(Action.START_PAYLOAD)
            if self.payload_receipt is not None
            else None,
            "shutdown_receipt": self.shutdown_receipt.record(Action.POWEROFF)
            if self.shutdown_receipt is not None
            else None,
            "work_observation": self.work_observation,
            "closure_observation": self.closure_observation,
            "primary_error_class": type(self.primary_error).__name__ if self.primary_error is not None else None,
            "closure_error_classes": [type(error).__name__ for error in self.closure_errors],
            "helpers": [helper.record() for helper in self.helpers],
        }


async def drive_payload(phases: BindingPhases, original: AdmittedDeadline) -> PayloadDrive:
    """Use one original run clock and event loop; timeout never becomes permission for another start."""
    owner = phases.owner
    if (
        phases.configured is None
        or phases.active_guest_manifest is None
        or original.outer_end_ns != owner.journal.deadline.end_ns
        or Purpose(text(parse_object(owner.manifest_bytes), OwnerKey.PURPOSE)) is not Purpose.APPLICATION
    ):
        raise ValueError(ERROR_DRIVER)
    selected = parse_object(phases.active_guest_manifest).get("selected_scenarios")
    if not isinstance(selected, list) or any(not isinstance(name, str) or not name for name in selected):
        raise ValueError(ERROR_DRIVER)
    selection = frozenset(name for name in selected if isinstance(name, str))
    if len(selection) != len(selected):
        raise ValueError(ERROR_DRIVER)
    budget = object_value(parse_object(phases.package.recipe_bytes)[Field.BUDGET_SECONDS])
    normal_cap = positive_integer(budget, Field.NORMAL_COMMAND_MAX)
    shutdown_cap = positive_integer(budget, Field.SHUTDOWN_MAX)
    export_cap = positive_integer(budget, Field.EXPORT_MAX)
    work_end = min(original.effective_end(), original.outer_end_ns - owner.journal.deadline.reserve_ns)
    payload = None
    shutdown = None
    work_observation = None
    closure_observation = None
    primary = None
    closure_errors: list[BaseException] = []
    helpers: list[HelperCollection] = []
    try:
        payload = await phases.perform(Action.START_PAYLOAD, original, normal_cap, None, selected=selection)
        if payload.status is not Outcome.SUCCEEDED or phases.payload_started is None:
            raise RuntimeError(ERROR_PAYLOAD)
        work_observation = await phases.wait_for_payload_exit(
            AdmittedDeadline(original.outer_end_ns, original.vector_end_ns, work_end)
        )
    except BaseException as error:
        primary = error
        payload = phases.results.get(Action.START_PAYLOAD, payload)
    # Cap closure once. Preserve export time only against original outer time,
    # never subtract it from an independent vector or command cutoff.
    closure_end = min(
        original.effective_end(),
        original.outer_end_ns - export_cap * NANOSECONDS,
        time.monotonic_ns() + shutdown_cap * NANOSECONDS,
    )
    closure = AdmittedDeadline(original.outer_end_ns, original.vector_end_ns, closure_end)
    try:
        if phases.payload_started is not None:
            if work_observation is None:
                closure_observation = await phases.wait_for_payload_exit(closure)
            else:
                closure_observation = work_observation
            if phases.automatic_cleanup_read is None:
                raise RuntimeError(ERROR_SHUTDOWN)
            shutdown = await phases.perform(Action.POWEROFF, closure, shutdown_cap, None)
            if shutdown.status is not Outcome.SUCCEEDED:
                raise RuntimeError(ERROR_SHUTDOWN)
    except BaseException as error:
        closure_errors.append(error)
        shutdown = phases.results.get(Action.POWEROFF, shutdown)
    for startup in phases.startups:
        retained = phases.results.get(startup.action)
        process = startup.process
        if (
            retained is not None
            and process is not None
            and process.returncode is not None
            and startup.task.done()
            and not startup.task.cancelled()
            and startup.task.exception() is None
        ):
            startup.output_eof = process.stdout is not None and process.stdout.at_eof()
            helpers.append(HelperCollection(startup, retained, ()))
        else:
            helpers.append(await collect_helper_startup(startup, owner, closure))
    return PayloadDrive(
        work_end,
        closure_end,
        payload,
        shutdown,
        work_observation,
        closure_observation,
        primary,
        tuple(closure_errors),
        tuple(helpers),
    )
