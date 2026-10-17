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

from tools.ci import workflow_creation as creation
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
from tools.ci.workflow_creation import collect_slugs
from tools.ci.workflow_driver import DRIVER_ID as PROC_PREPARE
from tools.ci.workflow_driver import ROLE as ROLE_PREPARE
from tools.ci.workflow_driver import assert_claim_observation, assert_instruction
from tools.ci.workflow_flow import (
    B5_ACTIONS,
    B6_ACTIONS,
    B6_COMMIT,
    B7_ACTIONS,
    ITEM,
    MESSAGE_STARTS,
    PROC_BUILD,
    PROC_INTEGRATE,
    PROC_WORK,
    ROLE_BUILDER,
    ROLE_INTEGRATOR,
    ROLE_WORK,
    declared_chain,
    message_key,
    procedure_key,
)
from tools.ci.workflow_integration import EXPECTED_FEATURE, EXPECTED_MAKEFILE, FEATURE_FILE, INTEGRATION_TREE, MAKE_FILE
from tools.ci.workflow_ledger import (
    RECORD_DISCHARGED,
    RECORD_EFFECT,
    RECORD_OPERATION,
    RECORD_SESSION,
    RECORD_TRIGGER,
    Attempt,
    StartLedger,
)
from tools.ci.workflow_prepared import (
    B4_ATTEMPT_LEDGER,
    B4_B9_ACTIONS,
    B4_CASE,
    B9_S_P_MESSAGE,
    B9_X_MESSAGE,
    END_S_P,
    END_X,
    SESSION_S_P,
    SESSION_X,
    caller_startup_body,
    text_capability_enabled,
)
from tools.ci.workflow_prepared import CONTROL_NAME as PREPARED_CONTROLS
from tools.ci.workflow_publication import START_CLAIMED, START_REFUSED, TERMINAL_STATES
from tools.ci.workflow_ready import FINDING_DOOR, FINDING_WORK, REASON_ONE, REASON_TWO
from tools.ci.workflow_review import (
    B11_BASE_FEATURE_BYTES,
    B11_DIRTY_REFUSAL,
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
    LANE_ONE,
    LANE_TWO,
    REPLY_TEXT,
    WRONG_PERFORMER_TEXT,
)
from tools.ci.workflow_waiting import CHILD_PROCEDURE, CHILD_ROLE, DISPATCH_MESSAGE, STARTED_CHILD
from tools.ci.workflow_waiting import CONTROL_NAME as WAITING_CONTROLS

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
        "early_workflow",
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
    stamps = _labeled_inputs(starts, "stamps")
    integrators = object_value(starts["integrators"])
    if (
        stamps["stamp-ok"]["commit"] != b5.get("C2")
        or stamps["stamp-ok"]["ready_since"] != b5.get("ready_since_C2")
        or stamps["stamp-ok2"]["commit"] != b5.get("C3")
        or stamps["stamp-ok2"]["ready_since"] != b5.get("ready_since_C3")
        or _identity_list(b5["integrators"]) != tuple(sorted(object_value(integrators["sessions"])))
    ):
        raise ValueError(ERROR_REPORT)
    linked: list[JsonValue] = ["B5 actors, C1 review/finding/reply, restored C2 and C2/C3 stamps"]
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
    if "B6" in data:
        integration = object_value(starts["integration"])
        delivery = object_value(integration["delivery"])
        main = text(delivery, "main_head")
        final_item = object_value(data["B6"]["final_item"])
        roadmap = object_value(final_item["roadmap"])
        if (
            integration["candidate"] != b5.get("C3")
            or data["B6"].get("delivered_commit") != main
            or final_item.get("stage") != "delivered"
            or roadmap.get("status") != "delivered"
            or roadmap.get("delivered_commit") != main
        ):
            raise ValueError(ERROR_REPORT)
        text(roadmap, "delivered_at")
        linked.append("B6 admitted C3 and delivered public main readback")
    return {"state": "shared_flow_inputs_linked", "matched": linked, "remaining_settlement": "unproven"}


def _event_early_links(
    binding: events.EventWindowBinding, records: list[Mapping[str, object]], early: JsonObject
) -> JsonObject:
    matched: list[JsonValue] = []
    for record in records:
        case = str(record[events.FIELD_CASE])
        if case not in ("B3", "B4"):
            continue
        data = object_value(cast(JsonObject, record)[events.FIELD_DATA])
        inputs = object_value(early[case])
        if case == "B3":
            actors = tuple(text(data, key) for key in ("owner", "first_driver", "child", "dispatched", "second_driver"))
            driver_actors = {"first": data["first_driver"], "second": data["second_driver"]}
            expected_new = {"first": {text(data, "owner"), text(data, "first_driver")}, "second": set(actors)}
            claim_contexts = {
                "first": ([], [text(data, "owner")]),
                "second": ([text(data, "first_driver")], [text(data, "owner"), text(data, "dispatched")]),
            }
            actor_ids = {"owner": data["owner"], "child": data["child"], "dispatched": data["dispatched"]}
            actor_parents = {"owner": None, "child": data["first_driver"], "dispatched": data["owner"]}
        else:
            actors = _strings(data["sessions"])
            outsiders = object_value(data["outsider_sessions"])
            if (
                set(outsiders) != {"S_P", "X"}
                or len(actors) != 5
                or set(actors)
                != {text(data, key) for key in ("author", "child", "worker")} | set(_strings(list(outsiders.values())))
            ):
                raise ValueError(ERROR_REPORT)
            ledger = object_value(inputs["attempt_ledger_inputs"])
            sessions = object_value(ledger["session_ids"])
            if sessions != {SESSION_S_P: outsiders["S_P"], SESSION_X: outsiders["X"]}:
                raise ValueError(ERROR_REPORT)
            driver_actors = {"author": data["author"], "worker": data["worker"]}
            expected_new = {
                "author": {text(data, "author"), text(outsiders, "S_P"), text(outsiders, "X")},
                "worker": set(actors),
            }
            claim_contexts = {"author": ([], []), "worker": ([], [])}
            actor_ids = {"S_P": outsiders["S_P"], "X": outsiders["X"], "child": data["child"]}
            actor_parents = {"S_P": None, "X": outsiders["S_P"], "child": data["author"]}
        other_actors = object_value(inputs["other_actor_inputs"])
        if set(other_actors) != set(actor_ids) or any(
            object_value(other_actors[name])["session_id"] != actor
            or object_value(other_actors[name])["parent_actor"] != actor_parents[name]
            for name, actor in actor_ids.items()
        ):
            raise ValueError(ERROR_REPORT)
        driver_inputs = object_value(inputs["driver_inputs"])
        if set(driver_inputs) != set(driver_actors) or any(
            object_value(driver_inputs[name])["session_id"] != actor
            or set(_strings(object_value(driver_inputs[name])["expected_new"])) != expected_new[name]
            for name, actor in driver_actors.items()
        ):
            raise ValueError(ERROR_REPORT)
        for name, (earlier, holds_nothing) in claim_contexts.items():
            context = object_value(object_value(driver_inputs[name])["claim_context"])
            if (
                context["earlier"] != earlier
                or context["holds_nothing"] != holds_nothing
                or (case == "B3" and context["known_entries"] != 0)
            ):
                raise ValueError(ERROR_REPORT)
        if (
            len(actors) != len(set(actors))
            or inputs["project_path"] != binding.project_path
            or set(actors) != set(_strings(inputs["observed_new_session_ids"]))
        ):
            raise ValueError(ERROR_REPORT)
        matched.append(case)
    if set(early) != set(matched):
        raise ValueError(ERROR_REPORT)
    return {"cases": matched, "state": "early_actor_listing_inputs_matched", "creator_classification": "unproven"}


def _early_session_list(value: JsonValue) -> dict[str, Mapping[str, object]]:
    output = _command_output(value, [creation.TELEC, "sessions", "list", "--all", "--closed"])
    values = creation.decode_array(output)
    if values is None:
        raise ValueError(ERROR_REPORT)
    rows: dict[str, Mapping[str, object]] = {}
    for entry in values:
        if not isinstance(entry, Mapping):
            raise ValueError(ERROR_REPORT)
        session = entry.get("session_id")
        if not isinstance(session, str) or not session or session in rows:
            raise ValueError(ERROR_REPORT)
        rows[session] = entry
    return rows


