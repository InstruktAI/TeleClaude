"""Approved B7 held-ready recovery, message-keyed requests and reason freshness journey."""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Mapping
from typing import Final, cast

from tools.ci import acceptance_work as payload_work
from tools.ci import workflow_creation as creation
from tools.ci import workflow_driver as driver
from tools.ci import workflow_events
from tools.ci import workflow_flow as flow_module
from tools.ci import workflow_foundation as foundation
from tools.ci import workflow_items as items
from tools.ci import workflow_ledger as start_ledger
from tools.ci.workflow_review import (
    FIELD_ACTIVE,
    FIELD_ADMITTED,
    FIELD_ERROR,
    FIELD_INITIATOR,
    FIELD_OPERATION,
    FIELD_PHASE,
    FIELD_READY_COMMIT,
    FIELD_RESULT,
    FIELD_ROLE,
    FIELD_STANDING_PHASE,
    FIELD_STATE,
    FRAME_SECONDS,
    OPERATION_SECONDS,
    POLL_SECONDS,
    ROLE_INTEGRATOR,
    ROLE_WORK,
    START_SECONDS,
    STATE_COMPLETED,
    STATE_FAILED,
    TELEC,
    TODO,
    _end,
    _fail,
    _frame_success,
    _operation_command,
    _public_log,
    _startup,
)

ACT: Final = "act"
PREPARE: Final = "prepare"
WORK: Final = "work"
SESSIONS: Final = "sessions"
START: Final = "start"
PATH: Final = "--path"
AGENT: Final = "--agent"
MODE: Final = "--mode"
MESSAGE: Final = "--message"
CLAUDE: Final = "claude"
FAST: Final = "fast"
RUNNING_EARLIER_FIELD: Final = "standing.running_sessions_of_earlier_claims"
EARLIER_DOOR_FIELD: Final = "standing.door"
MSG_ONE: Final = "b7 session one"
MSG_TWO: Final = "b7 session two"
REASON_ONE: Final = "b7 reason one"
REASON_TWO: Final = "b7 reason two"
FINDING_DOOR: Final = "is ready, which"
FINDING_WORK: Final = "is ready: it is worked on only with a stated reason, from a session"
FINDING_RELEASE: Final = "a held ready item is released with the key of the instruction you received"
FINDING_STALE: Final = "a reason was noted after the instruction you hold"
DETAIL_MANIFEST: Final = "B7 did not receive the approved B5 handover"
DETAIL_ROLELESS: Final = "roleless session {session} did not match its exact message-key launch: {record!r}"
DETAIL_REASON: Final = "reason operation {operation} ended {state!r}: {error!r}"
DETAIL_SNAPSHOT: Final = "B7 refusal changed the item/session snapshot at {where}"
DETAIL_KEY: Final = "the held-ready instruction has no parseable release key: {text!r}"
DETAIL_NOTE: Final = "the public reason note is missing, duplicated or misattributed: {reasons!r}"


