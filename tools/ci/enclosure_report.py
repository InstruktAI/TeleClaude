"""Outside checks of new provisional identities and original ledger bytes, without final acceptance."""

from __future__ import annotations

import base64
import binascii
import hashlib
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Final, cast

from tools.ci import workflow_events as events
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
from tools.ci.workflow_flow import (
    B5_ACTIONS,
    B6_ACTIONS,
    B7_ACTIONS,
    ITEM,
    MESSAGE_STARTS,
    PROC_BUILD,
    PROC_WORK,
    ROLE_BUILDER,
    ROLE_WORK,
    declared_chain,
    message_key,
    procedure_key,
)
from tools.ci.workflow_ledger import (
    RECORD_DISCHARGED,
    RECORD_EFFECT,
    RECORD_OPERATION,
    RECORD_SESSION,
    RECORD_TRIGGER,
    Attempt,
    StartLedger,
)
from tools.ci.workflow_publication import TERMINAL_STATES
from tools.ci.workflow_ready import FINDING_DOOR, FINDING_WORK, REASON_ONE, REASON_TWO
from tools.ci.workflow_review import (
    B11_BASE_FEATURE_BYTES,
    B11_FEATURE_PATH,
    B11_LOCAL_COMMIT_MESSAGE,
    B11_LOCAL_HEAD_LABEL,
    B11_NUMSTAT,
    B11_SENTINEL_BYTES,
    B11_SENTINEL_LABEL,
    B11_SENTINEL_LINE,
    B11_STATUS_MODIFIED_BYTES,
    DIRECT_REFUSAL_ERRORS,
    FINDING_TEXT,
    REPLY_TEXT,
    WRONG_PERFORMER_TEXT,
)

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
CLAIM_STARTS: Final = {
    ("B5", "w2-start"): ("work", 1),
    ("B5", "w3-start"): ("work", 2),
    ("B7", "reasonone"): ("ready", 3),
}
REFUSAL_CALLS: Final = {
    ("B7", "ready-door"): (["telec", "todo", "prepare", ITEM], (FINDING_DOOR, f"telec todo work {ITEM} --reason")),
    ("B7", "ready-no-reason"): (["telec", "todo", "work", ITEM], (FINDING_WORK,)),
    ("B7", "ready-no-session"): (["telec", "todo", "work", ITEM, "--reason", "b7 owner terminal"], (FINDING_WORK,)),
    ("B6", "refused-work"): (["telec", "todo", "work", ITEM], ("admitted by the integrator", ITEM)),
}


def _strings(value: JsonValue) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(ERROR_REPORT)
    return tuple(item for item in value if isinstance(item, str))


def _event_bytes(value: JsonValue) -> bytes | None:
    """Recompute every retained read; a later matching read cannot erase an earlier different one."""
    if not isinstance(value, list):
        raise ValueError(ERROR_REPORT)
    original: bytes | None = None
    for raw in value:
        record = object_value(raw)
        if set(record) != {"raw_data", "raw_sha256", "raw_byte_count"}:
            raise ValueError(ERROR_REPORT)
        try:
            data = base64.b64decode(text(record, "raw_data"), validate=True)
        except (ValueError, binascii.Error) as error:
            raise ValueError(ERROR_REPORT) from error
        if (
            type(record["raw_byte_count"]) is not int
            or record["raw_byte_count"] != len(data)
            or record["raw_sha256"] != hashlib.sha256(data).hexdigest()
            or (original is not None and original != data)
        ):
            raise ValueError(ERROR_REPORT)
        original = data
    return original


def _event_binding(report: JsonObject, window: JsonObject, root: Path, sha: str) -> events.EventWindowBinding:
    """Construct addresses as data only; outside validation never opens a guest-reported path."""
    carrier = root / events.WINDOW_DIRECTORY
    item = object_value(window[events.FIELD_ITEM])
    mark = object_value(window["raw_mark"])
    project_home = text(window, "project_home")
    computer = text(window, events.FIELD_COMPUTER)
    cursor = text(window, events.FIELD_CURSOR)
    if (
        type(window.get(events.FIELD_SCHEMA)) is not int
        or window[events.FIELD_SCHEMA] != events.WINDOW_SCHEMA
        or item.get(events.FIELD_SUBJECT) != f"todo:{ITEM}"
        or item.get(events.FIELD_PROJECT) != project_home
        or item.get(events.FIELD_COMPUTER) != computer
        or mark.get(events.FIELD_ITEM) != item
        or mark.get(events.FIELD_CURSOR) != cursor
        or report.get(events.FIELD_WINDOW_PATH) != str(carrier / events.WINDOW_FILE)
        or report.get(events.FIELD_WITNESSES_PATH) != str(carrier / events.WITNESSES_FILE)
    ):
        raise ValueError(ERROR_REPORT)
    return events.EventWindowBinding(
        root,
        carrier,
        carrier / events.WINDOW_FILE,
        carrier / events.WITNESSES_FILE,
        root / events.CASE_REPORT_FILE,
        sha,
        text(window, "project_slug"),
        project_home,
        text(window, events.FIELD_PROJECT_PATH),
        computer,
    )


def _event_records(raw: bytes, cases: JsonObject, expected: tuple[str, ...], sha: str) -> list[Mapping[str, object]]:
    lines = raw.splitlines(keepends=True)
    if len(lines) != len(expected) or set(cases) != set(expected):
        raise ValueError(ERROR_REPORT)
    prefix = hashlib.sha256()
    records: list[Mapping[str, object]] = []
    for position, (line, case) in enumerate(zip(lines, expected, strict=True), 1):
        if not line.endswith(b"\n"):
            raise ValueError(ERROR_REPORT)
        row = parse_object(line)
        entry = object_value(cases[case])
        prefix.update(line)
        if (
            set(row) != {events.FIELD_CASE, events.FIELD_WINDOW_SHA, events.FIELD_DATA}
            or row[events.FIELD_CASE] != case
            or row[events.FIELD_WINDOW_SHA] != sha
            or not isinstance(row[events.FIELD_DATA], dict)
            or set(entry) != {events.FIELD_STATUS, events.FIELD_WITNESS_COUNT, events.FIELD_WITNESS_SHA}
            or entry[events.FIELD_STATUS] != "complete"
            or type(entry[events.FIELD_WITNESS_COUNT]) is not int
            or entry[events.FIELD_WITNESS_COUNT] != position
            or entry[events.FIELD_WITNESS_SHA] != prefix.hexdigest()
        ):
            raise ValueError(ERROR_REPORT)
        records.append(row)
    return records


def _labeled_inputs(inputs: JsonObject, key: str) -> dict[str, JsonObject]:
    values = inputs[key]
    if not isinstance(values, list):
        raise ValueError(ERROR_REPORT)
    rows: dict[str, JsonObject] = {}
    for value in values:
        row = object_value(value)
        label = text(row, "label")
        if label in rows:
            raise ValueError(ERROR_REPORT)
        rows[label] = row
    return rows