def _early_closures(value: JsonValue, expected: set[str]) -> list[JsonValue]:
    if not isinstance(value, list) or len(value) != len(expected):
        raise ValueError(ERROR_REPORT)
    seen: set[str] = set()
    operations: list[JsonValue] = []
    for entry in value:
        row = object_value(entry)
        session = text(row, "session_id")
        reads = row["reads"]
        if (
            set(row) != {"session_id", "command", "terminal", "reads", "error"}
            or session not in expected
            or session in seen
            or row["error"] is not None
            or not isinstance(reads, list)
            or len(reads) != 1
        ):
            raise ValueError(ERROR_REPORT)
        receipt = _public_session_command(row["command"], [creation.TELEC, "sessions", "end", session])
        terminal = object_value(row["terminal"])
        operation = receipt.get("operation_id")
        closed = _public_session_command(reads[0], [creation.TELEC, "sessions", "show", session, "--full"])
        if (
            not isinstance(operation, str)
            or not operation
            or terminal.get("operation_id") != operation
            or terminal.get("state") != "completed"
            or terminal.get("error") not in (None, "")
            or not _public_closed(closed, session)
        ):
            raise ValueError(ERROR_REPORT)
        operations.append({"session_id": session, "operation_id": operation})
        seen.add(session)
    return operations


def _early_launches(value: JsonValue, root: str, case: str) -> list[JsonValue]:
    control, size = (WAITING_CONTROLS, 7) if case == "B3" else (PREPARED_CONTROLS, 5)
    if not isinstance(value, list) or len(value) != size:
        raise ValueError(ERROR_REPORT)
    result: list[JsonValue] = []
    for index, entry in enumerate(value):
        row = object_value(entry)
        path = f"{root}/{control}/d{index}"
        if (
            set(row) != {"control", "shown_exists", "launches_data", "shown_data", "read_error"}
            or row["control"] != path
            or type(row["shown_exists"]) is not bool
            or row["read_error"] is not None
        ):
            raise ValueError(ERROR_REPORT)
        if row["shown_exists"] is False:
            if row["launches_data"] is not None or row["shown_data"] is not None:
                raise ValueError(ERROR_REPORT)
            result.append({"control": path, "state": "launch_not_observed"})
            continue
        try:
            data = base64.b64decode(text(row, "launches_data"), validate=True)
            shown_data = base64.b64decode(text(row, "shown_data"), validate=True)
        except (ValueError, binascii.Error) as error:
            raise ValueError(ERROR_REPORT) from error
        shown = parse_object(shown_data)
        records = [parse_object(line) for line in data.splitlines() if line.strip()]
        if not records:
            raise ValueError(ERROR_REPORT)
        native, pid = text(shown, "native_session_id"), positive_integer(shown, "pid")
        launches: list[JsonValue] = []
        found = False
        for record in records:
            record_native = text(record, "native_session_id")
            record_pid = positive_integer(record, "pid")
            launches.append({"native_session_id": record_native, "pid": record_pid, "cwd": text(record, "cwd")})
            if record_native == native and record_pid == pid:
                found = True
        if not found:
            raise ValueError(ERROR_REPORT)
        result.append(
            {
                "control": path,
                "state": "recorded_launch_inputs",
                "launches_sha256": hashlib.sha256(data).hexdigest(),
                "shown_sha256": hashlib.sha256(shown_data).hexdigest(),
                "launches": launches,
            }
        )
    return result


def _early_closed_record(value: JsonValue, actor: JsonObject, project: str) -> None:
    session = text(actor, "session_id")
    record = _public_session_command(value, [creation.TELEC, "sessions", "show", session, "--full"])
    if (
        not _public_closed(record, session)
        or record.get("native_session_id") != text(actor, "native_session_id")
        or record.get("project_path") != project
    ):
        raise ValueError(ERROR_REPORT)


def _early_end_operation(value: JsonValue, operation: str | None = None) -> Mapping[str, object]:
    record: Mapping[str, object]
    if operation is None:
        record = object_value(value)
    else:
        record = _public_session_command(value, [creation.TELEC, "operations", "get", operation])
    identity = record.get("operation_id")
    if (
        not isinstance(identity, str)
        or not identity
        or (operation is not None and identity != operation)
        or record.get("kind") != "session_close"
        or record.get("state") not in ("queued", "running", "completed")
        or record.get("error") not in (None, "")
        or record.get("error_payload") is not None
    ):
        raise ValueError(ERROR_REPORT)
    return record


def _early_end_reads(packet: JsonObject, operation: str, outsider: bool) -> JsonValue:
    reads, closed = packet["operation_reads"], packet["closed_reads"]
    if not isinstance(reads, list) or not reads or not isinstance(closed, list) or len(closed) != 1:
        raise ValueError(ERROR_REPORT)
    terminal_seen = False
    for read in reads:
        state = _early_end_operation(read, operation)["state"]
        if terminal_seen and state != "completed":
            raise ValueError(ERROR_REPORT)
        terminal_seen = state == "completed"
    if not terminal_seen:
        raise ValueError(ERROR_REPORT)
    if outsider:
        # await_terminal issues its retained terminal read after the poll that observes completion.
        if len(reads) < 2:
            raise ValueError(ERROR_REPORT)
    elif _early_end_operation(packet["retained_terminal"], operation)["state"] != "completed":
        raise ValueError(ERROR_REPORT)
    return closed[0]


def _early_end_inputs(
    row: JsonObject, case: str, drivers: JsonObject, other_actors: JsonObject, ledger: JsonObject
) -> JsonObject:
    """Match every original end/read, including errors, without treating public closure as physical exit."""
    actors = {name: object_value(value) for name, value in {**drivers, **other_actors}.items()}
    by_session = {text(actor, "session_id"): actor for actor in actors.values()}
    if len(by_session) != len(actors):
        raise ValueError(ERROR_REPORT)
    project = text(row, "project_path")
    expected = ("first", "second", "dispatched", "owner") if case == "B3" else ("X", "S_P", "author", "worker")
    values, closed_values = row["ends"], row["closed_reads"]
    if not isinstance(values, list) or not isinstance(closed_values, list):
        raise ValueError(ERROR_REPORT)
    attempts = ledger.get("attempts", [])
    if not isinstance(attempts, list):
        raise ValueError(ERROR_REPORT)
    labels = {text(object_value(value), "label"): object_value(value) for value in attempts}
    proofs: JsonObject = {}
    original_operations: dict[str, str] = {}
    completed: set[str] = set()
    previous_end = positive_integer(row, "started_ns")
    for value in values:
        packet = object_value(value)
        session = text(packet, "session_id")
        if session not in by_session:
            raise ValueError(ERROR_REPORT)
        name = next(name for name, actor in actors.items() if actor["session_id"] == session)
        outsider = case == "B4" and name in ("X", "S_P")
        fields = {
            "kind",
            "session_id",
            "started_ns",
            "finished_ns",
            "command",
            "operation_reads",
            "closed_reads",
            "error",
        }
        fields |= {"label", "attempt_id", "original_operation_id"} if outsider else {"retained_terminal"}
        if (
            set(packet) != fields
            or name not in expected
            or packet["kind"] != ("b4-outsider-end" if outsider else "foundation-end")
            or packet["error"] is not None
            or not previous_end
            <= positive_integer(packet, "started_ns")
            <= positive_integer(packet, "finished_ns")
            <= positive_integer(row, "finished_ns")
        ):
            raise ValueError(ERROR_REPORT)
        previous_end = positive_integer(packet, "finished_ns")
        if packet["command"] is None:
            if not outsider or name not in proofs:
                raise ValueError(ERROR_REPORT)
            operation = text(packet, "original_operation_id")
            if original_operations.get(operation) != session:
                raise ValueError(ERROR_REPORT)
        else:
            if name in proofs:
                raise ValueError(ERROR_REPORT)
            receipt = _public_session_command(packet["command"], [creation.TELEC, "sessions", "end", session])
            operation = cast(str, _early_end_operation(cast(JsonValue, receipt))["operation_id"])
            if operation in original_operations:
                raise ValueError(ERROR_REPORT)
            original_operations[operation] = session
        if outsider:
            label = END_X if name == "X" else END_S_P
            attempt = labels.get(label)
            if (
                attempt is None
                or packet["label"] != label
                or packet["attempt_id"] != attempt.get("attempt_id")
                or attempt.get("kind") != RECORD_OPERATION
                or attempt.get("operation_id") != operation
                or (packet["command"] is not None and packet["original_operation_id"] is not None)
            ):
                raise ValueError(ERROR_REPORT)
        _early_closed_record(_early_end_reads(packet, operation, outsider), by_session[session], project)
        proofs[name] = {"session_id": session, "operation_id": operation, "state": "original_public_end_inputs_matched"}
        completed.add(session)
    if tuple(proofs) != expected:
        raise ValueError(ERROR_REPORT)
    for value in closed_values:
        packet = object_value(value)
        session = text(packet, "session_id")
        if (
            set(packet) != {"session_id", "started_ns", "finished_ns", "command"}
            or session not in by_session
            or not positive_integer(row, "started_ns")
            <= positive_integer(packet, "started_ns")
            <= positive_integer(packet, "finished_ns")
            <= positive_integer(row, "finished_ns")
        ):
            raise ValueError(ERROR_REPORT)
        _early_closed_record(packet["command"], by_session[session], project)
        completed.add(session)
    if completed != set(by_session):
        raise ValueError(ERROR_REPORT)
    return {"ends": proofs, "public_closed_session_ids": list[JsonValue](sorted(completed)), "physical_P4": "unproven"}


