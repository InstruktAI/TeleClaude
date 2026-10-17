"""Outside checks of new provisional identities and original ledger bytes, without final acceptance."""

from __future__ import annotations

import base64
import binascii
import hashlib
from pathlib import Path
from typing import Final

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
from tools.ci.workflow_flow import declared_chain

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