def _event_flow_links(
    binding: events.EventWindowBinding,
    records: list[Mapping[str, object]],
    sessions: JsonObject,
    starts: JsonObject,
) -> JsonObject:
    """Join already validated native facts to event witnesses without another read or result reclassification."""
    data = {str(row[events.FIELD_CASE]): object_value(cast(JsonObject, row)[events.FIELD_DATA]) for row in records}
    if "B5" not in data:
        if sessions.get("state") != "not_selected" or starts.get("state") != "not_selected":
            raise ValueError(ERROR_REPORT)
        return {"state": "shared_flow_not_selected"}
    if sessions.get("state") != "public_closed" or starts.get("state") != "recorded_inputs_matched":
        raise ValueError(ERROR_REPORT)
    closed = set(_strings(sessions["session_ids"]))
    children = starts["children"]
    if not isinstance(children, list) or len(children) != 1:
        raise ValueError(ERROR_REPORT)
    child = object_value(children[0])
    claims = _labeled_inputs(starts, "accepted_start_claims")
    direct = _labeled_inputs(starts, "direct_acts")
    b5 = data["B5"]
    w2 = text(claims["w2-start"], "actor")
    w3 = text(claims["w3-start"], "actor")
    builder = text(child, "session_id")
    if (
        b5.get("w2") != w2
        or b5.get("w3") != w3
        or b5.get("builder") != builder
        or not {w2, w3, builder} <= closed
        or child["project_path"] != binding.project_path
        or child["worktree"] != f"{binding.project_path}/trees/{ITEM}"
        or direct["reviewed"]["bound"] != b5.get("C1")
        or direct["finding"]["bound"] != b5.get("C1")
        or direct["finding"]["finding_key"] != b5.get("finding_key")
        or direct["reply"]["bound"] != b5.get("finding_key")
    ):
        raise ValueError(ERROR_REPORT)
    restorations = starts["local_restoration"]
    if (
        not isinstance(restorations, list)
        or len(restorations) != 2
        or any(object_value(value)["commit"] != b5.get("C2") for value in restorations)
    ):
        raise ValueError(ERROR_REPORT)
    linked: list[JsonValue] = ["B5 actors, C1 review/finding/reply and restored C2"]
    if "B7" in data:
        b7 = data["B7"]
        reasons = _labeled_inputs(starts, "reason_notes")
        one, two = reasons["reasonone"], reasons["reasontwo"]
        holder = text(claims["reasonone"], "actor")
        messages = object_value(sessions["message_sessions"])
        if (
            b7.get("first") != one["actor"]
            or b7.get("second") != two["actor"]
            or set(messages) != {text(one, "actor"), text(two, "actor")}
            or b7.get("w4") != holder
            or holder not in closed
            or one["holder"] != holder
            or two["holder"] != holder
            or b7.get("reason_one_note") != one["note"]
            or b7.get("reason_two_note") != two["note"]
            or b7.get("reason_one") != REASON_ONE
            or b7.get("reason_two") != REASON_TWO
            or any(
                row["ready_at_commit"] != b5.get("C3") or row["ready_since"] != b5.get("ready_since_C3")
                for row in (one, two)
            )
        ):
            raise ValueError(ERROR_REPORT)
        linked.append("B7 message authors, W4 claim, written notes and C3 ready context")
    return {"state": "shared_flow_inputs_linked", "matched": linked, "remaining_settlement": "unproven"}


def validate_event_inputs(report: JsonObject, sessions: JsonObject, starts: JsonObject) -> JsonObject:
    """Check original prefix bytes and, only with B6 coverage, rerun the existing positive event/log oracle."""
    selection = frozenset(_strings(report["selection"]))
    expected = tuple(case for case in events.CASE_SEQUENCE if not selection or f"UC-WF-{case}" in selection)
    if expected != events.CASE_SEQUENCE[: len(expected)]:
        raise ValueError(ERROR_REPORT)
    evidence = object_value(report["workflow_event_evidence"])
    capture = object_value(evidence["input_capture"])
    if (
        set(capture)
        != {"schema_version", "selected_case_prefix", "capture_error", "case_report", "window", "witnesses"}
        or type(capture["schema_version"]) is not int
        or capture["schema_version"] != 1
        or _strings(capture["selected_case_prefix"]) != expected
        or capture["capture_error"] is not None
    ):
        raise ValueError(ERROR_REPORT)
    case_bytes = _event_bytes(capture["case_report"])
    window_bytes = _event_bytes(capture["window"])
    witness_bytes = _event_bytes(capture["witnesses"])
    if not expected:
        if any(value is not None for value in (case_bytes, window_bytes, witness_bytes)) or evidence != {
            "status": "not_started",
            "cases": {},
            "input_capture": capture,
        }:
            raise ValueError(ERROR_REPORT)
        return {"state": "not_selected", "full_event_assertions": "not_covered"}
    if case_bytes is None or window_bytes is None or witness_bytes is None:
        raise ValueError(ERROR_REPORT)
    case_report = parse_object(case_bytes)
    window = parse_object(window_bytes)
    sha = hashlib.sha256(window_bytes).hexdigest()
    if (
        set(case_report) != {"schema_version", "window_sha256", "window_path", "witnesses_path", "cases"}
        or type(case_report[events.FIELD_SCHEMA]) is not int
        or case_report[events.FIELD_SCHEMA] != events.CASE_REPORT_SCHEMA
        or case_report[events.FIELD_WINDOW_SHA] != sha
        or evidence
        != {
            **case_report,
            "status": "complete" if expected == events.CASE_SEQUENCE else "unproven",
            "case_report_path": evidence.get("case_report_path"),
            "input_capture": capture,
        }
    ):
        raise ValueError(ERROR_REPORT)
    observations = object_value(object_value(report["payload_provisional"])["observations"])
    root = Path(text(observations, "owned_profile_root"))
    binding = _event_binding(case_report, window, root, sha)
    if evidence["case_report_path"] != str(binding.report_path):
        raise ValueError(ERROR_REPORT)
    records = _event_records(witness_bytes, object_value(case_report["cases"]), expected, sha)
    links = _event_flow_links(binding, records, sessions, starts)
    if expected == events.CASE_SEQUENCE:
        terminal = object_value(cast(JsonObject, records[-1])[events.FIELD_DATA])
        pages = terminal["pages"]
        coverages = terminal["coverage"]
        if (
            set(terminal) != {"delivered_commit", "final_item", "pages", "coverage", "read_error"}
            or terminal["read_error"] is not None
            or not isinstance(pages, list)
            or not isinstance(coverages, list)
        ):
            raise ValueError(ERROR_REPORT)
        text(terminal, "delivered_commit")
        events.assert_positive_window(
            binding,
            window,
            records,
            [object_value(page) for page in pages],
            [object_value(coverage) for coverage in coverages],
            object_value(terminal["final_item"]),
        )
    return {
        "state": "captured_prefix_integrity",
        "case_prefix": list(expected),
        "window_sha256": sha,
        "witness_sha256": hashlib.sha256(witness_bytes).hexdigest(),
        "full_event_assertions": "proven" if expected == events.CASE_SEQUENCE else "not_covered",
        "shared_flow_links": links,
    }


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


def _command_output(value: JsonValue, argv: list[str]) -> str:
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
    return command["stdout"]


def _public_session_command(value: JsonValue, argv: list[str]) -> Mapping[str, object]:
    # Reuse the actual public CLI framing parser, without reading any report-supplied address.
    record = foundation.json_object(_command_output(value, argv))
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


def _message_start_ack(report: JsonObject, packet: JsonObject, message: str, session_id: str) -> None:
    provisional = object_value(report["payload_provisional"])
    root = text(object_value(provisional["observations"]), "owned_profile_root")
    project = text(packet, "project_path")
    if not project.startswith(root.rstrip("/") + "/"):
        raise ValueError(ERROR_REPORT)
    argv = [
        foundation.TELEC,
        "sessions",
        "start",
        "--path",
        project,
        "--agent",
        "claude",
        "--mode",
        "fast",
        "--message",
        message,
    ]
    record = _public_session_command(packet["public_start"], argv)
    if record.get("status") != "success" or record.get("session_id") != session_id or record.get("agent") != "claude":
        raise ValueError(ERROR_REPORT)
    tmux = record.get("tmux_session_name")
    if not isinstance(tmux, str) or not tmux:
        raise ValueError(ERROR_REPORT)