def _start_roleless(flow: flow_module.WorkflowFlow, baseline: creation.SessionView, message: str, label: str) -> str:
    attempt = flow.require_ledger().begin(flow_module.SFC_CHAIN_B7, label, start_ledger.RECORD_SESSION)
    launcher = foundation.Journey(flow.host, flow.setup, flow.project, flow.owner_email, message=message)
    launcher.start_session(case_start_file=False)
    session = launcher.session_id
    if not session:
        flow.require_ledger().unknown(attempt)
        raise creation.binding_failure(DETAIL_ROLELESS.format(session="unknown", record="start returned no public id"))
    flow.require_ledger().record_session(attempt, session)
    # Correlate only after the successful public start; slot and identity remain platform-owned.
    mapped = flow.map_message_actor(message, 1, timeout_seconds=START_SECONDS)
    if mapped != session:
        raise creation.binding_failure(DETAIL_ROLELESS.format(session=session, record={"message_key_session": mapped}))
    record = flow.session_record(session)
    _setup, launch = flow.control_for_session(session)
    native = record.get("native_session_id")
    if (
        session not in flow.observer.sessions().ids - baseline.ids
        or not isinstance(native, str)
        or launch.get("native_session_id") != native
        or launch.get("key_kind") != "message"
        or launch.get("key") != flow_module.message_key(message)
        or launch.get("index") != 1
        or launch.get("first_line") != message
        or record.get("role") is not None
        or record.get("job") is not None
        or record.get(FIELD_INITIATOR) is not None
    ):
        raise creation.binding_failure(DETAIL_ROLELESS.format(session=session, record=record))
    active = foundation.Journey(flow.host, _setup, flow.project, flow.owner_email, message=message)
    active.session_id = session
    deadline = time.monotonic() + START_SECONDS
    for hook in (foundation.FRAME_SESSION_START, foundation.FRAME_PROMPT_SUBMIT):
        active.require_hook(hook, active.await_frame(hook, deadline))
    if not active.started(record, native):
        _fail(DETAIL_ROLELESS.format(session=session, record=record))
    inputs = active.inputs()
    first = inputs[0].get("text") if inputs else None
    if first != message:
        _fail(DETAIL_ROLELESS.format(session=session, record=record))
    flow.record_session(session, "roleless")
    return session


def _owner_refusal(
    flow: flow_module.WorkflowFlow,
    label: str,
    args: tuple[str, ...],
    needles: tuple[str, ...],
    baseline: creation.SessionView,
) -> None:
    attempt = flow.require_ledger().begin(flow_module.SFC_CHAIN_B7, label, start_ledger.RECORD_OPERATION)
    before = flow.item()
    sessions = flow.observer.sessions()
    evidence = flow.refusal_input(attempt, before, sessions.ids, baseline.ids)
    output = flow.observer.run(args)
    evidence["command"] = flow.public_command_evidence(args, output)
    receipt = foundation.json_object(output.output)
    operation = receipt.get(FIELD_OPERATION) if receipt is not None else None
    if output.exit_status != 0 or not isinstance(operation, str) or not operation:
        flow.require_ledger().unknown(attempt)
        raise creation.binding_failure(f"{label} did not return its public operation receipt: {output.output[-300:]}")
    flow.require_ledger().record_operation(attempt, operation)
    result = flow.operation(operation, OPERATION_SECONDS)
    error = result.get(FIELD_ERROR)
    if (
        result.get(FIELD_STATE) != STATE_FAILED
        or not isinstance(error, str)
        or any(needle not in error for needle in needles)
    ):
        _fail(f"{label} refusal did not name {needles!r}: {result!r}")
    after = flow.item()
    observations: list[flow_module.JsonValue] = [
        {"observed_ns": time.monotonic_ns(), "item": cast(flow_module.JsonValue, dict(after))}
    ]
    evidence["after_items"] = observations
    if after != before or not baseline.ids.issubset(sessions.ids):
        _fail(DETAIL_SNAPSHOT.format(where=label))
    session_observations: list[flow_module.JsonValue] = []
    evidence["session_observations"] = session_observations
    _allow_integrator_delta(flow, baseline, label, evidence=session_observations)
    payload_work.sleep(5.0)
    after = flow.item()
    observations.append({"observed_ns": time.monotonic_ns(), "item": cast(flow_module.JsonValue, dict(after))})
    if after != before:
        _fail(DETAIL_SNAPSHOT.format(where=f"{label} stability window"))
    _allow_integrator_delta(flow, baseline, f"{label} stability window", evidence=session_observations)
    evidence["finished_ns"] = time.monotonic_ns()
    flow.require_ledger().discharge(attempt, "public refusal completed and item/session snapshots remained equal")