def _b4_ledger_inputs(row: JsonObject, root: str, case: str) -> JsonObject:
    reads = row["attempt_ledgers"]
    if case != B4_CASE:
        if reads != []:
            raise ValueError(ERROR_REPORT)
        return {"state": "not_applicable"}
    if not isinstance(reads, list) or not reads:
        raise ValueError(ERROR_REPORT)
    expected = {value["label"]: (value["kind"], value.get("parent")) for value in B4_B9_ACTIONS}
    previous: bytes | None = None
    flow_id: str | None = None
    sessions: JsonObject = {}
    attempts: list[JsonValue] = []
    digests: list[JsonValue] = []
    for value in reads:
        packet = object_value(value)
        raw = packet["raw_reads"]
        if (
            set(packet) != {"started_ns", "finished_ns", "path", "raw_reads", "error"}
            or packet["error"] is not None
            or packet["path"] != f"{root}/{PREPARED_CONTROLS}/{B4_ATTEMPT_LEDGER}"
            or not positive_integer(row, "started_ns")
            <= positive_integer(packet, "started_ns")
            <= positive_integer(packet, "finished_ns")
            <= positive_integer(row, "finished_ns")
            or not isinstance(raw, list)
            or len(raw) != 1
        ):
            raise ValueError(ERROR_REPORT)
        data = _event_bytes(raw)
        if data is None or (previous is not None and not data.startswith(previous)):
            raise ValueError(ERROR_REPORT)
        snapshot = LedgerEvidence.capture(data, path=Path(B4_ATTEMPT_LEDGER), expected_cases=(B4_CASE,))
        ledger = snapshot.ledger
        if (
            snapshot.error is not None
            or ledger is None
            or snapshot.missing_cases
            or snapshot.extra_cases
            or snapshot.blocking_attempts
            or snapshot.pending_triggers
            or ledger.closed_lists != {B4_CASE: expected}
            or (flow_id is not None and ledger.flow_id != flow_id)
        ):
            raise ValueError(ERROR_REPORT)
        current = {attempt.label: attempt for attempt in ledger.attempts.values()}
        if set(current) != set(expected) or len(current) != len(ledger.attempts):
            raise ValueError(ERROR_REPORT)
        attempts = []
        current_sessions: JsonObject = {}
        for label, attempt in current.items():
            kind, parent = expected[label]
            if (
                attempt.case != B4_CASE
                or attempt.kind != kind
                or attempt.state != RECORD_DISCHARGED
                or attempt.parent != (current[parent].identifier if parent is not None else None)
            ):
                raise ValueError(ERROR_REPORT)
            if kind == RECORD_SESSION:
                if attempt.session_id is None:
                    raise ValueError(ERROR_REPORT)
                current_sessions[label] = attempt.session_id
            attempts.append(
                {
                    "attempt_id": attempt.identifier,
                    "label": label,
                    "kind": kind,
                    "parent_attempt_id": attempt.parent,
                    "operation_id": attempt.operation_id,
                    "session_id": attempt.session_id,
                    "recorded_evidence": attempt.evidence,
                }
            )
        if (
            len(current_sessions) != 2
            or current_sessions[SESSION_S_P] == current_sessions[SESSION_X]
            or (sessions and sessions != current_sessions)
        ):
            raise ValueError(ERROR_REPORT)
        sessions = current_sessions
        flow_id, previous = ledger.flow_id, data
        digests.append(hashlib.sha256(data).hexdigest())
    return {
        "state": "declared_attempt_inputs_checked",
        "flow_id": flow_id,
        "read_sha256": digests,
        "session_ids": sessions,
        "attempts": attempts,
        "semantic_settlement": "unproven",
    }


def _early_driver_startup(
    startup: JsonObject, project: str, procedure: str, role: str, baseline: set[str], started: int, finished: int
) -> tuple[str, str]:
    if (
        set(startup)
        != {
            "started_ns",
            "observed_ns",
            "session_id",
            "expected_new",
            "list",
            "launch",
            "owned_executable",
            "hooks",
            "record",
            "declared_role",
            "inputs",
        }
        or not started
        <= positive_integer(startup, "started_ns")
        <= positive_integer(startup, "observed_ns")
        <= finished
    ):
        raise ValueError(ERROR_REPORT)
    actor = text(startup, "session_id")
    lists = startup["list"]
    expected = set(_identity_list(startup["expected_new"]))
    if (
        not isinstance(lists, list)
        or len(lists) != 1
        or actor not in expected
        or set(_early_session_list(lists[0])) - baseline != expected
    ):
        raise ValueError(ERROR_REPORT)
    launch = object_value(startup["launch"])
    record = object_value(startup["record"])
    owned = text(startup, "owned_executable")
    native = text(launch, "native_session_id")
    if (
        launch.get("executable") != owned
        or launch.get("resolved_command") != owned
        or record.get("session_id") != actor
        or record.get("native_session_id") != native
        or record.get("project_path") != project
        or record.get("active_agent") != "claude"
        or record.get("lifecycle_status") != "active"
        or record.get("runtime_start_observed") is not True
        or record.get("closed_at") is not None
        or record.get("role") != role
        or startup["declared_role"] != role
        or record.get("job") != procedure
        or record.get("title") != f"{role} {ITEM}"
    ):
        raise ValueError(ERROR_REPORT)
    hooks = startup["hooks"]
    inputs = startup["inputs"]
    if not isinstance(hooks, list) or len(hooks) != 2 or not isinstance(inputs, list) or not inputs:
        raise ValueError(ERROR_REPORT)
    frames = _actor_hooks(hooks)
    first = text(object_value(inputs[0]), "text")
    if procedure not in first:
        raise ValueError(ERROR_REPORT)
    _message_hooks({"hooks": frames, "inputs": inputs}, native, first)
    return actor, native


def _early_driver_claim(
    claim: JsonObject, actor: str, role: str, verb: str, phase: str, started: int, finished: int
) -> str:
    if (
        set(claim) != {"started_ns", "returned_ns", "observed_ns", "frame", "terminal", "held", "distinct_from"}
        or not started
        <= positive_integer(claim, "started_ns")
        <= positive_integer(claim, "returned_ns")
        <= positive_integer(claim, "observed_ns")
        <= finished
    ):
        raise ValueError(ERROR_REPORT)
    operation = _pane_operation(claim["frame"], ["telec", "todo", verb, ITEM])
    terminal = object_value(claim["terminal"])
    if (
        operation in _strings(claim["distinct_from"])
        or terminal.get("operation_id") != operation
        or terminal.get("state") != "completed"
        or terminal.get("error") not in (None, "")
    ):
        raise ValueError(ERROR_REPORT)
    instruction = text(terminal, "result")
    if any(needle not in instruction for needle in (ITEM, actor, phase)):
        raise ValueError(ERROR_REPORT)
    _claimed_holder(object_value(claim["held"]), actor, phase, role)
    return operation


def _early_driver_oracles(packet: JsonObject, actor: str, phase: str) -> JsonObject:
    claim = object_value(packet["claim"])
    terminal = object_value(claim["terminal"])
    instruction = object_value(packet["instruction"])
    context = object_value(packet["claim_context"])
    if (
        set(instruction) != {"session_id", "text", "child", "acts"}
        or instruction["session_id"] != actor
        or instruction["text"] != terminal["result"]
        or set(context) != {"session_id", "known_entries", "earlier", "holds_nothing"}
        or context["session_id"] != actor
        or type(context["known_entries"]) is not int
        or context["known_entries"] < 0
    ):
        raise ValueError(ERROR_REPORT)
    values = instruction["acts"]
    if not isinstance(values, list) or not values:
        raise ValueError(ERROR_REPORT)
    acts: list[tuple[str, str]] = []
    for value in values:
        pair = _strings(value)
        if len(pair) != 2 or not all(pair):
            raise ValueError(ERROR_REPORT)
        acts.append((pair[0], pair[1]))
    assert_instruction(ITEM, phase, actor, text(instruction, "text"), acts, text(instruction, "child"))
    assert_claim_observation(
        ITEM,
        phase,
        actor,
        object_value(claim["held"]),
        _strings(context["holds_nothing"]),
        _strings(context["earlier"]),
        context["known_entries"],
    )
    return context