def _message_hooks(packet: JsonObject, native: str, message: str) -> None:
    hooks = object_value(packet["hooks"])
    if set(hooks) != {"session_start", "prompt_submit"}:
        raise ValueError(ERROR_REPORT)
    for name, event in (("session_start", "SessionStart"), ("prompt_submit", "UserPromptSubmit")):
        frame = object_value(hooks[name])
        runs = frame["runs"]
        if (
            frame.get("event") != event
            or frame.get("native_session_id") != native
            or frame.get("registered") is not True
            or not isinstance(runs, list)
            or not runs
        ):
            raise ValueError(ERROR_REPORT)
        for value in runs:
            run = object_value(value)
            if type(run.get("exit_status")) is not int or run["exit_status"] != 0 or run.get("timed_out") is True:
                raise ValueError(ERROR_REPORT)
    inputs = packet["inputs"]
    if not isinstance(inputs, list) or not inputs:
        raise ValueError(ERROR_REPORT)
    first = object_value(inputs[0])
    if first.get("text") != message or first.get("hook_started") is not True:
        raise ValueError(ERROR_REPORT)


def _message_record(
    report: JsonObject, packet: JsonObject, attempt: Attempt, created: int, public_finished: int
) -> str:
    if (
        set(packet)
        != {
            "attempt_id",
            "started_ns",
            "observed_ns",
            "session_id",
            "mapped_session_id",
            "project_path",
            "baseline_ids",
            "current_ids",
            "public_record",
            "public_start",
            "launch_record",
            "hooks",
            "inputs",
        }
        or not created
        <= positive_integer(packet, "started_ns")
        <= positive_integer(packet, "observed_ns")
        <= public_finished
    ):
        raise ValueError(ERROR_REPORT)
    session_id = text(packet, "session_id")
    message = MESSAGE_STARTS[attempt.label]
    if attempt.session_id != session_id or packet["mapped_session_id"] != session_id:
        raise ValueError(ERROR_REPORT)
    baseline = _identity_list(packet["baseline_ids"])
    current = _identity_list(packet["current_ids"])
    if session_id not in set(current) - set(baseline):
        raise ValueError(ERROR_REPORT)
    record = object_value(packet["public_record"])
    launch = object_value(packet["launch_record"])
    native = text(record, "native_session_id")
    if (
        record.get("session_id") != session_id
        or record.get("project_path") != packet["project_path"]
        or record.get("role") is not None
        or record.get("job") is not None
        or record.get("initiator_session_id") is not None
        or record.get("active_agent") != "claude"
        or record.get("lifecycle_status") != "active"
        or record.get("runtime_start_observed") is not True
        or record.get("closed_at") is not None
        or launch.get("native_session_id") != native
        or launch.get("key_kind") != "message"
        or launch.get("key") != message_key(message)
        or type(launch.get("index")) is not int
        or launch["index"] != 1
        or launch.get("first_line") != message
    ):
        raise ValueError(ERROR_REPORT)
    _message_start_ack(report, packet, message, session_id)
    _message_hooks(packet, native, message)
    return native


def _message_bindings(
    report: JsonObject, finalizer: JsonObject, cases: tuple[str, ...], created: int, public_finished: int
) -> dict[str, str]:
    values = finalizer["public_message_evidence"]
    if not isinstance(values, list):
        raise ValueError(ERROR_REPORT)
    if "B7" not in cases:
        if values:
            raise ValueError(ERROR_REPORT)
        return {}
    snapshot = _declared_snapshot(finalizer["start_ledger_after_closure"], cases)
    if snapshot.ledger is None:
        raise ValueError(ERROR_REPORT)
    attempts = [
        attempt
        for attempt in snapshot.ledger.attempts.values()
        if attempt.case == "B7" and attempt.label in MESSAGE_STARTS
    ]
    if (
        len(attempts) != 2
        or {attempt.label for attempt in attempts} != set(MESSAGE_STARTS)
        or any(attempt.kind != RECORD_SESSION or attempt.state != RECORD_DISCHARGED for attempt in attempts)
        or len(values) != 2
    ):
        raise ValueError(ERROR_REPORT)
    expected = {attempt.identifier: attempt for attempt in attempts}
    seen: set[str] = set()
    bindings: dict[str, str] = {}
    for value in values:
        packet = object_value(value)
        identifier = text(packet, "attempt_id")
        session_id = text(packet, "session_id")
        if identifier not in expected or identifier in seen or session_id in bindings:
            raise ValueError(ERROR_REPORT)
        bindings[session_id] = _message_record(report, packet, expected[identifier], created, public_finished)
        seen.add(identifier)
    if len(set(bindings.values())) != len(bindings):
        raise ValueError(ERROR_REPORT)
    return bindings


def _session_end_proof(
    proof: JsonObject, created: int, public_finished: int, messages: dict[str, str]
) -> tuple[str, str]:
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
    if session_id in messages:
        if any(
            record.get("role") is not None
            or record.get("job") is not None
            or record.get("initiator_session_id") is not None
            or record.get("native_session_id") != messages[session_id]
            for record in records
        ):
            raise ValueError(ERROR_REPORT)
        role = "roleless"
    elif not isinstance(role, str) or not role or role == "unknown":
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
            "public_message_evidence",
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
    messages = _message_bindings(report, finalizer, cases, created, public_finished)
    observed: dict[str, str] = {}
    for value in proofs:
        session_id, role = _session_end_proof(object_value(value), created, public_finished, messages)
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
        "message_sessions": {session: native for session, native in messages.items()},
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


def _claimed_holder(held: JsonObject, actor: str, phase: str) -> None:
    state = object_value(held["state"])
    standing = object_value(held["standing"])
    if (
        state.get("active_runner") != actor
        or state.get("lifecycle_phase") != phase
        or state.get("hold") is not False
        or standing.get("held_by") != actor
        or standing.get("phase") != phase
    ):
        raise ValueError(ERROR_REPORT)
    text(standing, "held_since")
    log = text(object_value(held["artifact_content"]), "log")
    claims = [entry for entry in events.parse_log_entries(log) if entry.act == "claim"]
    if (
        not claims
        or claims[-1].session != actor
        or claims[-1].role != ROLE_WORK
        or ITEM not in claims[-1].body
        or actor not in claims[-1].body
    ):
        raise ValueError(ERROR_REPORT)


def _pane_run(value: JsonValue, argv: list[str], *, successful: bool = True) -> JsonObject:
    frame = object_value(value)
    run = object_value(frame["run"])
    if (
        frame.get("argv") != argv
        or type(run.get("exit_status")) is not int
        or (run["exit_status"] == 0) is not successful
        or run.get("timed_out") is True
        or run.get("diagnostics") not in (None, "")
    ):
        raise ValueError(ERROR_REPORT)
    return run


def _pane_operation(value: JsonValue, argv: list[str]) -> str:
    run = _pane_run(value, argv)
    receipt = foundation.json_object(text(run, "stdout"))
    operation_id = receipt.get("operation_id") if receipt is not None else None
    if not isinstance(operation_id, str) or not operation_id:
        raise ValueError(ERROR_REPORT)
    return operation_id