def _command_failure(flow: flow_module.WorkflowFlow, session: str, name: str) -> tuple[Mapping[str, object], str]:
    frame = flow.frame(session, f"cmd_{name}", FRAME_SECONDS)
    raw_run = frame.get("run")
    if (
        not isinstance(raw_run, Mapping)
        or not isinstance(raw_run.get("exit_status"), int)
        or raw_run.get("exit_status") == 0
    ):
        _fail(f"{name} unexpectedly succeeded or has an unreadable process outcome: {frame!r}")
    return frame, f"{raw_run.get('stdout', '')}{raw_run.get('stderr', '')}"


def _operation_call(
    flow: flow_module.WorkflowFlow, session: str, name: str, attempt_label: str, evidence: flow_module.MutableJson
) -> Mapping[str, object]:
    attempt = flow.require_ledger().begin(flow_module.SFC_CHAIN_B7, attempt_label, start_ledger.RECORD_OPERATION)
    evidence["attempt_id"] = attempt
    evidence["started_ns"] = time.monotonic_ns()
    flow.gate(session, f"go_{'r1' if attempt_label == 'reasonone' else 'r2'}")
    frame = _frame_success(flow, session, name)
    evidence["frame"] = cast(flow_module.JsonValue, dict(frame))
    raw_run = frame.get("run")
    run = raw_run if isinstance(raw_run, Mapping) else {}
    stdout = run.get("stdout")
    receipt = foundation.json_object(stdout) if isinstance(stdout, str) else None
    operation = receipt.get(FIELD_OPERATION) if receipt is not None else None
    if not isinstance(operation, str) or not operation:
        flow.require_ledger().unknown(attempt)
        raise creation.binding_failure(f"{attempt_label} returned no operation id")
    flow.require_ledger().record_operation(attempt, operation)
    terminal = flow.operation(operation, START_SECONDS)
    evidence["returned_ns"] = time.monotonic_ns()
    return terminal


def _note(flow: flow_module.WorkflowFlow, session: str, expected_text: str, expected_hash: str | None = None) -> str:
    item = flow.item()
    standing = item.get("standing")
    reasons = standing.get("reasons") if isinstance(standing, Mapping) else None
    if not isinstance(reasons, list):
        _fail(DETAIL_NOTE.format(reasons=reasons))
    matching = [
        row
        for row in reasons
        if isinstance(row, Mapping) and row.get("session") == session and row.get("text") == expected_text
    ]
    if len(matching) != 1 or not isinstance(matching[0].get("note"), str):
        _fail(DETAIL_NOTE.format(reasons=reasons))
    note = str(matching[0]["note"])
    if expected_hash is not None and hashlib.sha256(expected_text.encode("utf-8")).hexdigest()[:16] != expected_hash:
        _fail("reason key digest mismatch")
    content = item.get("artifact_content")
    log = content.get("log") if isinstance(content, Mapping) else None
    digest = hashlib.sha256(expected_text.encode("utf-8")).hexdigest()[:16]
    if not isinstance(log, str) or digest not in log or expected_text not in log:
        _fail(DETAIL_NOTE.format(reasons=reasons))
    return note


def _assert_no_write(
    flow: flow_module.WorkflowFlow,
    snapshot: Mapping[str, object],
    log_entries: list[tuple[str, str]],
    where: str,
) -> None:
    sessions = flow.observer.sessions()
    for label, pause in (("immediately", 0.0), ("five seconds later", 5.0)):
        if pause:
            payload_work.sleep(pause)
        current = flow.item()
        if current != snapshot or _public_log(current) != log_entries:
            _fail(f"B7 {where} wrote to the item {label}")
        sessions = _allow_integrator_delta(flow, sessions, f"{where} {label}")


