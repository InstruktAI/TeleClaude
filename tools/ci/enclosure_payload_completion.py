"""Capture existing report and normal-cleanup evidence after payload completion, without a live-PID requirement."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from tools.ci.enclosure_contract import (
    NANOSECONDS,
    AdmittedDeadline,
    Cutoff,
    JsonObject,
    StaticPackage,
    object_value,
    parse_object,
    positive_integer,
    text,
)
from tools.ci.enclosure_guest import POWER_COMMAND, GuestContext, Record
from tools.ci.enclosure_guest import Key as GuestKey
from tools.ci.enclosure_guest_evidence import EvidenceLeaf, GuestFileRead, read_guest_evidence

if TYPE_CHECKING:
    from tools.ci.enclosure_guest_binding import GuestBinding

ERROR_COMPLETION: Final = "the captured payload report or normal cleanup evidence is incomplete or inconsistent"


class CaptureState(StrEnum):
    """Capture validity is separate from functional verdict, physical witness and final acceptance."""

    CAPTURED = "captured"
    UNPROVEN = "unproven"


@dataclass(frozen=True)
class PayloadCompletion:
    """Keep raw bytes and actual read/validation errors independently of the known native start."""

    report: GuestFileRead | None
    shutdown: GuestFileRead | None
    failure: Exception | None

    def record(self) -> JsonObject:
        return {
            "capture_state": CaptureState.CAPTURED if self.failure is None else CaptureState.UNPROVEN,
            "report_sha256": self.report.sha256 if self.report is not None else None,
            "shutdown_journal_sha256": self.shutdown.sha256 if self.shutdown is not None else None,
            "error_class": type(self.failure).__name__ if self.failure is not None else None,
            "error_errno": self.failure.errno if isinstance(self.failure, OSError) else None,
        }


def _outside_uid(raw_map: str, inside_uid: int) -> int:
    # Use the already observed native ranges, never an assumed root shift plus UID.
    for line in raw_map.splitlines():
        inside, outside, count = (int(value) for value in line.split())
        if inside <= inside_uid < inside + count:
            return outside + inside_uid - inside
    raise ValueError(ERROR_COMPLETION)


def validate_shutdown_journal(read: GuestFileRead, manifest: bytes, package: StaticPackage) -> None:
    read.require_complete()
    if not read.data.endswith(b"\n"):
        raise ValueError(ERROR_COMPLETION)
    rows = [parse_object(line) for line in read.data.split(b"\n")[:-1]]
    if len(rows) != 3:
        raise ValueError(ERROR_COMPLETION)
    intent, started, outcome = rows
    admission = parse_object(manifest)
    for key in (
        GuestKey.SCHEMA_VERSION,
        GuestKey.RUN_TOKEN,
        GuestKey.SOURCE_COMMIT,
        GuestKey.SOURCE_TREE,
        GuestKey.REALIZATION_SHA256,
        GuestKey.STATIC_LOCK_SHA256,
        GuestKey.RECIPE_SHA256,
        GuestKey.QUALIFICATION_SHA256,
        GuestKey.ADMISSION_SEAL_SHA256,
        GuestKey.PURPOSE,
        GuestKey.QUALIFICATION_VECTOR,
        Cutoff.OUTER_END_NS,
        Cutoff.VECTOR_END_NS,
        Cutoff.COMMAND_END_NS,
    ):
        if key not in intent or intent[key] != admission[key]:
            raise ValueError(ERROR_COMPLETION)
    if (
        intent.get(GuestKey.RECORD) != Record.INTENT
        or intent.get(GuestKey.COMMAND) != list(POWER_COMMAND)
        or intent.get(GuestKey.MANIFEST_SHA256) != hashlib.sha256(manifest).hexdigest()
        or started.get(GuestKey.RECORD) != Record.STARTED
        or outcome.get(GuestKey.RECORD) != Record.ACKNOWLEDGED
        or type(outcome.get(GuestKey.EXIT_STATUS)) is not int
        or outcome[GuestKey.EXIT_STATUS] != 0
    ):
        raise ValueError(ERROR_COMPLETION)
    positive_integer(started, GuestKey.PID)
    original = AdmittedDeadline.from_record(admission, require_vector=False)
    first = positive_integer(intent, GuestKey.MONOTONIC_NS)
    end = positive_integer(intent, GuestKey.EFFECTIVE_COMMAND_END_NS)
    if (
        not first
        < end
        <= min(original.effective_end(), first + GuestContext(manifest, package).unit_max_seconds() * NANOSECONDS)
    ):
        raise ValueError(ERROR_COMPLETION)
    previous = first
    for row in rows:
        current = positive_integer(row, GuestKey.MONOTONIC_NS)
        if not previous <= current < end or current > read.finished_ns:
            raise ValueError(ERROR_COMPLETION)
        previous = current


def capture_payload_completion(
    binding: GuestBinding, manifest: bytes, package: StaticPackage, deadline: AdmittedDeadline
) -> PayloadCompletion:
    """Read only existing named artifacts; do not grade functional results or infer completion from absence."""
    report = None
    shutdown = None
    try:
        binding.require_root_view(deadline)
        admission = parse_object(manifest)
        # Account UID is fixed by the reviewed recipe, not by report contents.
        recipe = parse_object(package.recipe_bytes)
        uid = positive_integer(object_value(object_value(recipe["guest"])["account"]), "uid")
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        return PayloadCompletion(report, shutdown, error)
    failures: list[Exception] = []
    try:
        report = read_guest_evidence(
            binding.root_fd,
            binding.facts.root_uid,
            _outside_uid(binding.facts.uid_map, uid),
            EvidenceLeaf.REPORT,
            deadline,
        )
        report.require_complete()
        value = parse_object(report.data)
        if (
            text(value, "source_revision") != text(admission, GuestKey.SOURCE_COMMIT)
            or text(value, "source_tree") != text(admission, GuestKey.SOURCE_TREE)
            or value.get("profile") != "full"
            or value.get("selection") != admission[GuestKey.SELECTED_SCENARIOS]
        ):
            raise ValueError(ERROR_COMPLETION)
        # Functional verdicts and every retention key remain in these original bytes for final validation.
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        failures.append(error)
    try:
        shutdown = read_guest_evidence(
            binding.root_fd,
            binding.facts.root_uid,
            binding.facts.root_uid,
            EvidenceLeaf.POWEROFF,
            deadline,
        )
        validate_shutdown_journal(shutdown, manifest, package)
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        failures.append(error)
    try:
        binding.require_root_view(deadline)
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        failures.append(error)
    failure = (
        None if not failures else failures[0] if len(failures) == 1 else ExceptionGroup(ERROR_COMPLETION, failures)
    )
    return PayloadCompletion(report, shutdown, failure)