def _claim_record(row: JsonObject, attempt: Attempt, created: int, public_finished: int) -> JsonObject:
    if set(row) != {"attempt_id", "actor", "phase", "startup_record", "launch_record", "claim"}:
        raise ValueError(ERROR_REPORT)
    phase, index = CLAIM_STARTS[attempt.case, attempt.label]
    actor = text(row, "actor")
    startup = object_value(row["startup_record"])
    launch = object_value(row["launch_record"])
    native = text(startup, "native_session_id")
    if (
        row["phase"] != phase
        or startup.get("session_id") != actor
        or startup.get("role") != ROLE_WORK
        or startup.get("job") != PROC_WORK
        or startup.get("title") != f"{ROLE_WORK} {ITEM}"
        or launch.get("native_session_id") != native
        or launch.get("key_kind") != "procedure"
        or launch.get("key") != procedure_key(PROC_WORK)
        or type(launch.get("index")) is not int
        or launch["index"] != index
    ):
        raise ValueError(ERROR_REPORT)
    claim = object_value(row["claim"])
    if set(claim) != {"started_ns", "returned_ns", "observed_ns", "frame", "terminal", "held"} or not (
        created
        <= positive_integer(claim, "started_ns")
        <= positive_integer(claim, "returned_ns")
        <= positive_integer(claim, "observed_ns")
        <= public_finished
    ):
        raise ValueError(ERROR_REPORT)
    operation_id = _pane_operation(claim["frame"], ["telec", "todo", "work", ITEM])
    terminal = object_value(claim["terminal"])
    if (
        operation_id == attempt.operation_id
        or terminal.get("operation_id") != operation_id
        or terminal.get("state") != "completed"
        or terminal.get("error") not in (None, "")
        or not isinstance(terminal.get("result"), str)
    ):
        raise ValueError(ERROR_REPORT)
    instruction = text(terminal, "result")
    if any(needle not in instruction for needle in (ITEM, phase, actor)):
        raise ValueError(ERROR_REPORT)
    _claimed_holder(object_value(claim["held"]), actor, phase)
    return {
        "attempt_id": attempt.identifier,
        "label": attempt.label,
        "actor": actor,
        "phase": phase,
        "native_session_id": native,
        "start_operation_id": attempt.operation_id,
        "claim_operation_id": operation_id,
        "state": "public_claim_matched",
    }


def _claim_inputs(
    finalizer: JsonObject,
    ledger: StartLedger,
    operations: dict[str, list[JsonValue]],
    created: int,
    public_finished: int,
) -> list[JsonValue]:
    expected_pairs = {pair for pair in CLAIM_STARTS if pair[0] in ledger.closed_lists}
    attempts = [attempt for attempt in ledger.attempts.values() if (attempt.case, attempt.label) in expected_pairs]
    if (
        {(attempt.case, attempt.label) for attempt in attempts} != expected_pairs
        or len(attempts) != len(expected_pairs)
        or any(attempt.kind != RECORD_OPERATION or attempt.state != RECORD_DISCHARGED for attempt in attempts)
    ):
        raise ValueError(ERROR_REPORT)
    expected = {attempt.identifier: attempt for attempt in attempts}
    values = finalizer["public_claim_evidence"]
    if not isinstance(values, list) or len(values) != len(expected):
        raise ValueError(ERROR_REPORT)
    seen: set[str] = set()
    matched: list[JsonValue] = []
    owned = _strings(finalizer["owned_session_ids"])
    for value in values:
        row = object_value(value)
        identifier = text(row, "attempt_id")
        if identifier not in expected or identifier in seen or text(row, "actor") not in owned:
            raise ValueError(ERROR_REPORT)
        attempt = expected[identifier]
        if attempt.operation_id is None:
            raise ValueError(ERROR_REPORT)
        for terminal in operations[attempt.operation_id]:
            result = object_value(terminal)
            if result.get("state") != "completed" or result.get("error") not in (None, ""):
                raise ValueError(ERROR_REPORT)
        matched.append(_claim_record(row, attempt, created, public_finished))
        seen.add(identifier)
    return matched


def _identity_list(value: JsonValue) -> tuple[str, ...]:
    values = _strings(value)
    if values != tuple(sorted(set(values))) or any(not item for item in values):
        raise ValueError(ERROR_REPORT)
    return values


def _refusal_sessions(row: JsonObject, case: str, owned: tuple[str, ...]) -> None:
    before = _identity_list(row["before_session_ids"])
    baseline = _identity_list(row["baseline_session_ids"])
    observations = row["session_observations"]
    if not isinstance(observations, list) or len(observations) != (2 if case == "B7" else 1):
        raise ValueError(ERROR_REPORT)
    if case == "B6":
        observation = object_value(observations[0])
        if (
            set(observation) != {"session_ids"}
            or baseline != before
            or _identity_list(observation["session_ids"]) != before
        ):
            raise ValueError(ERROR_REPORT)
        return
    if not set(baseline) <= set(before):
        raise ValueError(ERROR_REPORT)
    for value in observations:
        observation = object_value(value)
        if set(observation) != {"baseline_ids", "current_ids", "new_session_records"}:
            raise ValueError(ERROR_REPORT)
        current = _identity_list(observation["current_ids"])
        additions = object_value(observation["new_session_records"])
        if (
            _identity_list(observation["baseline_ids"]) != baseline
            or not set(baseline) <= set(current)
            or set(additions) != set(current) - set(baseline)
        ):
            raise ValueError(ERROR_REPORT)
        for session_id, record in additions.items():
            actual = object_value(record)
            if (
                session_id not in owned
                or actual.get("session_id") != session_id
                or actual.get("role") != "integrator"
                or actual.get("initiator_session_id") not in (None, "")
            ):
                raise ValueError(ERROR_REPORT)


def _refusal_record(
    row: JsonObject,
    attempt: Attempt,
    terminals: list[JsonValue],
    created: int,
    public_finished: int,
    owned: tuple[str, ...],
) -> JsonObject:
    if set(row) != {
        "attempt_id",
        "started_ns",
        "finished_ns",
        "before_item",
        "before_session_ids",
        "baseline_session_ids",
        "command",
        "after_items",
        "session_observations",
    }:
        raise ValueError(ERROR_REPORT)
    started = positive_integer(row, "started_ns")
    finished = positive_integer(row, "finished_ns")
    if not created <= started <= finished <= public_finished:
        raise ValueError(ERROR_REPORT)
    argv, needles = REFUSAL_CALLS[attempt.case, attempt.label]
    receipt = _public_session_command(row["command"], argv)
    if receipt.get("operation_id") != attempt.operation_id:
        raise ValueError(ERROR_REPORT)
    before = object_value(row["before_item"])
    required = needles
    if attempt.case == "B6":
        required = (*needles, text(object_value(before["standing"]), "ready_at_commit"))
    elif object_value(before["standing"]).get("phase") != "ready":
        raise ValueError(ERROR_REPORT)
    for value in terminals:
        terminal = object_value(value)
        error = text(terminal, "error")
        if terminal.get("state") != "failed" or any(needle not in error for needle in required):
            raise ValueError(ERROR_REPORT)
    after_items = row["after_items"]
    if not isinstance(after_items, list) or len(after_items) != (2 if attempt.case == "B7" else 1):
        raise ValueError(ERROR_REPORT)
    positions: list[int] = []
    for value in after_items:
        after = object_value(value)
        observed = positive_integer(after, "observed_ns")
        if set(after) != {"observed_ns", "item"} or after["item"] != before or not started <= observed <= finished:
            raise ValueError(ERROR_REPORT)
        positions.append(observed)
    # This is the original approved functional refusal window, never a P4 quiet-period proof.
    if attempt.case == "B7" and positions[1] - positions[0] < 5 * NANOSECONDS:
        raise ValueError(ERROR_REPORT)
    _refusal_sessions(row, attempt.case, owned)
    return {"attempt_id": attempt.identifier, "operation_id": attempt.operation_id, "state": "public_refusal_matched"}


