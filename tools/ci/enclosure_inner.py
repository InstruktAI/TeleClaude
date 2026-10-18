"""Immutable inner evidence for the outside owner, without resolving a physical or functional outcome."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Final

from tools.ci.enclosure_contract import Cutoff, JsonObject, JsonValue, parse_object
from tools.ci.enclosure_guest import GuestContext
from tools.ci.enclosure_guest import Key as GuestKey
from tools.ci.workflow_ledger import RECORD_OPEN, RECORD_TRIGGER, RECORD_UNKNOWN, StartLedger

PROVISIONAL_REPORT_SCHEMA: Final = 4
PROVISIONAL_STAGE: Final = "payload_provisional"
JSON_SEPARATORS: Final = (",", ":")


class PendingReason(StrEnum):
    """Only this newly emitted typed reason is eligible for ensuing outside physical resolution."""

    P4_PENDING_OUTER = "P4_PENDING_OUTER"


class RetentionEmitter(StrEnum):
    """The two actual source owners of deferred physical and evidence-delivery holds."""

    SHARED_FLOW = "shared-workflow-flow"
    EVENT_EVIDENCE = "workflow-event-evidence"


class RetentionField(StrEnum):
    """Typed holds never classify a free-text failure or an existing failed marker."""

    DEFERRED = "deferred_retention"
    EMITTER = "emitter"
    OWNER = "owner"
    BINDING = "binding"
    CONDITION = "condition"
    FAILURE = "failure"
    ISSUES = "issues"
    FINALIZER = "finalizer"
    OWNED_PROFILE_ROOT = "owned_profile_root"


class RetentionCondition(StrEnum):
    """Evidence delivery and physical closure keep their independent obligations."""

    PHYSICAL = "original-physical-closure-pending"
    EVIDENCE = "original-evidence-readback-pending"


class PhysicalCleanupPending(RuntimeError):
    """A live new-run cleanup defers physical closure; it never represents a previously failed result."""


@dataclass(frozen=True)
class InnerCleanupEvidence:
    """Actual public-before-stop ordering and supported stop outcome; P1/P2 and functional coverage stay separate."""

    public_finished_ns: int
    stop_started_ns: int | None
    stop_finished_ns: int | None
    stop_outcome: str | None
    stop_exit_status: int | None
    stop_diagnostics: str
    stop_error: str | None
    work_end_ns: int | None
    failures: tuple[str, ...]
    unclassified_retention: tuple[str, ...]

    @property
    def pending_physical(self) -> bool:
        return (
            self.stop_started_ns is not None
            and self.stop_finished_ns is not None
            and self.work_end_ns is not None
            and 0 < self.public_finished_ns <= self.stop_started_ns <= self.stop_finished_ns <= self.work_end_ns
            and self.stop_outcome == "stopped"
            and type(self.stop_exit_status) is int
            and self.stop_exit_status == 0
            and not self.stop_diagnostics
            and self.stop_error is None
            and not self.failures
            and not self.unclassified_retention
        )

    def record(self) -> JsonObject:
        return {
            "classification": PendingReason.P4_PENDING_OUTER.value if self.pending_physical else "retained-unproven",
            "public_cleanup_finished_ns": self.public_finished_ns,
            "stop_started_ns": self.stop_started_ns,
            "stop_finished_ns": self.stop_finished_ns,
            "supported_stop_outcome": self.stop_outcome,
            "stop_exit_status": self.stop_exit_status,
            "stop_diagnostics": self.stop_diagnostics,
            "stop_error": self.stop_error,
            "work_end_ns": self.work_end_ns,
            "independent_failures": list[JsonValue](self.failures),
            "unclassified_retention": list[JsonValue](self.unclassified_retention),
        }


def _encoded(record: JsonObject) -> bytes:
    return json.dumps(record, sort_keys=True, separators=JSON_SEPARATORS, allow_nan=False).encode("utf-8")


@dataclass(frozen=True)
class PayloadProvisional:
    """One newly admitted run's immutable binding; its pending physical fact grants no cleanup/functional pass."""

    binding_bytes: bytes
    observations_bytes: bytes = b"{}"

    @classmethod
    def from_admitted(cls, context: GuestContext) -> PayloadProvisional:
        """Capture the request just verified by run_profile, before any product action or old report is read."""
        record = context.record
        binding = {
            str(key): record[key]
            for key in (
                GuestKey.RUN_TOKEN,
                GuestKey.SOURCE_COMMIT,
                GuestKey.SOURCE_TREE,
                GuestKey.STATIC_LOCK_SHA256,
                GuestKey.RECIPE_SHA256,
                GuestKey.QUALIFICATION_SHA256,
                GuestKey.REALIZATION_SHA256,
                GuestKey.ADMISSION_SEAL_SHA256,
                GuestKey.PURPOSE,
                GuestKey.GUEST_BOOT_ID,
                GuestKey.PID_NAMESPACE,
                GuestKey.CGROUP_NAMESPACE,
                GuestKey.SELECTED_SCENARIOS,
                GuestKey.PAYLOAD_END_NS,
            )
        }
        original = context.admitted_deadline()
        binding.update(
            {
                "guest_manifest_sha256": hashlib.sha256(context.manifest_bytes).hexdigest(),
                Cutoff.OUTER_END_NS: original.outer_end_ns,
                Cutoff.VECTOR_END_NS: original.vector_end_ns,
                Cutoff.COMMAND_END_NS: original.command_end_ns,
                "created_ns": time.monotonic_ns(),
            }
        )
        return cls(_encoded(binding))

    def observe(self, facts: JsonObject) -> PayloadProvisional:
        """Freeze current structured facts without clearing a pending reason or changing any original verdict."""
        return replace(self, observations_bytes=_encoded(facts))

    def record(self) -> JsonObject:
        return {
            "schema_version": 1,
            "stage": PROVISIONAL_STAGE,
            "pending_reasons": [PendingReason.P4_PENDING_OUTER.value],
            "binding": parse_object(self.binding_bytes),
            "observations": parse_object(self.observations_bytes),
        }