def _allow_integrator_delta(
    flow: flow_module.WorkflowFlow,
    baseline: creation.SessionView,
    where: str,
    *,
    evidence: list[flow_module.JsonValue] | None = None,
) -> creation.SessionView:
    current = flow.observer.sessions()
    new_records: flow_module.MutableJson = {}
    if evidence is not None:
        evidence.append(
            {
                "baseline_ids": list[flow_module.JsonValue](sorted(baseline.ids)),
                "current_ids": list[flow_module.JsonValue](sorted(current.ids)),
                "new_session_records": new_records,
            }
        )
    if baseline.ids - current.ids:
        _fail(DETAIL_SNAPSHOT.format(where=f"{where}: a prior session disappeared"))
    for session in sorted(current.ids - baseline.ids):
        deadline = time.monotonic() + START_SECONDS
        record: Mapping[str, object] = {}
        while time.monotonic() < deadline:
            record = flow.session_record(session, retain=False)
            role = record.get(FIELD_ROLE)
            if role == ROLE_INTEGRATOR:
                break
            if role not in (None, ""):
                _fail(DETAIL_SNAPSHOT.format(where=f"{where}: unexpected new session {session}"))
            payload_work.sleep(POLL_SECONDS)
        if record.get(FIELD_ROLE) != ROLE_INTEGRATOR or record.get(FIELD_INITIATOR) not in (None, ""):
            _fail(DETAIL_SNAPSHOT.format(where=f"{where}: new session {session} did not classify as an integrator"))
        if evidence is not None:
            new_records[session] = cast(flow_module.JsonValue, dict(record))
        flow.record_session(session, ROLE_INTEGRATOR)
        flow.integrators.add(session)
    return current


def _owner_preflight(
    flow: flow_module.WorkflowFlow,
) -> tuple[creation.SessionView, Mapping[str, object], int, list[tuple[str, str]]]:
    manifest = flow.verify_manifest()
    if manifest.get("last_completed_case") != flow_module.SFC_CHAIN_B5:
        raise creation.binding_failure(DETAIL_MANIFEST)
    flow.begin_case(flow_module.SFC_CHAIN_B7, flow_module.B7_ACTIONS)
    item = driver.fresh_snapshot(flow.observer, flow_module.ITEM)
    standing = item.get("standing")
    if not isinstance(standing, Mapping) or standing.get(FIELD_STANDING_PHASE) != flow_module.READY_PHASE:
        raise creation.binding_failure(DETAIL_MANIFEST)
    baseline = flow.observer.sessions()
    artifact = item.get("artifact_content")
    log = artifact.get("log") if isinstance(artifact, Mapping) else None
    if not isinstance(log, str):
        raise creation.binding_failure("B7 preflight has no public artifact log")
    prior_claims = len(driver.claim_entries(log))
    _owner_refusal(
        flow,
        "ready-door",
        (TELEC, TODO, PREPARE, flow_module.ITEM),
        (FINDING_DOOR, f"{TELEC} todo work {flow_module.ITEM} --reason"),
        baseline,
    )
    _owner_refusal(flow, "ready-no-reason", (TELEC, TODO, WORK, flow_module.ITEM), (FINDING_WORK,), baseline)
    _owner_refusal(
        flow,
        "ready-no-session",
        (TELEC, TODO, WORK, flow_module.ITEM, "--reason", "b7 owner terminal"),
        (FINDING_WORK,),
        baseline,
    )
    if flow.item() != item:
        _fail("B7 owner-terminal refusals changed the preflight show snapshot")
    return baseline, item, prior_claims, _public_log(item)


def _actor_delta(
    flow: flow_module.WorkflowFlow, baseline: creation.SessionView, expected: set[str], where: str
) -> set[str]:
    """Require the scenario's non-integrator actors and retain any legitimate extra integrator session."""
    created = set(flow.observer.sessions(retain=False).ids - baseline.ids)
    other: set[str] = set()
    for session in created:
        record = flow.session_record(session, retain=False)
        if record.get(FIELD_ROLE) == ROLE_INTEGRATOR:
            flow.control_for_session(session)
            flow.record_session(session, ROLE_INTEGRATOR)
            flow.integrators.add(session)
        else:
            other.add(session)
    if other != expected:
        _fail(f"{where} non-integrator sessions are {sorted(other)!r}, expected {sorted(expected)!r}")
    return created


