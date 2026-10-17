"""Immutable inner evidence for the outside owner, without resolving a physical or functional outcome."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from pathlib import Path

from tools.ci.enclosure_contract import JsonObject, JsonValue
from tools.ci.workflow_ledger import RECORD_OPEN, RECORD_TRIGGER, RECORD_UNKNOWN, StartLedger


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