def _refusal_inputs(
    finalizer: JsonObject,
    ledger: StartLedger,
    operations: dict[str, list[JsonValue]],
    created: int,
    public_finished: int,
) -> list[JsonValue]:
    pairs = {pair for pair in REFUSAL_CALLS if pair[0] in ledger.closed_lists}
    attempts = [attempt for attempt in ledger.attempts.values() if (attempt.case, attempt.label) in pairs]
    if (
        {(attempt.case, attempt.label) for attempt in attempts} != pairs
        or len(attempts) != len(pairs)
        or any(attempt.kind != RECORD_OPERATION or attempt.state != RECORD_DISCHARGED for attempt in attempts)
    ):
        raise ValueError(ERROR_REPORT)
    expected = {attempt.identifier: attempt for attempt in attempts}
    values = finalizer["public_refusal_evidence"]
    if not isinstance(values, list) or len(values) != len(expected):
        raise ValueError(ERROR_REPORT)
    seen: set[str] = set()
    matched: list[JsonValue] = []
    owned = _strings(finalizer["owned_session_ids"])
    for value in values:
        row = object_value(value)
        identifier = text(row, "attempt_id")
        if identifier not in expected or identifier in seen:
            raise ValueError(ERROR_REPORT)
        attempt = expected[identifier]
        if attempt.operation_id is None:
            raise ValueError(ERROR_REPORT)
        matched.append(_refusal_record(row, attempt, operations[attempt.operation_id], created, public_finished, owned))
        seen.add(identifier)
    return matched


def _note_rows(item: JsonObject, authors: tuple[str, ...]) -> tuple[str, ...]:
    standing = object_value(item["standing"])
    if "admitted" in standing or standing.get("phase") != "ready":
        raise ValueError(ERROR_REPORT)
    reasons = standing["reasons"]
    if not isinstance(reasons, list) or len(reasons) != len(authors):
        raise ValueError(ERROR_REPORT)
    notes: list[str] = []
    for value, author, reason in zip(reasons, authors, (REASON_ONE, REASON_TWO), strict=False):
        row = object_value(value)
        if row.get("session") != author or row.get("text") != reason:
            raise ValueError(ERROR_REPORT)
        notes.append(text(row, "note"))
    if len(notes) != len(set(notes)):
        raise ValueError(ERROR_REPORT)
    return tuple(notes)


def _reason_log(row: JsonObject, before: JsonObject, after: JsonObject, actor: str, label: str, holder: str) -> None:
    before_log = text(object_value(before["artifact_content"]), "log")
    before_entries = events.parse_log_entries(before_log)
    pairs = [list[JsonValue]((entry.header, entry.body)) for entry in before_entries]
    if row["before_log"] != pairs:
        raise ValueError(ERROR_REPORT)
    after_log = text(object_value(after["artifact_content"]), "log")
    entries = events.parse_log_entries(after_log)
    if entries[: len(before_entries)] != before_entries:
        raise ValueError(ERROR_REPORT)
    added = entries[len(before_entries) :]
    first = label == "reasonone"
    if len(added) != (2 if first else 1):
        raise ValueError(ERROR_REPORT)
    reason = REASON_ONE if first else REASON_TWO
    digest = hashlib.sha256(reason.encode("utf-8")).hexdigest()[:16]
    if (
        added[0].act != "note"
        or added[0].session != actor
        or digest not in added[0].header
        or reason not in added[0].body
    ):
        raise ValueError(ERROR_REPORT)
    if first and (added[1].act != "claim" or added[1].session != holder or ITEM not in added[1].body):
        raise ValueError(ERROR_REPORT)


def _reason_record(
    row: JsonObject,
    attempt: Attempt,
    terminals: list[JsonValue],
    authors: tuple[str, str],
    holder: str,
    created: int,
    public_finished: int,
) -> JsonObject:
    if set(row) != {
        "attempt_id",
        "actor",
        "started_ns",
        "returned_ns",
        "observed_ns",
        "frame",
        "before_item",
        "before_log",
        "after_item",
    } or not (
        created
        <= positive_integer(row, "started_ns")
        <= positive_integer(row, "returned_ns")
        <= positive_integer(row, "observed_ns")
        <= public_finished
    ):
        raise ValueError(ERROR_REPORT)
    first = attempt.label == "reasonone"
    actor = authors[0 if first else 1]
    reason = REASON_ONE if first else REASON_TWO
    if (
        row["actor"] != actor
        or _pane_operation(row["frame"], ["telec", "todo", "work", ITEM, "--reason", reason]) != attempt.operation_id
    ):
        raise ValueError(ERROR_REPORT)
    before = object_value(row["before_item"])
    after = object_value(row["after_item"])
    old = object_value(before["standing"])
    current = object_value(after["standing"])
    for key in ("ready_at_commit", "ready_since"):
        if text(old, key) != text(current, key):
            raise ValueError(ERROR_REPORT)
    _claimed_holder(after, holder, "ready")
    notes = _note_rows(after, authors[:1] if first else authors)
    if not first:
        previous_notes = _note_rows(before, authors[:1])
        if (
            notes[0] != previous_notes[0]
            or cast(list[JsonValue], current["reasons"])[0] != cast(list[JsonValue], old["reasons"])[0]
        ):
            raise ValueError(ERROR_REPORT)
    _reason_log(row, before, after, actor, attempt.label, holder)
    credits: list[JsonValue] = []
    for value in terminals:
        terminal = object_value(value)
        if terminal.get("state") != ("completed" if first else "failed"):
            raise ValueError(ERROR_REPORT)
        output = text(terminal, "result" if first else "error")
        note = re.search(r"recorded as note\s+(\S+)", output)
        if first and "has not claimed yet" in output:
            credits.append("pending result; session and note clauses not evaluated")
        elif (
            (f"session {holder} holds the claim" in output if first else holder in output)
            and note is not None
            and note.group(1) == notes[-1]
        ):
            credits.append(
                "result names matched session and public note" if first else "refusal names holder and written note"
            )
        else:
            raise ValueError(ERROR_REPORT)
    return {
        "attempt_id": attempt.identifier,
        "operation_id": attempt.operation_id,
        "label": attempt.label,
        "actor": actor,
        "holder": holder,
        "note": notes[-1],
        "state": "public_note_matched",
        "native_result_credit": credits,
        "ready_at_commit": current["ready_at_commit"],
        "ready_since": current["ready_since"],
    }