def _roleless_pair(
    flow: flow_module.WorkflowFlow, baseline: creation.SessionView
) -> tuple[str, str, creation.SessionView]:
    first = _start_roleless(flow, baseline, MSG_ONE, "session-S_R")
    second = _start_roleless(flow, baseline, MSG_TWO, "session-S2")
    if first == second:
        _fail("the two exact message keys mapped to one session")
    _actor_delta(flow, baseline, {first, second}, "B7 roleless starts")
    return first, second, baseline


def _claim_held_ready(
    flow: flow_module.WorkflowFlow,
    first: str,
    second: str,
    baseline: creation.SessionView,
    known_claims: int,
    pre_log: list[tuple[str, str]],
    *,
    before_item: Mapping[str, object],
) -> tuple[str, str, str, str, str, Mapping[str, object]]:
    evidence = flow.reason_input(first, before_item, pre_log)
    outcome = _operation_call(flow, first, "reasonone", "reasonone", evidence)
    result = str(outcome.get(FIELD_RESULT, ""))
    if outcome.get(FIELD_STATE) != STATE_COMPLETED:
        _fail(
            DETAIL_REASON.format(operation="reasonone", state=outcome.get(FIELD_STATE), error=outcome.get(FIELD_ERROR))
        )
    w4 = flow.plan_actor(flow_module.PROC_WORK, 3, ROLE_WORK)
    note = _note(flow, first, REASON_ONE)
    named_note = re.search(r"recorded as note\s+(\S+)", result)
    if "has not claimed yet" in result:
        reasonone_credit = "pending result; session and note clauses not evaluated"
    elif f"session {w4} holds the claim" in result and named_note is not None and named_note.group(1) == note:
        reasonone_credit = "result names the mapped W4 session and public note"
    else:
        _fail(f"reasonone returned neither the approved pending nor claimed outcome: {result!r}")
    _startup_record, startup_launch, _startup_role = _startup(flow, w4, ROLE_WORK, flow_module.PROC_WORK)
    _actor_delta(flow, baseline, {first, second, w4}, "B7 reasonone")
    record = flow.session_record(w4)
    if record.get(FIELD_ROLE) != ROLE_WORK or record.get("title") != f"{ROLE_WORK} {flow_module.ITEM}":
        _fail(f"W4 has an unexpected role: {record!r}")
    attempt = next(identifier for identifier, row in flow.require_ledger().attempts.items() if row.label == "reasonone")
    case = driver.DriverCase(
        host=flow.host,
        observer=flow.observer,
        journey=flow.journey(w4),
        item=flow_module.ITEM,
        launch_setup=flow.setup_for_session(w4),
        clone=flow.publication.clone,
        baseline=baseline,
        driver_id=flow_module.PROC_WORK,
        verb=WORK,
        phase=flow_module.READY_PHASE,
        claim_evidence=flow.claim_input(attempt, w4, flow_module.READY_PHASE, record, startup_launch),
    )
    instruction = case.claim_call(())
    case.observe_claim(w4, known_entries=known_claims)
    for needle in (flow_module.ITEM, flow_module.READY_PHASE, w4, first, REASON_ONE):
        if needle not in instruction:
            _fail(f"held-ready instruction omits {needle!r}: {instruction[-500:]!r}")
    if "child:" in instruction or "worktree" in instruction:
        _fail("held-ready instruction unexpectedly includes child or worktree text")
    act_rows = [match for match in map(driver.ACT_ROW.match, instruction.splitlines()) if match is not None]
    targets = {(row.group("act"), row.group("target")) for row in act_rows}
    if targets != {("kickback", "preparation"), ("release", "ready")}:
        _fail(f"held-ready instruction ending act rows are {targets!r}")
    key = re.search(r"Instruction key\s+([A-Za-z0-9_-]+):", instruction)
    if key is None:
        _fail(DETAIL_KEY.format(text=instruction[-500:]))
    flow.require_ledger().discharge(attempt, "W4 claim and the reason note were observed")
    initial = flow.item()
    evidence["after_item"] = cast(flow_module.JsonValue, dict(initial))
    evidence["observed_ns"] = time.monotonic_ns()
    initial_log = _public_log(initial)
    added_log = initial_log[len(pre_log) :]
    first_digest = hashlib.sha256(REASON_ONE.encode("utf-8")).hexdigest()[:16]
    if (
        len(added_log) != 2
        or first_digest not in added_log[0][0]
        or first not in added_log[0][0]
        or "note" not in added_log[0][0]
        or REASON_ONE not in added_log[0][1]
        or w4 not in added_log[1][0]
        or "claim" not in added_log[1][0]
        or flow_module.ITEM not in added_log[1][1]
    ):
        _fail(f"B7 reason and W4 claim log delta does not match the public actor evidence: {added_log!r}")
    standing = initial.get("standing")
    state = initial.get("state")
    reasons = standing.get("reasons") if isinstance(standing, Mapping) else None
    if (
        not isinstance(standing, Mapping)
        or not isinstance(state, Mapping)
        or standing.get(FIELD_STANDING_PHASE) != flow_module.READY_PHASE
        or state.get(FIELD_PHASE) != flow_module.READY_PHASE
        or standing.get(FIELD_READY_COMMIT) is None
        or not standing.get("ready_since")
        or standing.get("held_by") != w4
        or not standing.get("held_since")
        or FIELD_ADMITTED in standing
        or not isinstance(reasons, list)
        or len(reasons) != 1
        or not isinstance(reasons[0], Mapping)
        or reasons[0].get("note") != note
        or reasons[0].get("session") != first
        or reasons[0].get("text") != REASON_ONE
    ):
        _fail(f"W4 did not retain the stamped ready state and first reason: {initial!r}")
    no_key_before = flow.item()
    no_key_entries = _public_log(no_key_before)
    flow.gate(w4, "go_nokey")
    no_key, output = _command_failure(flow, w4, "releasenokey")
    if FINDING_RELEASE not in output or "Performed release" in output:
        _fail(f"release without the instruction key did not refuse through the approved door: {no_key!r}")
    _assert_no_write(flow, no_key_before, no_key_entries, "release without instruction")
    return w4, note, key.group(1), result, reasonone_credit, initial