def _early_driver_inputs(
    row: JsonObject, case: str, baseline: set[str], observed: set[str], launches: list[JsonValue]
) -> JsonObject:
    expected = (
        {
            "first": (1, PROC_PREPARE, "prepare", "preparation", ROLE_PREPARE),
            "second": (4, PROC_PREPARE, "prepare", "preparation", ROLE_PREPARE),
        }
        if case == "B3"
        else {
            "author": (2, PROC_PREPARE, "prepare", "preparation", ROLE_PREPARE),
            "worker": (4, PROC_WORK, "work", "work", ROLE_WORK),
        }
    )
    values = row["drivers"]
    if not isinstance(values, list) or len(values) != len(expected):
        raise ValueError(ERROR_REPORT)
    result: JsonObject = {}
    native_ids: set[str] = set()
    for value in values:
        packet = object_value(value)
        name = text(packet, "name")
        if (
            set(packet)
            != {"name", "slot", "procedure", "verb", "phase", "startup", "claim", "instruction", "claim_context"}
            or name not in expected
            or name in result
        ):
            raise ValueError(ERROR_REPORT)
        slot, procedure, verb, phase, role = expected[name]
        if (
            type(packet["slot"]) is not int
            or packet["slot"] != slot
            or packet["procedure"] != procedure
            or packet["verb"] != verb
            or packet["phase"] != phase
        ):
            raise ValueError(ERROR_REPORT)
        startup = object_value(packet["startup"])
        actor, native = _early_driver_startup(
            startup,
            text(row, "project_path"),
            procedure,
            role,
            baseline,
            positive_integer(row, "started_ns"),
            positive_integer(row, "finished_ns"),
        )
        if actor not in observed or native in native_ids:
            raise ValueError(ERROR_REPORT)
        native_ids.add(native)
        slot_input = object_value(launches[slot])
        recorded = slot_input.get("launches")
        pid = positive_integer(object_value(startup["launch"]), "pid")
        if not isinstance(recorded, list) or not any(
            object_value(value).get("native_session_id") == native and object_value(value).get("pid") == pid
            for value in recorded
        ):
            raise ValueError(ERROR_REPORT)
        operation = _early_driver_claim(
            object_value(packet["claim"]),
            actor,
            role,
            verb,
            phase,
            positive_integer(row, "started_ns"),
            positive_integer(row, "finished_ns"),
        )
        result[name] = {
            "state": "native_startup_and_claim_inputs_matched",
            "session_id": actor,
            "native_session_id": native,
            "claim_operation_id": operation,
            "expected_new": startup["expected_new"],
            "claim_context": _early_driver_oracles(packet, actor, phase),
            "distinct_from": object_value(packet["claim"])["distinct_from"],
            "originating_start_settlement": "unproven",
        }
    return result


def _early_start_inputs(row: JsonObject, case: str, drivers: JsonObject, starts: JsonObject) -> list[JsonValue]:
    expected = (
        {"start": ("first", "prepare")}
        if case == "B3"
        else {"start": ("author", "prepare"), "work": ("worker", "work")}
    )
    values = row["start_calls"]
    if not isinstance(values, list) or len(values) != len(expected):
        raise ValueError(ERROR_REPORT)
    seen: set[str] = set()
    result: list[JsonValue] = []
    for value in values:
        packet = object_value(value)
        label = text(packet, "label")
        if (
            set(packet) != {"label", "attempt_key", "started_ns", "finished_ns", "command", "operation_id", "error"}
            or label not in expected
            or label in seen
            or packet["error"] is not None
            or not positive_integer(row, "started_ns")
            <= positive_integer(packet, "started_ns")
            <= positive_integer(packet, "finished_ns")
            <= positive_integer(row, "finished_ns")
        ):
            raise ValueError(ERROR_REPORT)
        text(packet, "attempt_key")
        name, verb = expected[label]
        receipt = _public_session_command(packet["command"], [creation.TELEC, "todo", verb, ITEM])
        operation = receipt.get("operation_id")
        driver = object_value(drivers[name])
        if (
            not isinstance(operation, str)
            or not operation
            or packet["operation_id"] != operation
            or starts.get(operation) != START_CLAIMED
            or driver["distinct_from"] != [operation]
            or driver["claim_operation_id"] == operation
        ):
            raise ValueError(ERROR_REPORT)
        result.append(
            {
                "state": "accepted_start_receipt_and_claim_inputs_matched",
                "label": label,
                "operation_id": operation,
                "session_id": driver["session_id"],
                "native_session_id": driver["native_session_id"],
                "claim_operation_id": driver["claim_operation_id"],
            }
        )
        seen.add(label)
    return result


def _actor_public_startup(record: JsonObject, actor: str, native: str, project: str) -> None:
    if (
        record.get("session_id") != actor
        or record.get("native_session_id") != native
        or record.get("project_path") != project
        or record.get("active_agent") != "claude"
        or record.get("lifecycle_status") != "active"
        or record.get("runtime_start_observed") is not True
        or record.get("closed_at") is not None
    ):
        raise ValueError(ERROR_REPORT)


def _actor_hooks(values: JsonValue) -> JsonObject:
    if not isinstance(values, list) or len(values) != 2:
        raise ValueError(ERROR_REPORT)
    result: JsonObject = {}
    for value, name in zip(values, ("session_start", "prompt_submit"), strict=True):
        row = object_value(value)
        if set(row) != {"name", "frame"} or row["name"] != name:
            raise ValueError(ERROR_REPORT)
        result[name] = row["frame"]
    return result


def _actor_owner_inputs(packet: JsonObject, project: str, baseline: set[str]) -> JsonObject:
    values = packet["positive_start"]
    if not isinstance(values, list) or len(values) != 4:
        raise ValueError(ERROR_REPORT)
    rows = [object_value(value) for value in values]
    if (
        [row.get("kind") for row in rows] != ["launch", "session_start", "prompt_submit", "inputs"]
        or set(rows[0]) != {"kind", "value", "owned_executable"}
        or any(set(row) != {"kind", "value"} for row in rows[1:3])
        or set(rows[3]) != {"kind", "values"}
    ):
        raise ValueError(ERROR_REPORT)
    launch = object_value(rows[0]["value"])
    native = text(launch, "native_session_id")
    owned = text(rows[0], "owned_executable")
    if launch.get("executable") != owned or launch.get("resolved_command") != owned:
        raise ValueError(ERROR_REPORT)
    hooks: JsonObject = {"session_start": rows[1]["value"], "prompt_submit": rows[2]["value"]}
    _message_hooks({"hooks": hooks, "inputs": rows[3]["values"]}, native, text(packet, "message"))
    actor = text(packet, "session_id")
    record = object_value(packet["fact_record"])
    _actor_public_startup(record, actor, native, project)
    if record.get("principal") != text(packet, "expected_principal") or any(
        record.get(key) not in (None, "") for key in ("initiator_session_id", "role", "job")
    ):
        raise ValueError(ERROR_REPORT)
    lists = packet["lists"]
    if not isinstance(lists, list) or len(lists) != 1 or set(_early_session_list(lists[0])) - baseline != {actor}:
        raise ValueError(ERROR_REPORT)
    return launch


