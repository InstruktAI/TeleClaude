"""Outside checks of new provisional identities and original ledger bytes, without final acceptance."""

from __future__ import annotations

import base64
import binascii
import hashlib
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from tools.ci import workflow_foundation as foundation
from tools.ci.enclosure_contract import (
    NANOSECONDS,
    QUALIFICATION_DIGEST,
    RECIPE_DIGEST,
    STATIC_DIGEST,
    AdmittedDeadline,
    Cutoff,
    Field,
    JsonObject,
    JsonValue,
    StaticPackage,
    object_value,
    parse_object,
    positive_integer,
    text,
)
from tools.ci.enclosure_guest import Key as GuestKey
from tools.ci.enclosure_guest import Purpose
from tools.ci.enclosure_inner import PROVISIONAL_REPORT_SCHEMA, PROVISIONAL_STAGE, LedgerEvidence, PendingReason
from tools.ci.workflow_flow import B5_ACTIONS, B6_ACTIONS, B7_ACTIONS, declared_chain
from tools.ci.workflow_ledger import RECORD_OPERATION, RECORD_SESSION, RECORD_TRIGGER
from tools.ci.workflow_publication import TERMINAL_STATES

ERROR_REPORT: Final = "the new provisional report binding or original ledger evidence is inconsistent"
LEDGER_ADDRESS: Final = Path("starts.jsonl")
BINDING_FIELDS: Final = (
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
OBSERVATION_FIELDS: Final = frozenset(
    {
        "owned_profile_root",
        "daemon_stop_outcome",
        "inner_cleanup",
        "recorded_retention_reasons",
        "recorded_retention_keys",
        "flow_finalizer",
        "flow_finalizer_errors",
    }
)
CLOSED_ACTIONS: Final = {"B5": B5_ACTIONS, "B7": B7_ACTIONS, "B6": B6_ACTIONS}


def _strings(value: JsonValue) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(ERROR_REPORT)
    return tuple(item for item in value if isinstance(item, str))


def _ledger(value: JsonValue, cases: tuple[str, ...]) -> LedgerEvidence | None:
    if value is None:
        return None
    record = object_value(value)
    if (
        record.get("raw_encoding") != "base64"
        or type(record.get("raw_byte_count")) is not int
        or type(record.get("recorded_explicit_attempts_settled")) is not bool
    ):
        raise ValueError(ERROR_REPORT)
    try:
        data = base64.b64decode(text(record, "raw_data"), validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError(ERROR_REPORT) from error
    # This is a nominal address for the existing parser; no report path is opened.
    snapshot = LedgerEvidence.capture(data, path=LEDGER_ADDRESS, expected_cases=cases)
    if snapshot.record() != record:
        raise ValueError(ERROR_REPORT)
    return snapshot


def _ledger_pair(observations: JsonObject, selection: frozenset[str]) -> JsonObject:
    cases = declared_chain(selection)
    flow = observations["flow_finalizer"]
    before = None
    after = None
    if flow is not None:
        finalizer = object_value(flow)
        before = _ledger(finalizer.get("start_ledger_before_closure"), cases)
        after = _ledger(finalizer.get("start_ledger_after_closure"), cases)
    continuous = None
    if before is not None and after is not None:
        continuous = after.data.startswith(before.data)
        if not continuous or (
            before.flow_id is not None and after.flow_id is not None and before.flow_id != after.flow_id
        ):
            raise ValueError(ERROR_REPORT)
    return {
        "expected_cases": list[JsonValue](cases),
        "before_sha256": hashlib.sha256(before.data).hexdigest() if before is not None else None,
        "after_sha256": hashlib.sha256(after.data).hexdigest() if after is not None else None,
        "append_continuous": continuous,
        "before_parse_error": before.error if before is not None else None,
        "after_parse_error": after.error if after is not None else None,
        "before_blocking_attempt_ids": list[JsonValue](before.blocking_attempts) if before is not None else None,
        "after_blocking_attempt_ids": list[JsonValue](after.blocking_attempts) if after is not None else None,
        "pending_trigger_ids": list[JsonValue](after.pending_triggers) if after is not None else None,
    }


def validate_provisional_bindings(report: JsonObject, manifest: bytes, package: StaticPackage) -> JsonObject:
    """Match actual protected input and reparse captured bytes; pending/settled labels grant no P2 or application pass."""
    admission = parse_object(manifest)
    if (
        type(report.get("schema_version")) is not int
        or report["schema_version"] != PROVISIONAL_REPORT_SCHEMA
        or report.get("stage") != PROVISIONAL_STAGE
        or report.get("profile") != "full"
        or report.get("source_revision") != admission[GuestKey.SOURCE_COMMIT]
        or report.get("source_tree") != admission[GuestKey.SOURCE_TREE]
        or report.get("selection") != admission[GuestKey.SELECTED_SCENARIOS]
    ):
        raise ValueError(ERROR_REPORT)
    selected = _strings(admission[GuestKey.SELECTED_SCENARIOS])
    if len(selected) != len(set(selected)):
        raise ValueError(ERROR_REPORT)
    provisional = object_value(report["payload_provisional"])
    if (
        set(provisional) != {"schema_version", "stage", "pending_reasons", "binding", "observations"}
        or type(provisional.get("schema_version")) is not int
        or provisional["schema_version"] != 1
        or provisional["stage"] != PROVISIONAL_STAGE
        or provisional["pending_reasons"] != [PendingReason.P4_PENDING_OUTER.value]
    ):
        raise ValueError(ERROR_REPORT)
    binding = object_value(provisional["binding"])
    if set(binding) != {*BINDING_FIELDS, *Cutoff, "guest_manifest_sha256", "created_ns"} or any(
        binding[key] != admission[key] for key in BINDING_FIELDS
    ):
        raise ValueError(ERROR_REPORT)
    if text(binding, "guest_manifest_sha256") != hashlib.sha256(manifest).hexdigest():
        raise ValueError(ERROR_REPORT)
    for key, expected in (
        (GuestKey.STATIC_LOCK_SHA256, STATIC_DIGEST),
        (GuestKey.RECIPE_SHA256, RECIPE_DIGEST),
        (GuestKey.QUALIFICATION_SHA256, QUALIFICATION_DIGEST),
    ):
        if text(binding, key) != expected:
            raise ValueError(ERROR_REPORT)
    # Purpose is preserved as data. A matching qualification identity is never an application verdict.
    purpose = Purpose(text(binding, GuestKey.PURPOSE))
    original = AdmittedDeadline.from_record(admission, require_vector=purpose is Purpose.QUALIFICATION)
    if AdmittedDeadline.from_record(binding, require_vector=purpose is Purpose.QUALIFICATION) != original:
        raise ValueError(ERROR_REPORT)
    reserve = (
        positive_integer(
            object_value(parse_object(package.recipe_bytes)[Field.BUDGET_SECONDS]), Field.CLOSURE_EXPORT_RESERVE
        )
        * NANOSECONDS
    )
    end = positive_integer(binding, GuestKey.PAYLOAD_END_NS)
    if (
        end > min(original.effective_end(), original.outer_end_ns - reserve)
        or positive_integer(binding, "created_ns") > end
    ):
        raise ValueError(ERROR_REPORT)
    observations = object_value(provisional["observations"])
    if frozenset(observations) != OBSERVATION_FIELDS:
        raise ValueError(ERROR_REPORT)
    text(observations, "owned_profile_root")
    _strings(observations["recorded_retention_reasons"])
    _strings(observations["flow_finalizer_errors"])
    reasons = object_value(observations["recorded_retention_keys"])
    if any(not isinstance(reason, str) for reason in reasons.values()):
        raise ValueError(ERROR_REPORT)
    return {
        "stage": PROVISIONAL_STAGE,
        "guest_manifest_sha256": hashlib.sha256(manifest).hexdigest(),
        "purpose": binding[GuestKey.PURPOSE],
        "ledger_bytes": _ledger_pair(observations, frozenset(selected)),
    }


def validate_provisional_cleanup(report: JsonObject) -> JsonObject:
    """Recheck actual public-before-P3 facts; the producer's pending label cannot absorb another failure."""
    provisional = object_value(report["payload_provisional"])
    binding = object_value(provisional["binding"])
    observations = object_value(provisional["observations"])
    cleanup = object_value(report["cleanup"])
    inner = object_value(observations["inner_cleanup"])
    if (
        set(inner)
        != {
            "classification",
            "public_cleanup_finished_ns",
            "stop_started_ns",
            "stop_finished_ns",
            "supported_stop_outcome",
            "stop_exit_status",
            "stop_diagnostics",
            "stop_error",
            "work_end_ns",
            "independent_failures",
            "unclassified_retention",
        }
        or set(cleanup) != {"status", "detail", "commands"}
        or cleanup["status"] != PendingReason.P4_PENDING_OUTER.value
        or cleanup["detail"] != ""
        or inner["classification"] != PendingReason.P4_PENDING_OUTER.value
        or inner["supported_stop_outcome"] != "stopped"
        or observations["daemon_stop_outcome"] != "stopped"
        or type(inner["stop_exit_status"]) is not int
        or inner["stop_exit_status"] != 0
        or inner["stop_diagnostics"] != ""
        or inner["stop_error"] is not None
        or inner["independent_failures"] != []
        or inner["unclassified_retention"] != []
        or observations["recorded_retention_reasons"] != []
        or observations["recorded_retention_keys"] != {}
        or observations["flow_finalizer_errors"] != []
    ):
        raise ValueError(ERROR_REPORT)
    created = positive_integer(binding, "created_ns")
    public = positive_integer(inner, "public_cleanup_finished_ns")
    started = positive_integer(inner, "stop_started_ns")
    finished = positive_integer(inner, "stop_finished_ns")
    end = positive_integer(inner, "work_end_ns")
    if not created <= public <= started <= finished <= end or end != positive_integer(binding, GuestKey.PAYLOAD_END_NS):
        raise ValueError(ERROR_REPORT)
    return {
        "public_cleanup_finished_ns": public,
        "stop_started_ns": started,
        "stop_finished_ns": finished,
        "work_end_ns": end,
        "supported_stop_outcome": "stopped",
        "physical_condition": PendingReason.P4_PENDING_OUTER.value,
    }


def _public_session_command(value: JsonValue, argv: list[str]) -> Mapping[str, object]:
    command = object_value(value)
    duration = command.get("duration_seconds")
    if (
        set(command) != {"argv", "exit_status", "duration_seconds", "stdout", "stderr", "diagnostics"}
        or command["argv"] != argv
        or type(command["exit_status"]) is not int
        or command["exit_status"] != 0
        or command["diagnostics"] != ""
        or not isinstance(command["stdout"], str)
        or not isinstance(command["stderr"], str)
        or type(duration) not in (int, float)
        or not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or duration < 0
    ):
        raise ValueError(ERROR_REPORT)
    # Reuse the actual public CLI framing parser, without reading any report-supplied address.
    record = foundation.json_object(command["stdout"])
    if record is None:
        raise ValueError(ERROR_REPORT)
    return record


def _public_closed(record: Mapping[str, object], session_id: str) -> bool:
    closed_at = record.get("closed_at")
    return (
        record.get("session_id") == session_id
        and isinstance(closed_at, str)
        and bool(closed_at)
        and record.get("lifecycle_status") == "closed"
    )


def _session_end_proof(proof: JsonObject, created: int, public_finished: int) -> tuple[str, str]:
    if set(proof) != {"session_id", "started_ns", "finished_ns", "reads", "end_command", "operation", "error"}:
        raise ValueError(ERROR_REPORT)
    session_id = text(proof, "session_id")
    if (
        proof["error"] is not None
        or not created
        <= positive_integer(proof, "started_ns")
        <= positive_integer(proof, "finished_ns")
        <= public_finished
    ):
        raise ValueError(ERROR_REPORT)
    reads = proof["reads"]
    if not isinstance(reads, list) or not reads:
        raise ValueError(ERROR_REPORT)
    records = [_public_session_command(value, ["telec", "sessions", "show", session_id, "--full"]) for value in reads]
    if any(record.get("session_id") != session_id for record in records) or not _public_closed(records[-1], session_id):
        raise ValueError(ERROR_REPORT)
    role = records[-1].get("role")
    if not isinstance(role, str) or not role or role == "unknown":
        raise ValueError(ERROR_REPORT)
    end = proof["end_command"]
    operation = proof["operation"]
    if end is None:
        # Already-closed public state is preserved as such; no end operation is invented.
        if operation is not None or not _public_closed(records[0], session_id):
            raise ValueError(ERROR_REPORT)
    else:
        receipt = _public_session_command(end, ["telec", "sessions", "end", session_id])
        terminal = object_value(operation)
        operation_id = receipt.get("operation_id")
        if (
            not isinstance(operation_id, str)
            or not operation_id
            or terminal.get("operation_id") != operation_id
            or terminal.get("state") != "completed"
            or terminal.get("error") not in (None, "")
        ):
            raise ValueError(ERROR_REPORT)
    return session_id, role


def validate_flow_session_closure(report: JsonObject) -> JsonObject:
    """Validate the shared flow's actual public end/closed evidence, independently of its P1 label or P4."""
    provisional = object_value(report["payload_provisional"])
    binding = object_value(provisional["binding"])
    observations = object_value(provisional["observations"])
    selection = frozenset(_strings(binding[GuestKey.SELECTED_SCENARIOS]))
    cases = declared_chain(selection)
    flow = observations["flow_finalizer"]
    if not cases:
        if flow is not None:
            raise ValueError(ERROR_REPORT)
        return {"scope": "shared-workflow-flow", "state": "not_selected"}
    finalizer = object_value(flow)
    if (
        not {
            "failure",
            "issues",
            "sessions",
            "owned_session_ids",
            "public_session_end_evidence",
            "start_ledger_before_closure",
            "start_ledger_after_closure",
        }
        <= set(finalizer)
        or finalizer["failure"] is not None
        or finalizer["issues"] != []
    ):
        raise ValueError(ERROR_REPORT)
    owned = _strings(finalizer["owned_session_ids"])
    if not owned or owned != tuple(sorted(set(owned))) or any(not session for session in owned):
        raise ValueError(ERROR_REPORT)
    rows = object_value(finalizer["sessions"])
    if set(rows) != set(owned):
        raise ValueError(ERROR_REPORT)
    proofs = finalizer["public_session_end_evidence"]
    if not isinstance(proofs, list):
        raise ValueError(ERROR_REPORT)
    public_finished = positive_integer(object_value(observations["inner_cleanup"]), "public_cleanup_finished_ns")
    created = positive_integer(binding, "created_ns")
    observed: dict[str, str] = {}
    for value in proofs:
        session_id, role = _session_end_proof(object_value(value), created, public_finished)
        if session_id not in owned or (session_id in observed and observed[session_id] != role):
            raise ValueError(ERROR_REPORT)
        observed[session_id] = role
    if set(observed) != set(owned):
        raise ValueError(ERROR_REPORT)
    # Join actual explicit session answers, not an acknowledged-process count, to the public closed records.
    for key in ("start_ledger_before_closure", "start_ledger_after_closure"):
        snapshot = _ledger(finalizer.get(key), cases)
        if snapshot is None or snapshot.ledger is None or snapshot.error is not None:
            raise ValueError(ERROR_REPORT)
        for attempt in snapshot.ledger.attempts.values():
            if attempt.kind == RECORD_SESSION and (attempt.session_id is None or attempt.session_id not in observed):
                raise ValueError(ERROR_REPORT)
    for session_id, role in observed.items():
        row = object_value(rows[session_id])
        if set(row) != {"role", "closed"} or row["role"] != role or row["closed"] is not True:
            raise ValueError(ERROR_REPORT)
    return {
        "scope": "shared-workflow-flow",
        "state": "public_closed",
        "session_ids": list(owned),
        "end_evidence_count": len(proofs),
    }


def _operation_results(finalizer: JsonObject, created: int, public_finished: int) -> dict[str, list[JsonValue]]:
    evidence = finalizer["public_operation_evidence"]
    if not isinstance(evidence, list):
        raise ValueError(ERROR_REPORT)
    results: dict[str, list[JsonValue]] = {}
    for value in evidence:
        row = object_value(value)
        if (
            set(row) != {"operation_id", "started_ns", "finished_ns", "terminal", "error"}
            or row["error"] is not None
            or not created
            <= positive_integer(row, "started_ns")
            <= positive_integer(row, "finished_ns")
            <= public_finished
        ):
            raise ValueError(ERROR_REPORT)
        operation_id = text(row, "operation_id")
        terminal = object_value(row["terminal"])
        state = terminal.get("state")
        if terminal.get("operation_id") != operation_id or not isinstance(state, str) or state not in TERMINAL_STATES:
            raise ValueError(ERROR_REPORT)
        results.setdefault(operation_id, []).append(terminal)
    return results


def _declared_snapshot(value: JsonValue, cases: tuple[str, ...]) -> LedgerEvidence:
    snapshot = _ledger(value, cases)
    if (
        snapshot is None
        or snapshot.ledger is None
        or snapshot.error is not None
        or snapshot.missing_cases
        or snapshot.extra_cases
        or tuple(snapshot.ledger.closed_lists) != cases
    ):
        raise ValueError(ERROR_REPORT)
    for case in cases:
        expected = {row["label"]: (row["kind"], row.get("parent")) for row in CLOSED_ACTIONS[case]}
        if snapshot.ledger.closed_lists[case] != expected:
            raise ValueError(ERROR_REPORT)
    return snapshot


def validate_flow_start_inputs(report: JsonObject) -> JsonObject:
    """Join declared attempts to actual terminal operation data; receipts alone do not establish semantic settlement."""
    provisional = object_value(report["payload_provisional"])
    binding = object_value(provisional["binding"])
    observations = object_value(provisional["observations"])
    cases = declared_chain(frozenset(_strings(binding[GuestKey.SELECTED_SCENARIOS])))
    if not cases:
        if observations["flow_finalizer"] is not None:
            raise ValueError(ERROR_REPORT)
        return {"scope": "shared-workflow-flow", "state": "not_selected"}
    finalizer = object_value(observations["flow_finalizer"])
    before = _declared_snapshot(finalizer["start_ledger_before_closure"], cases)
    after = _declared_snapshot(finalizer["start_ledger_after_closure"], cases)
    if not after.data.startswith(before.data) or after.flow_id != before.flow_id or after.blocking_attempts:
        raise ValueError(ERROR_REPORT)
    created = positive_integer(binding, "created_ns")
    public_finished = positive_integer(object_value(observations["inner_cleanup"]), "public_cleanup_finished_ns")
    operations = _operation_results(finalizer, created, public_finished)
    if after.ledger is None:
        raise ValueError(ERROR_REPORT)
    matched: list[JsonValue] = []
    effects: list[JsonValue] = []
    for attempt in after.ledger.attempts.values():
        if attempt.kind in (RECORD_OPERATION, RECORD_TRIGGER):
            if attempt.operation_id is None or attempt.operation_id not in operations:
                raise ValueError(ERROR_REPORT)
            matched.append(
                {
                    "attempt_id": attempt.identifier,
                    "kind": attempt.kind,
                    "recorded_state": attempt.state,
                    "operation_id": attempt.operation_id,
                    "terminal_records": operations[attempt.operation_id],
                }
            )
        elif attempt.kind != RECORD_SESSION:
            effects.append(
                {
                    "attempt_id": attempt.identifier,
                    "recorded_state": attempt.state,
                    "recorded_evidence": attempt.evidence,
                }
            )
    return {
        "scope": "shared-workflow-flow",
        "state": "recorded_inputs_matched",
        "flow_id": after.flow_id,
        "case_order": list(cases),
        "operations": matched,
        "effects": effects,
        "pending_trigger_ids": list(after.pending_triggers),
        "semantic_settlement": "unproven",
    }