def _reason_inputs(
    finalizer: JsonObject,
    ledger: StartLedger,
    operations: dict[str, list[JsonValue]],
    claims: list[JsonValue],
    created: int,
    public_finished: int,
) -> list[JsonValue]:
    values = finalizer["public_reason_evidence"]
    if not isinstance(values, list):
        raise ValueError(ERROR_REPORT)
    if "B7" not in ledger.closed_lists:
        if values:
            raise ValueError(ERROR_REPORT)
        return []
    reasons = [
        attempt
        for attempt in ledger.attempts.values()
        if attempt.case == "B7" and attempt.label in ("reasonone", "reasontwo")
    ]
    if (
        len(reasons) != 2
        or {attempt.label for attempt in reasons} != {"reasonone", "reasontwo"}
        or any(attempt.kind != RECORD_OPERATION or attempt.state != RECORD_DISCHARGED for attempt in reasons)
        or len(values) != 2
    ):
        raise ValueError(ERROR_REPORT)
    expected = {attempt.identifier: attempt for attempt in reasons}
    reason_one = next(attempt for attempt in reasons if attempt.label == "reasonone")
    holders = [
        text(object_value(value), "actor")
        for value in claims
        if object_value(value)["attempt_id"] == reason_one.identifier
    ]
    if len(holders) != 1:
        raise ValueError(ERROR_REPORT)
    authors: list[str] = []
    for label in ("session-S_R", "session-S2"):
        actors = [attempt for attempt in ledger.attempts.values() if attempt.case == "B7" and attempt.label == label]
        if (
            len(actors) != 1
            or actors[0].kind != RECORD_SESSION
            or actors[0].state != RECORD_DISCHARGED
            or actors[0].session_id is None
        ):
            raise ValueError(ERROR_REPORT)
        authors.append(actors[0].session_id)
    if authors[0] == authors[1]:
        raise ValueError(ERROR_REPORT)
    seen: set[str] = set()
    matched: list[JsonValue] = []
    for value in values:
        row = object_value(value)
        identifier = text(row, "attempt_id")
        if identifier not in expected or identifier in seen:
            raise ValueError(ERROR_REPORT)
        attempt = expected[identifier]
        if attempt.operation_id is None:
            raise ValueError(ERROR_REPORT)
        matched.append(
            _reason_record(
                row,
                attempt,
                operations[attempt.operation_id],
                (authors[0], authors[1]),
                holders[0],
                created,
                public_finished,
            )
        )
        seen.add(identifier)
    return matched


def _child_record(
    packet: JsonObject, attempt: Attempt, parent: JsonObject, created: int, public_finished: int, root: str
) -> JsonObject:
    if (
        set(packet)
        != {
            "attempt_id",
            "parent_attempt_id",
            "started_ns",
            "observed_ns",
            "parent_actor",
            "parent_native_session_id",
            "base_project",
            "worktree",
            "frame",
            "public_record",
            "launch_record",
        }
        or not created
        <= positive_integer(packet, "started_ns")
        <= positive_integer(packet, "observed_ns")
        <= public_finished
    ):
        raise ValueError(ERROR_REPORT)
    actor = text(parent, "actor")
    if (
        packet["parent_attempt_id"] != attempt.parent
        or packet["parent_actor"] != actor
        or packet["parent_native_session_id"] != parent["native_session_id"]
    ):
        raise ValueError(ERROR_REPORT)
    run = _pane_run(packet["frame"], ["telec", "todo", "child", ITEM])
    match = re.search(rf"Started {re.escape(PROC_BUILD)} as session ([A-Za-z0-9_-]+)", text(run, "stdout"))
    if match is None or attempt.session_id != match.group(1) or attempt.session_id == actor:
        raise ValueError(ERROR_REPORT)
    record = object_value(packet["public_record"])
    launch = object_value(packet["launch_record"])
    native = text(record, "native_session_id")
    project = text(packet, "base_project")
    worktree = text(packet, "worktree")
    subdir = f"trees/{ITEM}"
    if (
        not project.startswith(root.rstrip("/") + "/")
        or worktree != f"{project}/{subdir}"
        or record.get("session_id") != attempt.session_id
        or record.get("initiator_session_id") != actor
        or record.get("role") != ROLE_BUILDER
        or record.get("job") != PROC_BUILD
        or record.get("active_agent") != "claude"
        or record.get("lifecycle_status") != "active"
        or record.get("runtime_start_observed") is not True
        or record.get("closed_at") is not None
        or record.get("project_path") != project
        or record.get("subdir") != subdir
        or launch.get("native_session_id") != native
        or native == parent["native_session_id"]
        or launch.get("cwd") != worktree
        or launch.get("key_kind") != "procedure"
        or launch.get("key") != procedure_key(PROC_BUILD)
        or type(launch.get("index")) is not int
        or launch["index"] != 1
    ):
        raise ValueError(ERROR_REPORT)
    return {
        "attempt_id": attempt.identifier,
        "session_id": attempt.session_id,
        "parent_attempt_id": attempt.parent,
        "parent_actor": actor,
        "native_session_id": native,
        "state": "public_child_started",
        "project_path": project,
        "worktree": worktree,
    }


def _child_inputs(
    finalizer: JsonObject, ledger: StartLedger, claims: list[JsonValue], created: int, public_finished: int, root: str
) -> list[JsonValue]:
    values = finalizer["public_child_evidence"]
    if not isinstance(values, list):
        raise ValueError(ERROR_REPORT)
    if "B5" not in ledger.closed_lists:
        if values:
            raise ValueError(ERROR_REPORT)
        return []
    children = [attempt for attempt in ledger.attempts.values() if attempt.case == "B5" and attempt.label == "w2-child"]
    if len(children) != 1 or len(values) != 1:
        raise ValueError(ERROR_REPORT)
    child = children[0]
    if (
        child.kind != RECORD_SESSION
        or child.state != RECORD_DISCHARGED
        or child.session_id is None
        or child.parent is None
    ):
        raise ValueError(ERROR_REPORT)
    packet = object_value(values[0])
    if packet["attempt_id"] != child.identifier or child.session_id not in _strings(finalizer["owned_session_ids"]):
        raise ValueError(ERROR_REPORT)
    parents = [object_value(value) for value in claims if object_value(value)["attempt_id"] == child.parent]
    if len(parents) != 1 or ledger.attempts[child.parent].label != "w2-start":
        raise ValueError(ERROR_REPORT)
    return [_child_record(packet, child, parents[0], created, public_finished, root)]


def _direct_argv(label: str, commit: str, finding: str) -> list[str]:
    base = ["telec", "todo", "act", ITEM]
    return {
        "reviewed": [*base, "reviewed", "--sha", commit],
        "finding": [*base, "finding", "--sha", commit, FINDING_TEXT],
        "reply": [*base, "reply", "--finding", finding, REPLY_TEXT],
        "reviewed-wrong": [*base, "reviewed", "--sha", commit],
        "finding-wrong": [*base, "finding", "--sha", commit, WRONG_PERFORMER_TEXT],
        "reply-wrong": [*base, "reply", "--finding", finding, WRONG_PERFORMER_TEXT],
        "kickback-wrong": [*base, "kickback", WRONG_PERFORMER_TEXT],
        "release-wrong": [*base, "release"],
    }[label]


def _direct_log(before: JsonObject, after: JsonObject, label: str, actor: str, bound: str) -> None:
    old = events.parse_log_entries(text(object_value(before["artifact_content"]), "log"))
    current = events.parse_log_entries(text(object_value(after["artifact_content"]), "log"))
    if len(current) != len(old) + 1 or current[:-1] != old:
        raise ValueError(ERROR_REPORT)
    body = {"reviewed": "", "finding": FINDING_TEXT, "reply": REPLY_TEXT}[label]
    expected_bound = (
        bound if label == "reviewed" else f"{bound}:{hashlib.sha256(body.encode('utf-8')).hexdigest()[:16]}"
    )
    entry = current[-1]
    if (
        not entry.timestamp
        or entry.session != actor
        or entry.role != (ROLE_BUILDER if label == "reply" else ROLE_WORK)
        or entry.act != label
        or entry.bound != expected_bound
        or entry.body != body
    ):
        raise ValueError(ERROR_REPORT)