@dataclass(frozen=True)
class DeferredRetention:
    """A newly admitted owning emitter's hold; this supplies no discharge or acceptance."""

    emitter: RetentionEmitter
    owner: Path
    binding_bytes: bytes

    def record(self) -> JsonObject:
        return {
            RetentionField.EMITTER: self.emitter.value,
            RetentionField.OWNER: str(self.owner),
            RetentionField.BINDING: parse_object(self.binding_bytes),
            RetentionField.CONDITION: (
                RetentionCondition.PHYSICAL.value
                if self.emitter is RetentionEmitter.SHARED_FLOW
                else RetentionCondition.EVIDENCE.value
            ),
        }


@dataclass(frozen=True)
class LedgerEvidence:
    """Keep exact bytes and parse failure independently of the derived explicit-start classification."""

    data: bytes
    expected_cases: tuple[str, ...]
    ledger: StartLedger | None
    error: str | None
    flow_id: str | None
    missing_cases: tuple[str, ...]
    extra_cases: tuple[str, ...]
    pending_triggers: tuple[str, ...]
    blocking_attempts: tuple[str, ...]

    @classmethod
    def capture(cls, data: bytes, *, path: Path, expected_cases: tuple[str, ...]) -> LedgerEvidence:
        """Use the existing complete ledger validator; path is an address only and is never opened here."""
        try:
            ledger = StartLedger.from_bytes(data, path=path)
        except (ValueError, RecursionError) as error:
            return cls(data, expected_cases, None, str(error), None, expected_cases, (), (), ())
        cases = frozenset(ledger.closed_lists)
        attempts = tuple(ledger.attempts.values())
        pending = tuple(
            attempt.identifier
            for attempt in attempts
            if attempt.kind == RECORD_TRIGGER and attempt.state == RECORD_OPEN
        )
        blocking = tuple(
            attempt.identifier
            for attempt in attempts
            if attempt.kind == RECORD_UNKNOWN or (attempt.state == RECORD_OPEN and attempt.kind != RECORD_TRIGGER)
        )
        # The flow may keep using the parsed ledger for public settlement.
        # Snapshot facts are frozen now and cannot follow those later mutations.
        return cls(
            data,
            expected_cases,
            ledger,
            None,
            ledger.flow_id,
            tuple(sorted(set(expected_cases) - cases)),
            tuple(sorted(cases - set(expected_cases))),
            pending,
            blocking,
        )

    def record(self) -> JsonObject:
        """Pending triggers keep their open semantic state; no absence/count supplies consumption or P4."""
        return {
            "raw_encoding": "base64",
            "raw_data": base64.b64encode(self.data).decode("ascii"),
            "raw_sha256": hashlib.sha256(self.data).hexdigest(),
            "raw_byte_count": len(self.data),
            "parse_error": self.error,
            "flow_id": self.flow_id,
            "expected_cases": list[JsonValue](self.expected_cases),
            "missing_case_lists": list[JsonValue](self.missing_cases),
            "extra_case_lists": list[JsonValue](self.extra_cases),
            "pending_trigger_ids": list[JsonValue](self.pending_triggers),
            "blocking_attempt_ids": list[JsonValue](self.blocking_attempts),
            "recorded_explicit_attempts_settled": self.error is None
            and not self.missing_cases
            and not self.extra_cases
            and not self.blocking_attempts,
        }