def _refresh_reason_and_release_key(
    flow: flow_module.WorkflowFlow,
    first: str,
    second: str,
    w4: str,
    first_note: str,
    first_key: str,
    baseline: creation.SessionView,
) -> tuple[str, str]:
    before = flow.item()
    before_standing = before.get("standing")
    before_ready_since = before_standing.get("ready_since") if isinstance(before_standing, Mapping) else None
    before_log = _public_log(before)
    evidence = flow.reason_input(second, before, before_log)
    outcome = _operation_call(flow, second, "reasontwo", "reasontwo", evidence)
    error = outcome.get(FIELD_ERROR)
    if (
        outcome.get(FIELD_STATE) != STATE_FAILED
        or not isinstance(error, str)
        or w4 not in error
        or "recorded as note" not in error
    ):
        _fail(f"the second reason did not name its holder: {outcome!r}")
    second_note = _note(flow, second, REASON_TWO)
    named_note = re.search(r"recorded as note\s+(\S+)", error)
    if named_note is None or named_note.group(1) != second_note:
        _fail(f"reasontwo error and public note differ: {error!r}, {second_note!r}")
    if second_note == first_note:
        _fail("the second reason reused the first note key")
    after = flow.item()
    evidence["after_item"] = cast(flow_module.JsonValue, dict(after))
    evidence["observed_ns"] = time.monotonic_ns()
    standing = after.get("standing")
    reasons = standing.get("reasons") if isinstance(standing, Mapping) else None
    if (
        not isinstance(standing, Mapping)
        or standing.get("held_by") != w4
        or standing.get(FIELD_STANDING_PHASE) != flow_module.READY_PHASE
        or standing.get("ready_since") != before_ready_since
        or not isinstance(reasons, list)
        or len(reasons) != 2
        or not isinstance(reasons[0], Mapping)
        or not isinstance(reasons[1], Mapping)
        or reasons[0].get("note") != first_note
        or reasons[0].get("session") != first
        or reasons[0].get("text") != REASON_ONE
        or reasons[1].get("note") != second_note
        or reasons[1].get("session") != second
        or reasons[1].get("text") != REASON_TWO
    ):
        _fail(DETAIL_NOTE.format(reasons=reasons))
    log_delta = _public_log(after)[len(before_log) :]
    digest = hashlib.sha256(REASON_TWO.encode("utf-8")).hexdigest()[:16]
    if (
        len(log_delta) != 1
        or digest not in log_delta[0][0]
        or second not in log_delta[0][0]
        or REASON_TWO not in log_delta[0][1]
    ):
        _fail(f"reasontwo log delta is not one attributed digest entry: {log_delta!r}")
    attempt = next(identifier for identifier, row in flow.require_ledger().attempts.items() if row.label == "reasontwo")
    flow.require_ledger().discharge(attempt, "public refusal recorded the second reason without creating a session")
    stale_before = flow.item()
    stale_log = _public_log(stale_before)
    flow.late_argv(w4, "releasestale.argv", (TELEC, TODO, ACT, flow_module.ITEM, "release", "--instruction", first_key))
    flow.gate(w4, "go_stale")
    stale, stale_text = _command_failure(flow, w4, "releasestale")
    if FINDING_STALE not in stale_text or second_note not in stale_text:
        _fail(f"stale release did not name the new reason: {stale!r}")
    _assert_no_write(flow, stale_before, stale_log, "stale release instruction")
    _actor_delta(flow, baseline, {first, second, w4}, "B7 second reason and stale release")
    flow.gate(w4, "go_recall")
    _, fresh = _operation_command(flow, w4, "recall")
    if fresh.get(FIELD_STATE) != STATE_COMPLETED:
        _fail(f"holder could not get the refreshed release instruction: {fresh!r}")
    text = str(fresh.get(FIELD_RESULT, ""))
    key = re.search(r"Instruction key\s+([A-Za-z0-9_-]+):", text)
    if key is None or key.group(1) == first_key or REASON_ONE not in text or REASON_TWO not in text:
        _fail(f"fresh held-ready instruction omitted the changed reason set: {fresh!r}")
    return second_note, key.group(1)