def _direct_record(
    row: JsonObject,
    attempt: Attempt,
    worker: str,
    builder: str,
    commit: str,
    finding: str,
    created: int,
    public_finished: int,
) -> JsonObject:
    if (
        set(row)
        != {
            "attempt_id",
            "actor",
            "bound",
            "started_ns",
            "observed_ns",
            "before_item",
            "after_item",
            "frame",
        }
        or not created <= positive_integer(row, "started_ns") <= positive_integer(row, "observed_ns") <= public_finished
    ):
        raise ValueError(ERROR_REPORT)
    label = attempt.label
    refused = label in DIRECT_REFUSAL_ERRORS
    actor = worker if label in ("reviewed", "finding", "reply-wrong") else builder
    if row["actor"] != actor:
        raise ValueError(ERROR_REPORT)
    run = _pane_run(row["frame"], _direct_argv(label, commit, finding), successful=not refused)
    before = object_value(row["before_item"])
    after = object_value(row["after_item"])
    for item in (before, after):
        state = object_value(item["state"])
        standing = object_value(item["standing"])
        if (
            state.get("active_runner") != worker
            or state.get("lifecycle_phase") != "work"
            or standing.get("held_by") != worker
            or standing.get("phase") != "work"
        ):
            raise ValueError(ERROR_REPORT)
    if refused:
        stdout = run.get("stdout")
        stderr = run.get("stderr")
        if not isinstance(stdout, str) or not isinstance(stderr, str):
            raise ValueError(ERROR_REPORT)
        output = stdout + stderr
        if (
            row["bound"] is not None
            or before != after
            or DIRECT_REFUSAL_ERRORS[label] not in output
            or "Performed " in output
        ):
            raise ValueError(ERROR_REPORT)
    else:
        bound = finding if label == "reply" else commit
        if row["bound"] != bound or f"Performed {label} on {ITEM}" not in text(run, "stdout"):
            raise ValueError(ERROR_REPORT)
        _direct_log(before, after, label, actor, bound)
    return {
        "attempt_id": attempt.identifier,
        "actor": actor,
        "label": attempt.label,
        "bound": row["bound"],
        "finding_key": finding if label == "finding" else None,
        "state": "public_direct_refusal_matched" if refused else "public_direct_append_matched",
    }


def _direct_inputs(
    finalizer: JsonObject,
    ledger: StartLedger,
    claims: list[JsonValue],
    children: list[JsonValue],
    created: int,
    public_finished: int,
) -> list[JsonValue]:
    labels = {*DIRECT_REFUSAL_ERRORS, "reviewed", "finding", "reply"}
    attempts = [attempt for attempt in ledger.attempts.values() if attempt.case == "B5" and attempt.label in labels]
    values = finalizer["public_direct_evidence"]
    if not isinstance(values, list):
        raise ValueError(ERROR_REPORT)
    if "B5" not in ledger.closed_lists:
        if values:
            raise ValueError(ERROR_REPORT)
        return []
    if (
        {attempt.label for attempt in attempts} != labels
        or len(attempts) != len(labels)
        or len(values) != len(labels)
        or any(attempt.kind != RECORD_EFFECT or attempt.state != RECORD_DISCHARGED for attempt in attempts)
    ):
        raise ValueError(ERROR_REPORT)
    expected = {attempt.identifier: attempt for attempt in attempts}
    packets: dict[str, JsonObject] = {}
    for value in values:
        row = object_value(value)
        identifier = text(row, "attempt_id")
        if identifier not in expected or expected[identifier].label in packets:
            raise ValueError(ERROR_REPORT)
        packets[expected[identifier].label] = row
    commit = text(packets["reviewed"], "bound")
    if packets["finding"]["bound"] != commit:
        raise ValueError(ERROR_REPORT)
    finding_run = _pane_run(packets["finding"]["frame"], _direct_argv("finding", commit, ""))
    match = re.search(r"finding key:\s*(\S+)", text(finding_run, "stdout"))
    if match is None or len(children) != 1:
        raise ValueError(ERROR_REPORT)
    child = object_value(children[0])
    parent_claims = [
        object_value(value) for value in claims if object_value(value)["attempt_id"] == child["parent_attempt_id"]
    ]
    if len(parent_claims) != 1:
        raise ValueError(ERROR_REPORT)
    worker = text(parent_claims[0], "actor")
    builder = text(child, "session_id")
    return [
        _direct_record(
            packets[attempt.label], attempt, worker, builder, commit, match.group(1), created, public_finished
        )
        for attempt in attempts
    ]


def _restoration_reads(
    value: JsonValue, project: str, worktree: str
) -> tuple[dict[tuple[str, ...], list[str]], list[bytes]]:
    if not isinstance(value, list):
        raise ValueError(ERROR_REPORT)
    commands: dict[tuple[str, ...], list[str]] = {}
    files: list[bytes] = []
    for entry in value:
        row = object_value(entry)
        if row.get("kind") == "command":
            if set(row) != {"kind", "cwd", "value"}:
                raise ValueError(ERROR_REPORT)
            cwd = text(row, "cwd")
            command = object_value(row["value"])
            argv = _strings(command["argv"])
            if not argv or argv[0] != "git" or cwd not in (project, worktree):
                raise ValueError(ERROR_REPORT)
            output = _command_output(command, list(argv))
            commands.setdefault((cwd, *argv), []).append(output)
        elif row.get("kind") == "file":
            if set(row) != {"kind", "path", "raw_data"} or row["path"] != f"{worktree}/{B11_FEATURE_PATH}":
                raise ValueError(ERROR_REPORT)
            try:
                files.append(base64.b64decode(text(row, "raw_data"), validate=True))
            except (ValueError, binascii.Error) as error:
                raise ValueError(ERROR_REPORT) from error
        else:
            raise ValueError(ERROR_REPORT)
    return commands, files


def _git_read(
    reads: dict[tuple[str, ...], list[str]], cwd: str, argv: tuple[str, ...], expected: str, *, raw: bool = False
) -> tuple[str, ...]:
    key = (cwd, "git", *argv)
    values = reads.get(key)
    if not values or any((value if raw else value.strip()) != expected for value in values):
        raise ValueError(ERROR_REPORT)
    return key


def _restoration_refs(
    reads: dict[tuple[str, ...], list[str]], project: str, worktree: str, remote: str, head: str, count: str | None
) -> tuple[set[tuple[str, ...]], str]:
    keys = {
        _git_read(reads, project, ("ls-remote", "origin", f"refs/heads/{ITEM}"), f"{remote}\trefs/heads/{ITEM}"),
        _git_read(reads, worktree, ("rev-parse", "HEAD"), head),
        _git_read(reads, worktree, ("show-ref", "--verify", f"refs/heads/{ITEM}"), f"{head} refs/heads/{ITEM}"),
    }
    key = (worktree, "git", "rev-list", "--count", f"origin/main..{ITEM}")
    values = reads.get(key)
    if not values or any(
        not value.strip().isdigit() or (count is not None and value.strip() != count) for value in values
    ):
        raise ValueError(ERROR_REPORT)
    keys.add(key)
    return keys, values[0].strip()