def _actor_start_answer(packet: JsonObject, name: str, actor: str, project: str, message: str | None) -> None:
    if name == "child":
        run = _pane_run(packet["start_frame"], ["telec", "todo", "child", ITEM])
        output, stderr = run.get("stdout"), run.get("stderr")
        if not isinstance(output, str) or not isinstance(stderr, str):
            raise ValueError(ERROR_REPORT)
        match = STARTED_CHILD.search(output + stderr)
        if match is None or match.group("session") != actor or match.group("procedure") != CHILD_PROCEDURE:
            raise ValueError(ERROR_REPORT)
        return
    if message is None:
        raise ValueError(ERROR_REPORT)
    argv = [
        "telec",
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
    if name in ("owner", "S_P"):
        result = _public_session_command(packet["start_command"], [creation.TELEC, *argv[1:]])
    else:
        run = _pane_run(packet["start_frame"], argv)
        stdout, stderr = run.get("stdout"), run.get("stderr")
        if not isinstance(stdout, str) or not isinstance(stderr, str):
            raise ValueError(ERROR_REPORT)
        result = foundation.json_object(stdout + stderr)
        if result is None:
            raise ValueError(ERROR_REPORT)
    if (
        result.get("session_id") != actor
        or (name != "X" and result.get("status") != "success")
        or (name in ("owner", "S_P") and result.get("agent") != "claude")
        or (name in ("owner", "S_P") and not result.get(foundation.FIELD_TMUX))
    ):
        raise ValueError(ERROR_REPORT)


def _other_actor_inputs(
    row: JsonObject, case: str, baseline: set[str], observed: set[str], launches: list[JsonValue], drivers: JsonObject
) -> JsonObject:
    expected = {"owner": 0, "child": 2, "dispatched": 3} if case == "B3" else {"S_P": 0, "X": 1, "child": 3}
    values = row["actors"]
    if not isinstance(values, list) or len(values) != len(expected):
        raise ValueError(ERROR_REPORT)
    result: JsonObject = {}
    raw_packets: dict[str, JsonObject] = {}
    native_ids = {text(object_value(value), "native_session_id") for value in drivers.values()}
    for value in values:
        packet = object_value(value)
        name, actor = text(packet, "name"), text(packet, "session_id")
        if (
            set(packet)
            != {
                "name",
                "slot",
                "started_ns",
                "finished_ns",
                "session_id",
                "message",
                "parent_actor",
                "expected_principal",
                "launch",
                "hooks",
                "inputs",
                "startup_record",
                "fact_record",
                "parent_record",
                "start_command",
                "start_frame",
                "positive_start",
                "lists",
            }
            or name not in expected
            or name in result
            or type(packet["slot"]) is not int
            or packet["slot"] != expected[name]
            or actor not in observed
            or not positive_integer(row, "started_ns")
            <= positive_integer(packet, "started_ns")
            <= positive_integer(packet, "finished_ns")
            <= positive_integer(row, "finished_ns")
        ):
            raise ValueError(ERROR_REPORT)
        project = text(row, "project_path")
        launch = _actor_owner_inputs(packet, project, baseline) if name == "owner" else object_value(packet["launch"])
        native, pid = text(launch, "native_session_id"), positive_integer(launch, "pid")
        fact = object_value(packet["fact_record"])
        if native in native_ids or fact.get("session_id") != actor or fact.get("native_session_id") != native:
            raise ValueError(ERROR_REPORT)
        native_ids.add(native)
        recorded = object_value(launches[expected[name]]).get("launches")
        if not isinstance(recorded, list) or not any(
            object_value(value).get("native_session_id") == native and object_value(value).get("pid") == pid
            for value in recorded
        ):
            raise ValueError(ERROR_REPORT)
        startup = object_value(packet["startup_record"]) if name != "owner" else fact
        if name != "owner":
            _actor_public_startup(startup, actor, native, project)
        message: str | None = None
        if name in ("S_P", "X"):
            message = B9_S_P_MESSAGE if name == "S_P" else B9_X_MESSAGE
            inputs = packet["inputs"]
            if packet["message"] != message or not isinstance(inputs, list) or not inputs:
                raise ValueError(ERROR_REPORT)
            first = text(object_value(inputs[0]), "text")
            if (
                (first != message if name == "S_P" else not caller_startup_body(first, message))
                or startup.get("role") is not None
                or startup.get("job") is not None
            ):
                raise ValueError(ERROR_REPORT)
            _message_hooks({"hooks": _actor_hooks(packet["hooks"]), "inputs": inputs}, native, first)
        elif name == "owner":
            message = text(packet, "message")
        elif name == "dispatched":
            message = DISPATCH_MESSAGE
            if packet["message"] != message:
                raise ValueError(ERROR_REPORT)
        _actor_start_answer(packet, name, actor, project, message)
        if name == "child":
            parent = text(object_value(drivers["first" if case == "B3" else "author"]), "session_id")
            if (
                packet["parent_actor"] != parent
                or fact.get("initiator_session_id") != parent
                or fact.get("role") != CHILD_ROLE
            ):
                raise ValueError(ERROR_REPORT)
        elif name == "S_P" and fact.get("initiator_session_id") not in (None, ""):
            raise ValueError(ERROR_REPORT)
        result[name] = {
            "state": "specific_actor_startup_inputs_matched",
            "session_id": actor,
            "native_session_id": native,
            "parent_actor": packet["parent_actor"],
            "role_projection": fact.get("role"),
            "job_projection": fact.get("job"),
            "causal_settlement": "unproven",
        }
        raw_packets[name] = packet
    if case == "B3":
        dispatched, owner = raw_packets["dispatched"], raw_packets["owner"]
        parent_record = object_value(dispatched["parent_record"])
        fact = object_value(dispatched["fact_record"])
        owner_id = text(owner, "session_id")
        if (
            dispatched["parent_actor"] != owner_id
            or parent_record.get("session_id") != owner_id
            or parent_record.get("native_session_id") != object_value(result["owner"])["native_session_id"]
            or fact.get("initiator_session_id") != owner_id
            or fact.get("principal") != parent_record.get("principal")
            or parent_record.get("principal") != object_value(owner["fact_record"]).get("principal")
        ):
            raise ValueError(ERROR_REPORT)
    else:
        x = raw_packets["X"]
        parent_id = text(raw_packets["S_P"], "session_id")
        if x["parent_actor"] != parent_id or object_value(x["fact_record"]).get("initiator_session_id") != parent_id:
            raise ValueError(ERROR_REPORT)
    return result


def validate_early_inputs(report: JsonObject) -> JsonObject:
    """Reparse original B3/B4 accounting inputs; listings/legacy labels/PIDs establish no physical closure or P2."""
    provisional = object_value(report["payload_provisional"])
    binding, observations = object_value(provisional["binding"]), object_value(provisional["observations"])
    selection = frozenset(_strings(binding[GuestKey.SELECTED_SCENARIOS]))
    expected = tuple(case for case in ("B3", "B4") if not selection or f"UC-WF-{case}" in selection)
    values = object_value(observations["early_workflow"])
    if set(values) != set(expected):
        raise ValueError(ERROR_REPORT)
    created = positive_integer(binding, "created_ns")
    public_finished = positive_integer(object_value(observations["inner_cleanup"]), "public_cleanup_finished_ns")
    root = text(observations, "owned_profile_root")
    result: JsonObject = {}
    for case in expected:
        row = object_value(values[case])
        if (
            set(row)
            != {
                "schema_version",
                "case",
                "project_path",
                "started_ns",
                "finished_ns",
                "baseline",
                "settlement",
                "cleanup_problems",
                "journey_error",
                "cleanup_error",
                "seal_error",
                "attempt_ledgers",
                "drivers",
                "start_calls",
                "actors",
                "ends",
                "closed_reads",
                "effects",
            }
            or type(row["schema_version"]) is not int
            or row["schema_version"] != 1
            or row["case"] != case
            or row["cleanup_problems"] != []
            or not isinstance(row["actors"], list)
            or not isinstance(row["ends"], list)
            or not isinstance(row["closed_reads"], list)
            or not isinstance(row["effects"], list)
            or any(row[key] is not None for key in ("journey_error", "cleanup_error", "seal_error"))
            or not created
            <= positive_integer(row, "started_ns")
            <= positive_integer(row, "finished_ns")
            <= public_finished
        ):
            raise ValueError(ERROR_REPORT)
        project = text(row, "project_path")
        if not project.startswith(root.rstrip("/") + "/"):
            raise ValueError(ERROR_REPORT)
        baseline = row["baseline"]
        settlement = object_value(row["settlement"])
        if (
            not isinstance(baseline, list)
            or len(baseline) != 1
            or set(settlement)
            != {"baseline_ids", "starts", "lists", "closures", "launches", "read_error", "problems", "legacy_proven"}
            or settlement["read_error"] is not None
            or settlement["problems"] != []
            or type(settlement["legacy_proven"]) is not bool
        ):
            raise ValueError(ERROR_REPORT)
        baseline_ids = set(_early_session_list(baseline[0]))
        if _identity_list(settlement["baseline_ids"]) != tuple(sorted(baseline_ids)):
            raise ValueError(ERROR_REPORT)
        lists = settlement["lists"]
        if not isinstance(lists, list) or len(lists) != 2:
            raise ValueError(ERROR_REPORT)
        before, after = _early_session_list(lists[0]), _early_session_list(lists[1])
        open_ids = {
            session
            for session, record in before.items()
            if session not in baseline_ids and record.get("closed_at") is None
        }
        closures = _early_closures(settlement["closures"], open_ids)
        if any(record.get("closed_at") is None for session, record in after.items() if session not in baseline_ids):
            raise ValueError(ERROR_REPORT)
        starts = object_value(settlement["starts"])
        if any(not key or value not in (START_CLAIMED, START_REFUSED) for key, value in starts.items()):
            raise ValueError(ERROR_REPORT)
        observed = (set(before) | set(after)) - baseline_ids
        launches = _early_launches(settlement["launches"], root, case)
        drivers = _early_driver_inputs(row, case, baseline_ids, observed, launches)
        other_actors = _other_actor_inputs(row, case, baseline_ids, observed, launches, drivers)
        ledger = _b4_ledger_inputs(row, root, case)
        result[case] = {
            "state": "captured_accounting_inputs_checked",
            "project_path": project,
            "observed_new_session_ids": list[JsonValue](sorted(observed)),
            "missing_after_session_ids": list[JsonValue](sorted(set(before) - set(after) - baseline_ids)),
            "public_end_inputs": closures,
            "recorded_start_states": starts,
            "launch_inputs": launches,
            "driver_inputs": drivers,
            "other_actor_inputs": other_actors,
            "explicit_end_inputs": _early_end_inputs(row, case, drivers, other_actors, ledger),
            "originating_start_inputs": _early_start_inputs(row, case, drivers, starts),
            "attempt_ledger_inputs": ledger,
            "semantic_settlement": "unproven",
            "creator_classification": "unproven",
            "physical_P4": "unproven",
        }
    return result


def validate_event_inputs(
    report: JsonObject, sessions: JsonObject, starts: JsonObject, early: JsonObject
) -> JsonObject:
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
        if early:
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
    early_links = _event_early_links(binding, records, early)
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
        "early_flow_links": early_links,
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
    object_value(observations["early_workflow"])
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


def _command_output(value: JsonValue, argv: list[str], *, successful: bool = True) -> str:
    command = object_value(value)
    duration = command.get("duration_seconds")
    if (
        set(command) != {"argv", "exit_status", "duration_seconds", "stdout", "stderr", "diagnostics"}
        or command["argv"] != argv
        or type(command["exit_status"]) is not int
        or (command["exit_status"] == 0) is not successful
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


def _claimed_holder(held: JsonObject, actor: str, phase: str, role: str = ROLE_WORK) -> None:
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
        or claims[-1].role != role
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
    changed_head = commit
    changed_count = count
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
        changed_head = temporary
        if row["actor"] is not None or row["write_frame"] is not None or temporary == commit:
            raise ValueError(ERROR_REPORT)
        _command_output(row["mutation_command"], ["git", "commit", "--allow-empty", "-m", B11_LOCAL_COMMIT_MESSAGE])
        for key in ("changed_reads", "pre_restore_reads"):
            found_count = _restoration_stage(row[key], project, worktree, commit, temporary, None, "local-head")
            if key == "changed_reads":
                changed_count = found_count
        _command_output(row["restore_command"], ["git", "reset", "--hard", commit])
        _restoration_stage(row["post_restore_reads"], project, worktree, commit, commit, count, "reset")
    return {
        "attempt_id": attempt.identifier,
        "label": attempt.label,
        "state": "owned_local_effect_restored",
        "commit": commit,
        "refusal_refs": [
            f"{commit}\trefs/heads/{ITEM}",
            changed_head,
            f"{changed_head} refs/heads/{ITEM}",
            changed_count,
        ],
    }


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


def _stamp_git(
    value: JsonValue, project: str, worktree: str, *, performer: bool = False, branch: bool = False
) -> tuple[str, ...]:
    reads, files = _restoration_reads(value, project, worktree)
    queries = [
        (project, "git", "ls-remote", "origin", f"refs/heads/{ITEM}"),
        (worktree, "git", "rev-parse", "HEAD"),
    ]
    if performer:
        queries.append((worktree, "git", "status", "--porcelain"))
    else:
        if branch:
            queries.append((worktree, "git", "show-ref", "--verify", f"refs/heads/{ITEM}"))
        queries.append((worktree, "git", "rev-list", "--count", f"origin/main..{ITEM}"))
    if files or set(reads) != set(queries) or any(len(reads[key]) != 1 for key in queries):
        raise ValueError(ERROR_REPORT)
    return tuple(reads[key][0].strip() for key in queries)


def _stamp_success(row: JsonObject, actor: str, commit: str, lane: str, builder: str) -> str:
    before = object_value(row["before_item"])
    _claimed_holder(before, actor, "work")
    values = row["after_items"]
    if not isinstance(values, list) or len(values) != 2 or row["before_git"] != [] or row["after_git"] != []:
        raise ValueError(ERROR_REPORT)
    items = [object_value(value) for value in values]
    # Preserve the original differing read order: ready then log at C2; log then ready at C3.
    first = row["closed_child"] is not None
    ready, logged = items if first else items[::-1]
    old_log = events.parse_log_entries(text(object_value(before["artifact_content"]), "log"))
    new_log = events.parse_log_entries(text(object_value(logged["artifact_content"]), "log"))
    if len(new_log) != len(old_log) + 1 or new_log[:-1] != old_log:
        raise ValueError(ERROR_REPORT)
    entry = new_log[-1]
    if (
        not entry.timestamp
        or entry.role != ROLE_WORK
        or entry.session != actor
        or entry.act != "stamp"
        or entry.bound != commit
        or entry.body != lane
    ):
        raise ValueError(ERROR_REPORT)
    standing = object_value(ready["standing"])
    state = object_value(ready["state"])
    if (
        standing.get("phase") != "ready"
        or standing.get("ready_at_commit") != commit
        or state.get("active_runner") not in (None, "")
    ):
        raise ValueError(ERROR_REPORT)
    if first:
        child = object_value(row["closed_child"])
        if "admitted" in standing or child.get("session_id") != builder or not _public_closed(child, builder):
            raise ValueError(ERROR_REPORT)
    return text(standing, "ready_since")


def _stamp_terminal(values: list[JsonValue], commit: str, successful: bool, needles: tuple[str, ...]) -> None:
    for value in values:
        terminal = object_value(value)
        if terminal["state"] != ("completed" if successful else "failed"):
            raise ValueError(ERROR_REPORT)
        if successful:
            if terminal.get("error") not in (None, "") or not text(terminal, "result").startswith(
                f"Stamped {ITEM} at {commit}"
            ):
                raise ValueError(ERROR_REPORT)
        elif any(needle not in text(terminal, "error") for needle in needles):
            raise ValueError(ERROR_REPORT)


def _stamp_inputs(
    finalizer: JsonObject,
    ledger: StartLedger,
    operations: dict[str, list[JsonValue]],
    claims: list[JsonValue],
    children: list[JsonValue],
    direct: list[JsonValue],
    restorations: list[JsonValue],
    created: int,
    public_finished: int,
) -> list[JsonValue]:
    labels = {
        "stamp-performer",
        "stamp-nonhead",
        "stamp-empty",
        "stamp-unclean",
        "stamp-worktree-head",
        "stamp-ok",
        "stamp-ok2",
    }
    values = finalizer["public_stamp_evidence"]
    if not isinstance(values, list):
        raise ValueError(ERROR_REPORT)
    if "B5" not in ledger.closed_lists:
        if values:
            raise ValueError(ERROR_REPORT)
        return []
    attempts = [attempt for attempt in ledger.attempts.values() if attempt.case == "B5" and attempt.label in labels]
    if (
        len(attempts) != len(labels)
        or {attempt.label for attempt in attempts} != labels
        or len(values) != len(labels)
        or len(children) != 1
    ):
        raise ValueError(ERROR_REPORT)
    packets: dict[str, JsonObject] = {}
    expected = {attempt.identifier: attempt for attempt in attempts}
    for value in values:
        row = object_value(value)
        identifier = text(row, "attempt_id")
        if (
            set(row)
            != {
                "attempt_id",
                "actor",
                "started_ns",
                "finished_ns",
                "frame",
                "before_item",
                "after_items",
                "before_git",
                "after_git",
                "closed_child",
            }
            or identifier not in expected
            or expected[identifier].label in packets
            or not created
            <= positive_integer(row, "started_ns")
            <= positive_integer(row, "finished_ns")
            <= public_finished
        ):
            raise ValueError(ERROR_REPORT)
        packets[expected[identifier].label] = row
    claim_rows = _labeled_inputs({"claims": claims}, "claims")
    direct_rows = _labeled_inputs({"direct": direct}, "direct")
    restored = _labeled_inputs({"restored": restorations}, "restored")
    child = object_value(children[0])
    builder = text(child, "session_id")
    project, worktree = text(child, "project_path"), text(child, "worktree")
    c1 = text(direct_rows["reviewed"], "bound")
    c2 = text(restored[B11_SENTINEL_LABEL], "commit")
    c3_argv = _strings(object_value(packets["stamp-ok2"]["frame"])["argv"])
    if len(c3_argv) != 8:
        raise ValueError(ERROR_REPORT)
    c3 = c3_argv[6]
    if not c3 or c3 == c2 or c2 == c1:
        raise ValueError(ERROR_REPORT)
    error_needles = {
        "stamp-performer": ("stamp requires the holding driver",),
        "stamp-nonhead": (c1, c2),
        "stamp-empty": ("lane report",),
        "stamp-unclean": (B11_DIRTY_REFUSAL,),
        "stamp-worktree-head": (
            f"stamp: the worktree branch head {_strings(restored[B11_LOCAL_HEAD_LABEL]['refusal_refs'])[1]} differs from {c2}",
        ),
    }
    result: list[JsonValue] = []
    for attempt in attempts:
        label = attempt.label
        row = packets[label]
        successful = label in ("stamp-ok", "stamp-ok2")
        actor = (
            builder
            if label == "stamp-performer"
            else text(claim_rows["w3-start" if label == "stamp-ok2" else "w2-start"], "actor")
        )
        commit = c1 if label in ("stamp-performer", "stamp-nonhead") else c3 if label == "stamp-ok2" else c2
        lane = LANE_TWO if label == "stamp-ok2" else LANE_ONE
        argv = ["telec", "todo", "act", ITEM, "stamp", "--sha", commit, *([] if label == "stamp-empty" else [lane])]
        if (
            attempt.kind != RECORD_TRIGGER
            or row["actor"] != actor
            or _pane_operation(row["frame"], argv) != attempt.operation_id
            or attempt.operation_id is None
        ):
            raise ValueError(ERROR_REPORT)
        _stamp_terminal(operations[attempt.operation_id], commit, successful, error_needles.get(label, ()))
        ready_since: str | None = None
        if successful:
            if (row["closed_child"] is not None) is not (label == "stamp-ok"):
                raise ValueError(ERROR_REPORT)
            ready_since = _stamp_success(row, actor, commit, lane, builder)
        else:
            before = object_value(row["before_item"])
            after = row["after_items"]
            count = {
                "stamp-performer": 1,
                "stamp-nonhead": 4,
                "stamp-empty": 2,
                "stamp-unclean": 1,
                "stamp-worktree-head": 1,
            }[label]
            if (
                not isinstance(after, list)
                or len(after) != count
                or any(value != before for value in after)
                or row["closed_child"] is not None
            ):
                raise ValueError(ERROR_REPORT)
            if label == "stamp-performer":
                if (
                    _stamp_git(row["before_git"], project, worktree, performer=True)
                    != (f"{c1}\trefs/heads/{ITEM}", c1, "")
                    or row["after_git"] != []
                ):
                    raise ValueError(ERROR_REPORT)
            elif label in ("stamp-nonhead", "stamp-empty"):
                refs = _stamp_git(row["before_git"], project, worktree)
                if (
                    refs[:2] != (f"{c2}\trefs/heads/{ITEM}", c2)
                    or _stamp_git(row["after_git"], project, worktree) != refs
                ):
                    raise ValueError(ERROR_REPORT)
            else:
                context = restored[B11_SENTINEL_LABEL if label == "stamp-unclean" else B11_LOCAL_HEAD_LABEL]
                if row["before_git"] != [] or _stamp_git(row["after_git"], project, worktree, branch=True) != _strings(
                    context["refusal_refs"]
                ):
                    raise ValueError(ERROR_REPORT)
        result.append(
            {
                "attempt_id": attempt.identifier,
                "label": label,
                "actor": actor,
                "commit": commit,
                "operation_id": attempt.operation_id,
                "native_outcome": "stamped" if successful else "refused",
                "ready_since": ready_since,
                "recorded_state": attempt.state,
            }
        )
    return result


def _integrator_identity(record: JsonObject, launch: JsonObject, project: str) -> tuple[str, str, int]:
    session = text(record, "session_id")
    native = text(record, "native_session_id")
    if (
        record.get("role") != ROLE_INTEGRATOR
        or record.get("job") != PROC_INTEGRATE
        or record.get("project_path") != project
        or launch.get("native_session_id") != native
        or launch.get("key_kind") != "procedure"
        or launch.get("key") != procedure_key(PROC_INTEGRATE)
    ):
        raise ValueError(ERROR_REPORT)
    return session, native, positive_integer(launch, "index")


def _integrator_inputs(finalizer: JsonObject, child: JsonObject, created: int, public_finished: int) -> JsonObject:
    value = finalizer["public_integrator_evidence"]
    row = object_value(value)
    if (
        set(row) != {"started_ns", "finished_ns", "baseline_ids", "excluded_ids", "startup", "inert_item"}
        or not created <= positive_integer(row, "started_ns") <= positive_integer(row, "finished_ns") <= public_finished
        or row["excluded_ids"] != [child["parent_actor"], child["session_id"]]
    ):
        raise ValueError(ERROR_REPORT)
    baseline = set(_identity_list(row["baseline_ids"]))
    excluded = set(_strings(row["excluded_ids"]))
    values = row["startup"]
    if not isinstance(values, list) or not values:
        raise ValueError(ERROR_REPORT)
    sessions: dict[str, JsonValue] = {}
    for value in values:
        packet = object_value(value)
        if set(packet) != {"session_id", "record", "launch", "control_launch"}:
            raise ValueError(ERROR_REPORT)
        record = object_value(packet["record"])
        session, native, index = _integrator_identity(
            record, object_value(packet["launch"]), text(child, "project_path")
        )
        if (
            packet["session_id"] != session
            or session in sessions
            or session in baseline
            or session in excluded
            or session not in _strings(finalizer["owned_session_ids"])
            or record.get("initiator_session_id") not in (None, "")
            or record.get("active_agent") != "claude"
            or record.get("lifecycle_status") != "active"
            or record.get("runtime_start_observed") is not True
            or record.get("closed_at") is not None
            or _integrator_identity(record, object_value(packet["control_launch"]), text(child, "project_path"))
            != (session, native, index)
        ):
            raise ValueError(ERROR_REPORT)
        sessions[session] = {"native_session_id": native, "index": index}
    item = object_value(row["inert_item"])
    standing = object_value(item["standing"])
    if (
        standing.get("phase") != "ready"
        or "admitted" in standing
        or object_value(item["state"]).get("lifecycle_phase") != "ready"
    ):
        raise ValueError(ERROR_REPORT)
    return {"state": "observed_inert_startups", "sessions": sessions}


def _integration_actor(row: JsonObject, project: str, integrators: JsonObject, owned: tuple[str, ...]) -> str:
    values = row["actor_candidates"]
    if not isinstance(values, list):
        raise ValueError(ERROR_REPORT)
    matches: list[str] = []
    seen: set[str] = set()
    prior = object_value(integrators["sessions"])
    for value in values:
        packet = object_value(value)
        if set(packet) != {"session_id", "record", "launch"}:
            raise ValueError(ERROR_REPORT)
        session, native, index = _integrator_identity(
            object_value(packet["record"]), object_value(packet["launch"]), project
        )
        if packet["session_id"] != session or session in seen:
            raise ValueError(ERROR_REPORT)
        if session in prior and object_value(prior[session]) != {"native_session_id": native, "index": index}:
            raise ValueError(ERROR_REPORT)
        seen.add(session)
        if index == 1:
            matches.append(session)
    actor = text(row, "actor")
    if matches != [actor] or actor not in owned:
        raise ValueError(ERROR_REPORT)
    return actor


def _delivered_inputs(row: JsonObject, project: str) -> JsonObject:
    base, main = text(row, "base"), text(row, "main_head")
    if main == base:
        raise ValueError(ERROR_REPORT)
    reads, files = _restoration_reads(row["delivery_git"], project, project)
    keys = {
        _git_read(reads, project, ("ls-remote", "origin", "refs/heads/main"), f"{main}\trefs/heads/main"),
        _git_read(reads, project, ("rev-parse", "main"), main),
        _git_read(reads, project, ("rev-parse", f"{main}^"), base),
        _git_read(reads, project, ("show", f"{main}:feature.txt"), EXPECTED_FEATURE.decode("utf-8"), raw=True),
        _git_read(reads, project, ("show", f"{main}:Makefile"), EXPECTED_MAKEFILE.decode("utf-8"), raw=True),
    }
    if files or set(reads) != keys or any(len(values) != 1 for values in reads.values()):
        raise ValueError(ERROR_REPORT)
    delivered = object_value(row["delivered_item"])
    roadmap = object_value(delivered["roadmap"])
    if (
        delivered.get("stage") != "delivered"
        or roadmap.get("status") != "delivered"
        or roadmap.get("delivered_commit") != main
    ):
        raise ValueError(ERROR_REPORT)
    text(roadmap, "delivered_at")
    listing = _public_session_command(row["listing"], ["telec", "todo", "list", "--json", "--include-delivered"])
    if (
        not isinstance(listing.get("delivered"), list)
        or ITEM not in collect_slugs(listing["delivered"])
        or ITEM in collect_slugs(listing.get("active"))
    ):
        raise ValueError(ERROR_REPORT)
    return {"state": "public_delivery_readback", "base": base, "main_head": main, "item": delivered}


def _integration_tree_inputs(row: JsonObject, project: str, actor: str) -> JsonObject:
    integration = f"{project}/{INTEGRATION_TREE}"
    base, head = text(row, "base"), text(row, "integrated_head")
    preflight, files = _restoration_reads(row["preflight_git"], project, integration)
    status_key = (project, "git", "status", "--porcelain")
    declaration_key = (project, "git", "show", "HEAD:teleclaude.yml")
    keys = {
        status_key,
        declaration_key,
        _git_read(preflight, project, ("rev-parse", "origin/main"), base),
        _git_read(preflight, project, ("ls-remote", "origin", "refs/heads/main"), f"{base}\trefs/heads/main"),
    }
    if (
        files
        or set(preflight) != keys
        or any(len(values) != 1 for values in preflight.values())
        or any(name in preflight[status_key][0] for name in (FEATURE_FILE, MAKE_FILE))
    ):
        raise ValueError(ERROR_REPORT)
    declarations = (
        preflight[declaration_key][0].strip(),
        text(row, "root_declaration"),
        text(row, "integration_declaration"),
    )
    if row["integration_is_dir"] is not True or any(
        not text_capability_enabled(value, "docs") or text_capability_enabled(value, "code") for value in declarations
    ):
        raise ValueError(ERROR_REPORT)
    staged, files = _restoration_reads(row["staged_git"], project, integration)
    status_key = (integration, "git", "status", "--porcelain")
    keys = {
        status_key,
        _git_read(staged, integration, ("rev-parse", "HEAD"), base),
        _git_read(staged, project, ("ls-remote", "origin", "refs/heads/main"), f"{base}\trefs/heads/main"),
    }
    if (
        files
        or set(staged) != keys
        or any(len(values) != 1 for values in staged.values())
        or any(f"A  {name}" not in staged[status_key][0] for name in (FEATURE_FILE, MAKE_FILE))
    ):
        raise ValueError(ERROR_REPORT)
    committed, files = _restoration_reads(row["commit_git"], project, integration)
    message_key = (integration, "git", "show", "-s", "--format=%B", "HEAD")
    keys = {
        message_key,
        _git_read(committed, integration, ("rev-parse", "HEAD"), head),
        _git_read(committed, integration, ("rev-parse", "HEAD^"), base),
        _git_read(committed, integration, ("show", "-s", "--format=%s", "HEAD"), B6_COMMIT),
        _git_read(
            committed, integration, ("show", f"{head}:{FEATURE_FILE}"), EXPECTED_FEATURE.decode("utf-8"), raw=True
        ),
        _git_read(committed, integration, ("show", f"{head}:{MAKE_FILE}"), EXPECTED_MAKEFILE.decode("utf-8"), raw=True),
    }
    if (
        head == base
        or files
        or set(committed) != keys
        or any(len(values) != 1 for values in committed.values())
        or f"Session: {actor}" not in committed[message_key][0]
    ):
        raise ValueError(ERROR_REPORT)
    unpublished, files = _restoration_reads(row["unpublished_git"], project, integration)
    key = _git_read(unpublished, project, ("ls-remote", "origin", "refs/heads/main"), f"{base}\trefs/heads/main")
    if files or set(unpublished) != {key} or len(unpublished[key]) != 1:
        raise ValueError(ERROR_REPORT)
    return {"state": "native_tree_and_commit_inputs_matched", "base": base, "integrated_head": head}


def _integration_retired_cleanup(row: JsonObject, project: str, public_finished: int) -> JsonObject:
    cleanup = object_value(row["retired_cleanup"])
    if (
        set(cleanup) != {"started_ns", "finished_ns", "command", "after_items", "git", "worktree_exists"}
        or not positive_integer(row, "finished_ns")
        <= positive_integer(cleanup, "started_ns")
        <= positive_integer(cleanup, "finished_ns")
        <= public_finished
        or cleanup["worktree_exists"] is not False
    ):
        raise ValueError(ERROR_REPORT)
    output = _command_output(cleanup["command"], ["telec", "todo", "stamp", ITEM, "--prd-approved"], successful=False)
    main = text(row, "main_head")
    if any(needle not in output for needle in ("delivered", "telec todo create", main[:12])):
        raise ValueError(ERROR_REPORT)
    items = cleanup["after_items"]
    if not isinstance(items, list) or len(items) != 2 or any(item != row["delivered_item"] for item in items):
        raise ValueError(ERROR_REPORT)
    reads, files = _restoration_reads(cleanup["git"], project, project)
    keys = {
        _git_read(reads, project, ("ls-remote", "origin", f"refs/heads/{ITEM}"), ""),
        _git_read(reads, project, ("branch", "--list", ITEM), ""),
    }
    if files or set(reads) != keys or any(len(values) != 1 for values in reads.values()):
        raise ValueError(ERROR_REPORT)
    return {"state": "retired_door_and_owned_item_cleanup_matched", "finished_ns": cleanup["finished_ns"]}


def _integration_inputs(
    finalizer: JsonObject,
    ledger: StartLedger,
    operations: dict[str, list[JsonValue]],
    child: JsonObject,
    integrators: JsonObject,
    stamps: list[JsonValue],
    created: int,
    public_finished: int,
) -> JsonObject:
    value = finalizer["public_integration_evidence"]
    if "B6" not in ledger.closed_lists:
        if value is not None:
            raise ValueError(ERROR_REPORT)
        return {"state": "not_selected"}
    row = object_value(value)
    if (
        set(row)
        != {
            "started_ns",
            "finished_ns",
            "actor",
            "actor_candidates",
            "operations",
            "before_item",
            "admitted_item",
            "base",
            "candidate",
            "frame",
            "integrated_head",
            "delivered_item",
            "main_head",
            "listing",
            "delivery_git",
            "preflight_git",
            "staged_git",
            "commit_git",
            "unpublished_git",
            "root_declaration",
            "integration_declaration",
            "integration_is_dir",
            "retired_cleanup",
        }
        or not created <= positive_integer(row, "started_ns") <= positive_integer(row, "finished_ns") <= public_finished
    ):
        raise ValueError(ERROR_REPORT)
    actor = _integration_actor(row, text(child, "project_path"), integrators, _strings(finalizer["owned_session_ids"]))
    stamp = _labeled_inputs({"stamps": stamps}, "stamps")["stamp-ok2"]
    candidate = text(row, "candidate")
    before = object_value(object_value(row["before_item"])["standing"])
    admitted = object_value(row["admitted_item"])
    standing, state = object_value(admitted["standing"]), object_value(admitted["state"])
    if (
        candidate != stamp["commit"]
        or before.get("phase") != "ready"
        or before.get("ready_at_commit") != candidate
        or object_value(standing["admitted"]).get("commit") != candidate
        or state.get("lifecycle_phase") != "ready"
        or state.get("active_runner") not in (None, "")
    ):
        raise ValueError(ERROR_REPORT)
    attempts = {
        attempt.identifier: attempt
        for attempt in ledger.attempts.values()
        if attempt.case == "B6" and attempt.label in ("int1", "int2")
    }
    frames = row["operations"]
    if len(attempts) != 2 or not isinstance(frames, list) or len(frames) != 2:
        raise ValueError(ERROR_REPORT)
    seen: set[str] = set()
    outcomes: list[JsonValue] = []
    for value in frames:
        packet = object_value(value)
        identifier = text(packet, "attempt_id")
        if (
            set(packet) != {"attempt_id", "actor", "frame"}
            or identifier in seen
            or identifier not in attempts
            or packet["actor"] != actor
        ):
            raise ValueError(ERROR_REPORT)
        attempt = attempts[identifier]
        if (
            attempt.kind != RECORD_TRIGGER
            or attempt.operation_id is None
            or _pane_operation(packet["frame"], ["telec", "todo", "integrate", ITEM]) != attempt.operation_id
        ):
            raise ValueError(ERROR_REPORT)
        for value in operations[attempt.operation_id]:
            terminal = object_value(value)
            if terminal.get("state") != "completed" or terminal.get("error") not in (None, ""):
                raise ValueError(ERROR_REPORT)
            text(terminal, "result")
        outcomes.append(
            {
                "label": attempt.label,
                "attempt_id": identifier,
                "operation_id": attempt.operation_id,
                "recorded_state": attempt.state,
            }
        )
        seen.add(identifier)
    _pane_run(row["frame"], ["telec", "code", "commit", "--approved", B6_COMMIT])
    return {
        "state": "admission_and_delivery_inputs",
        "actor": actor,
        "candidate": candidate,
        "operations": outcomes,
        "delivery": _delivered_inputs(row, text(child, "project_path")),
        "integration_tree_inputs": _integration_tree_inputs(row, text(child, "project_path"), actor),
        "retired_cleanup": _integration_retired_cleanup(row, text(child, "project_path"), public_finished),
    }


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
    direct = _direct_inputs(finalizer, after.ledger, claims, children, created, public_finished)
    restorations = _restoration_inputs(
        finalizer, after.ledger, children, created, public_finished, text(observations, "owned_profile_root")
    )
    stamps = _stamp_inputs(
        finalizer, after.ledger, operations, claims, children, direct, restorations, created, public_finished
    )
    integrators = _integrator_inputs(finalizer, object_value(children[0]), created, public_finished)
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
        "direct_acts": direct,
        "local_restoration": restorations,
        "stamps": stamps,
        "integrators": integrators,
        "integration": _integration_inputs(
            finalizer,
            after.ledger,
            operations,
            object_value(children[0]),
            integrators,
            stamps,
            created,
            public_finished,
        ),
        "semantic_settlement": "unproven",
    }