def run_b7(flow: flow_module.WorkflowFlow) -> None:
    """Exercise held-ready refusal, two roleless reasons, stale key and fresh-key release."""
    try:
        if flow.event_window is None or flow.event_case_seal is None:
            raise creation.binding_failure(DETAIL_MANIFEST)
        workflow_events.verify_case(flow.event_window, "B5", flow.event_case_seal)
        baseline, s_pre, k_pre, pre_log = _owner_preflight(flow)
        first, second, _w4_baseline = _roleless_pair(flow, baseline)
        w4, first_note, first_key, result, reasonone_credit, initial = _claim_held_ready(
            flow, first, second, baseline, k_pre, pre_log, before_item=s_pre
        )
        second_note, fresh_key = _refresh_reason_and_release_key(
            flow, first, second, w4, first_note, first_key, baseline
        )
        flow.late_argv(
            w4,
            "releaseok.argv",
            (TELEC, TODO, ACT, flow_module.ITEM, "release", "--instruction", fresh_key),
        )
        flow.gate(w4, "go_ok")
        release = _frame_success(flow, w4, "releaseok")
        run = release.get("run")
        if (
            not isinstance(run, Mapping)
            or run.get("exit_status") != 0
            or "Performed release" not in str(run.get("stdout", ""))
        ):
            _fail(f"fresh held-ready release did not complete: {release!r}")
        released = flow.item()
        released_standing = released.get("standing")
        released_state = released.get("state")
        initial_standing = initial.get("standing")
        if (
            not isinstance(released_standing, Mapping)
            or not isinstance(initial_standing, Mapping)
            or released_standing.get(FIELD_STANDING_PHASE) != flow_module.READY_PHASE
            or released_standing.get(FIELD_READY_COMMIT) != initial_standing.get(FIELD_READY_COMMIT)
            or released_standing.get("ready_since") != initial_standing.get("ready_since")
            or released_standing.get(FIELD_ADMITTED) is not None
            or released_standing.get("held_by") is not None
            or not isinstance(released_state, Mapping)
            or released_state.get(FIELD_ACTIVE) not in (None, "")
            or released_state.get(FIELD_PHASE) != flow_module.READY_PHASE
        ):
            _fail(f"release did not preserve ready state: {released!r}")
        reasons = released_standing.get("reasons")
        if not isinstance(reasons, list) or len(reasons) != 2 or not all(isinstance(row, Mapping) for row in reasons):
            _fail(DETAIL_NOTE.format(reasons=reasons))
        first_reason, second_reason = reasons
        if (
            first_reason.get("note") != first_note
            or first_reason.get("session") != first
            or first_reason.get("text") != REASON_ONE
            or second_reason.get("note") != second_note
            or second_reason.get("session") != second
            or second_reason.get("text") != REASON_TWO
        ):
            _fail(DETAIL_NOTE.format(reasons=reasons))
        actors = {w4, first, second}
        _actor_delta(flow, baseline, actors, "B7 before session ends")
        for session in (w4, first, second):
            _end(flow, session)
        for label in ("session-S_R", "session-S2"):
            attempt_id = next(
                identifier for identifier, attempt in flow.require_ledger().attempts.items() if attempt.label == label
            )
            flow.require_ledger().discharge(attempt_id, "public session end completed and retained record closed")
        flow.sessions.update({first: "roleless", second: "roleless", w4: ROLE_WORK})
        deadline = time.monotonic() + 60.0
        final_item = flow.item()
        while time.monotonic() < deadline:
            final_item = flow.item()
            running_found, running = creation.dig(final_item, RUNNING_EARLIER_FIELD)
            door_found, door = creation.dig(final_item, EARLIER_DOOR_FIELD)
            if running_found and not isinstance(running, list):
                _fail(f"B7 earlier-session field is malformed: {final_item!r}")
            if not running_found or not running:
                if door_found and door not in (None, ""):
                    _fail(f"B7 earlier-session door remains after all sessions ended: {final_item!r}")
                break
            payload_work.sleep(POLL_SECONDS)
        else:
            _fail(f"B7 session ends did not clear earlier sessions or the door: {final_item!r}")
        final_item = flow.item()
        items.require_only_changes(
            "B7 final item after actor closure",
            s_pre,
            final_item,
            ("artifact_content.log", "artifact_state.log", "standing.reasons", "roadmap.updated_at", "events"),
        )
        _actor_delta(flow, baseline, actors, "B7 final actor set")
        flow.event_case_seal = workflow_events.append_case(
            flow.event_window,
            "B7",
            {
                "first": first,
                "second": second,
                "w4": w4,
                "reason_one_note": first_note,
                "reason_two_note": second_note,
                "reason_one": REASON_ONE,
                "reason_two": REASON_TWO,
                "release_key": fresh_key,
                "initial_ready": initial,
                "released": released,
                "final_state": final_item,
            },
            previous_case="B5",
            expected_previous_seal=flow.event_case_seal,
        )
        if flow_module.SFC_CHAIN_B6 in flow.chain:
            flow.handover(
                flow_module.SFC_CHAIN_B7,
                flow_module.SFC_CHAIN_B6,
                {
                    "S_R": first,
                    "S2": second,
                    "W4": w4,
                    "reason_one_note": first_note,
                    "reason_two_note": second_note,
                    "reasonone_result": result,
                    "reasonone_result_credit": reasonone_credit,
                    "release_key": fresh_key,
                },
            )
        else:
            flow.finalize()
    except BaseException as error:
        flow.finalize(str(error))
        raise