def _restoration_stage(
    value: JsonValue,
    project: str,
    worktree: str,
    commit: str,
    head: str,
    count: str | None,
    mode: str,
) -> str:
    reads, files = _restoration_reads(value, project, worktree)
    keys, found_count = _restoration_refs(reads, project, worktree, commit, head, count)
    status = ("status", "--porcelain=v1", "--untracked-files=all")
    cached = ("diff", "--cached", "--name-only")
    if mode == "append":
        keys.add(_git_read(reads, worktree, status, B11_STATUS_MODIFIED_BYTES.decode("utf-8"), raw=True))
        keys.add(_git_read(reads, worktree, cached, ""))
        keys.add(_git_read(reads, worktree, ("diff", "--numstat", "--", B11_FEATURE_PATH), B11_NUMSTAT))
        key = (worktree, "git", "diff", "--no-ext-diff", "--unified=0", "--", B11_FEATURE_PATH)
        diffs = reads.get(key)
        if not diffs or any(
            [line for line in diff.splitlines() if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))]
            != [f"+{B11_SENTINEL_LINE}"]
            for diff in diffs
        ):
            raise ValueError(ERROR_REPORT)
        keys.add(key)
        expected_files = [B11_BASE_FEATURE_BYTES + B11_SENTINEL_BYTES]
    else:
        keys.add(_git_read(reads, worktree, status, ""))
        expected_files = [B11_BASE_FEATURE_BYTES]
        if mode == "clean":
            keys.add(_git_read(reads, worktree, cached, ""))
            keys.add(
                _git_read(
                    reads,
                    worktree,
                    ("show", f"{commit}:{B11_FEATURE_PATH}"),
                    B11_BASE_FEATURE_BYTES.decode("utf-8"),
                    raw=True,
                )
            )
        elif mode == "local-head":
            keys.add(_git_read(reads, worktree, ("rev-parse", f"{head}^"), commit))
            expected_files = []
        elif mode != "reset":
            raise ValueError(ERROR_REPORT)
    if set(reads) != keys or files != expected_files:
        raise ValueError(ERROR_REPORT)
    return found_count


def _restoration_record(
    row: JsonObject, attempt: Attempt, builder: str, created: int, public_finished: int, root: str
) -> JsonObject:
    if (
        set(row)
        != {
            "label",
            "actor",
            "attempt_id",
            "started_ns",
            "observed_ns",
            "base_project",
            "worktree",
            "commit",
            "before_item",
            "after_item",
            "before_reads",
            "changed_reads",
            "pre_restore_reads",
            "post_restore_reads",
            "write_frame",
            "mutation_command",
            "restore_command",
            "temporary_head",
        }
        or row["label"] != attempt.label
        or not (
            created <= positive_integer(row, "started_ns") <= positive_integer(row, "observed_ns") <= public_finished
        )
    ):
        raise ValueError(ERROR_REPORT)
    project = text(row, "base_project")
    worktree = text(row, "worktree")
    commit = text(row, "commit")
    if not project.startswith(root.rstrip("/") + "/") or worktree != f"{project}/trees/{ITEM}":
        raise ValueError(ERROR_REPORT)
    if object_value(row["before_item"]) != object_value(row["after_item"]):
        raise ValueError(ERROR_REPORT)
    count = _restoration_stage(row["before_reads"], project, worktree, commit, commit, None, "clean")
    if attempt.label == B11_SENTINEL_LABEL:
        if row["actor"] != builder or row["mutation_command"] is not None or row["temporary_head"] is not None:
            raise ValueError(ERROR_REPORT)
        frame = object_value(row["write_frame"])
        writes = frame["writes"]
        if (
            frame.get("ok") is not True
            or frame.get("cwd") != worktree
            or not isinstance(writes, list)
            or len(writes) != 1
        ):
            raise ValueError(ERROR_REPORT)
        write = object_value(writes[0])
        if (
            write.get("path") != B11_FEATURE_PATH
            or write.get("mode") != "append"
            or type(write.get("bytes")) is not int
            or write["bytes"] != len(B11_SENTINEL_BYTES)
            or write.get("sha256") != hashlib.sha256(B11_SENTINEL_BYTES).hexdigest()
        ):
            raise ValueError(ERROR_REPORT)
        for key in ("changed_reads", "pre_restore_reads"):
            _restoration_stage(row[key], project, worktree, commit, commit, count, "append")
        _command_output(row["restore_command"], ["git", "restore", "--worktree", "--", B11_FEATURE_PATH])
        _restoration_stage(row["post_restore_reads"], project, worktree, commit, commit, count, "clean")
    else:
        temporary = text(row, "temporary_head")
        if row["actor"] is not None or row["write_frame"] is not None or temporary == commit:
            raise ValueError(ERROR_REPORT)
        _command_output(row["mutation_command"], ["git", "commit", "--allow-empty", "-m", B11_LOCAL_COMMIT_MESSAGE])
        for key in ("changed_reads", "pre_restore_reads"):
            _restoration_stage(row[key], project, worktree, commit, temporary, None, "local-head")
        _command_output(row["restore_command"], ["git", "reset", "--hard", commit])
        _restoration_stage(row["post_restore_reads"], project, worktree, commit, commit, count, "reset")
    return {"attempt_id": attempt.identifier, "state": "owned_local_effect_restored", "commit": commit}


def _restoration_inputs(
    finalizer: JsonObject, ledger: StartLedger, children: list[JsonValue], created: int, public_finished: int, root: str
) -> list[JsonValue]:
    labels = {B11_SENTINEL_LABEL, B11_LOCAL_HEAD_LABEL}
    attempts = [attempt for attempt in ledger.attempts.values() if attempt.case == "B5" and attempt.label in labels]
    values = finalizer["public_restoration_evidence"]
    if not isinstance(values, list):
        raise ValueError(ERROR_REPORT)
    if "B5" not in ledger.closed_lists:
        if values:
            raise ValueError(ERROR_REPORT)
        return []
    if (
        len(attempts) != 2
        or {attempt.label for attempt in attempts} != labels
        or len(values) != 2
        or len(children) != 1
        or any(attempt.kind != RECORD_EFFECT or attempt.state != RECORD_DISCHARGED for attempt in attempts)
    ):
        raise ValueError(ERROR_REPORT)
    expected = {attempt.identifier: attempt for attempt in attempts}
    builder = text(object_value(children[0]), "session_id")
    seen: set[str] = set()
    commits: set[str] = set()
    result: list[JsonValue] = []
    for value in values:
        row = object_value(value)
        identifier = text(row, "attempt_id")
        if identifier not in expected or identifier in seen:
            raise ValueError(ERROR_REPORT)
        result.append(_restoration_record(row, expected[identifier], builder, created, public_finished, root))
        commits.add(text(row, "commit"))
        seen.add(identifier)
    if len(commits) != 1:
        raise ValueError(ERROR_REPORT)
    return result


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
    claims = _claim_inputs(finalizer, after.ledger, operations, created, public_finished)
    children = _child_inputs(
        finalizer, after.ledger, claims, created, public_finished, text(observations, "owned_profile_root")
    )
    return {
        "scope": "shared-workflow-flow",
        "state": "recorded_inputs_matched",
        "flow_id": after.flow_id,
        "case_order": list(cases),
        "operations": matched,
        "effects": effects,
        "pending_trigger_ids": list(after.pending_triggers),
        "accepted_start_claims": claims,
        "refusals": _refusal_inputs(finalizer, after.ledger, operations, created, public_finished),
        "reason_notes": _reason_inputs(finalizer, after.ledger, operations, claims, created, public_finished),
        "children": children,
        "direct_acts": _direct_inputs(finalizer, after.ledger, claims, children, created, public_finished),
        "local_restoration": _restoration_inputs(
            finalizer, after.ledger, children, created, public_finished, text(observations, "owned_profile_root")
        ),
        "semantic_settlement": "unproven",
    }
