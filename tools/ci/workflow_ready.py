"""Approved B7 held-ready recovery, message-keyed requests and reason freshness journey."""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Mapping
from typing import Final

from tools.ci import workflow_creation as creation
from tools.ci import workflow_driver as driver
from tools.ci import workflow_flow as flow_module
from tools.ci import workflow_foundation as foundation
from tools.ci import workflow_ledger as start_ledger
from tools.ci import workflow_publication as publication
from tools.ci.workflow_review import (
    FIELD_ADMITTED,
    FIELD_ERROR,
    FIELD_INITIATOR,
    FIELD_OPERATION,
    FIELD_READY_COMMIT,
    FIELD_RESULT,
    FIELD_ROLE,
    FIELD_STANDING_PHASE,
    FIELD_STATE,
    FRAME_SECONDS,
    OPERATION_SECONDS,
    ROLE_WORK,
    START_SECONDS,
    STATE_COMPLETED,
    STATE_FAILED,
    TELEC,
    TODO,
    _end,
    _fail,
    _frame_success,
    _run_command,
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
    journey = flow.journey("", message=message)
    journey.start_session(case_start_file=False)
    session = flow.map_message_actor(message, 1)
    flow.require_ledger().record_session(attempt, session)
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
    active = flow.journey(session)
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
    output = flow.observer.run(args)
    receipt = foundation.json_object(output.output)
    operation = receipt.get(FIELD_OPERATION) if receipt is not None else None
    if output.exit_status != 0 or not isinstance(operation, str) or not operation:
        flow.require_ledger().unknown(attempt)
        raise creation.binding_failure(f"{label} did not return its public operation receipt: {output.output[-300:]}")
    flow.require_ledger().record_operation(attempt, operation)
    result = publication.await_terminal(flow.observer, operation, OPERATION_SECONDS)
    error = result.get(FIELD_ERROR)
    if (
        result.get(FIELD_STATE) != STATE_FAILED
        or not isinstance(error, str)
        or any(needle not in error for needle in needles)
    ):
        _fail(f"{label} refusal did not name {needles!r}: {result!r}")
    if flow.item() != before or flow.observer.sessions().ids != sessions.ids or baseline.ids - sessions.ids:
        _fail(DETAIL_SNAPSHOT.format(where=label))
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
    flow: flow_module.WorkflowFlow, session: str, name: str, attempt_label: str
) -> Mapping[str, object]:
    attempt = flow.require_ledger().begin(flow_module.SFC_CHAIN_B7, attempt_label, start_ledger.RECORD_OPERATION)
    flow.gate(session, f"go_{'r1' if attempt_label == 'reasonone' else 'r2'}")
    frame = _frame_success(flow, session, name)
    raw_run = frame.get("run")
    run = raw_run if isinstance(raw_run, Mapping) else {}
    stdout = run.get("stdout")
    receipt = foundation.json_object(stdout) if isinstance(stdout, str) else None
    operation = receipt.get(FIELD_OPERATION) if receipt is not None else None
    if not isinstance(operation, str) or not operation:
        flow.require_ledger().unknown(attempt)
        raise creation.binding_failure(f"{attempt_label} returned no operation id")
    flow.require_ledger().record_operation(attempt, operation)
    return publication.await_terminal(flow.observer, operation, START_SECONDS)


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
    if not isinstance(log, str) or digest not in log or expected_text not in log or note not in log:
        _fail(DETAIL_NOTE.format(reasons=reasons))
    return note


def _owner_preflight(flow: flow_module.WorkflowFlow) -> creation.SessionView:
    manifest = flow.verify_manifest()
    if manifest.get("last_completed_case") != flow_module.SFC_CHAIN_B5:
        raise creation.binding_failure(DETAIL_MANIFEST)
    flow.begin_case(flow_module.SFC_CHAIN_B7, flow_module.B7_ACTIONS)
    item = flow.item()
    standing = item.get("standing")
    if not isinstance(standing, Mapping) or standing.get(FIELD_STANDING_PHASE) != flow_module.READY_PHASE:
        raise creation.binding_failure(DETAIL_MANIFEST)
    baseline = flow.observer.sessions()
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
    return flow.observer.sessions()


def _roleless_pair(
    flow: flow_module.WorkflowFlow, baseline: creation.SessionView
) -> tuple[str, str, creation.SessionView]:
    first = _start_roleless(flow, baseline, MSG_ONE, "session-S_R")
    second = _start_roleless(flow, baseline, MSG_TWO, "session-S2")
    if first == second:
        _fail("the two exact message keys mapped to one session")
    created = flow.observer.sessions().ids - baseline.ids
    if created != frozenset({first, second}):
        _fail(f"roleless message starts created an unexpected session set: {sorted(created)}")
    return first, second, flow.observer.sessions()


def _claim_held_ready(
    flow: flow_module.WorkflowFlow, first: str, baseline: creation.SessionView
) -> tuple[str, str, str, str, Mapping[str, object]]:
    outcome = _operation_call(flow, first, "reasonone", "reasonone")
    result = str(outcome.get(FIELD_RESULT, ""))
    if outcome.get(FIELD_STATE) != STATE_COMPLETED:
        _fail(
            DETAIL_REASON.format(operation="reasonone", state=outcome.get(FIELD_STATE), error=outcome.get(FIELD_ERROR))
        )
    w4 = flow.plan_actor(flow_module.PROC_WORK, 3, ROLE_WORK)
    note = _note(flow, first, REASON_ONE)
    named_note = re.search(r"recorded as note\s+(\S+)", result)
    if named_note is not None and named_note.group(1) != note:
        _fail(f"reason operation and public reason note differ: {result!r}, {note!r}")
    _startup(flow, w4, ROLE_WORK, flow_module.PROC_WORK)
    created = flow.observer.sessions().ids - baseline.ids
    if created != frozenset({w4}):
        _fail(f"reasonone created an unexpected session set: {sorted(created)}")
    record = flow.session_record(w4)
    if record.get(FIELD_ROLE) != ROLE_WORK:
        _fail(f"W4 has an unexpected role: {record!r}")
    item = flow.item()
    artifact = item.get("artifact_content")
    log = artifact.get("log") if isinstance(artifact, Mapping) else None
    known_claims = len(driver.claim_entries(log)) if isinstance(log, str) else 0
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
    )
    instruction = case.claim_call(())
    case.check_instruction(w4, instruction)
    case.observe_claim(w4, known_entries=known_claims)
    if "reason:" in instruction and (first not in instruction or REASON_ONE not in instruction):
        _fail("W4 instruction does not carry the first reason")
    if "child:" in instruction or "worktree" in instruction:
        _fail("held-ready W4 instruction unexpectedly dispatches a child or names a worktree")
    key = re.search(r"--key\s+([A-Za-z0-9_-]+)", instruction)
    if key is None:
        _fail(DETAIL_KEY.format(text=instruction[-500:]))
    attempt = next(identifier for identifier, row in flow.require_ledger().attempts.items() if row.label == "reasonone")
    flow.require_ledger().discharge(attempt, "W4 claim and the reason note were observed")
    no_key, output = _command_failure(flow, w4, "releasenokey")
    if FINDING_RELEASE not in output or "Performed release" in output:
        _fail(f"release without the instruction key did not refuse through the approved door: {no_key!r}")
    return w4, note, key.group(1), result, item


def _refresh_reason_and_release_key(
    flow: flow_module.WorkflowFlow, second: str, w4: str, first_note: str, first_key: str
) -> tuple[str, str]:
    outcome = _operation_call(flow, second, "reasontwo", "reasontwo")
    error = outcome.get(FIELD_ERROR)
    if (
        outcome.get(FIELD_STATE) != STATE_FAILED
        or not isinstance(error, str)
        or w4 not in error
        or "recorded as note" not in error
    ):
        _fail(f"the second reason did not name its holder: {outcome!r}")
    second_note = _note(flow, second, REASON_TWO)
    if second_note == first_note:
        _fail("the second reason reused the first note key")
    attempt = next(identifier for identifier, row in flow.require_ledger().attempts.items() if row.label == "reasontwo")
    flow.require_ledger().discharge(attempt, "public refusal recorded the second reason without creating a session")
    flow.late_argv(w4, "releasestale.argv", (TELEC, TODO, ACT, flow_module.ITEM, "release", "--key", first_key))
    flow.gate(w4, "go_stale")
    stale, stale_text = _command_failure(flow, w4, "releasestale")
    if FINDING_STALE not in stale_text or second_note not in stale_text:
        _fail(f"stale release did not name the new reason: {stale!r}")
    flow.gate(w4, "go_recall")
    _, fresh = _run_command(flow, w4, "recall")
    if fresh.get(FIELD_STATE) != STATE_COMPLETED:
        _fail(f"holder could not get the refreshed release instruction: {fresh!r}")
    text = str(fresh.get(FIELD_RESULT, ""))
    key = re.search(r"--key\s+([A-Za-z0-9_-]+)", text)
    if key is None or key.group(1) == first_key or REASON_ONE not in text or REASON_TWO not in text:
        _fail(f"fresh held-ready instruction omitted the changed reason set: {fresh!r}")
    return second_note, key.group(1)


def run_b7(flow: flow_module.WorkflowFlow) -> None:
    """Exercise held-ready refusal, two roleless reasons, stale key and fresh-key release."""
    try:
        baseline = _owner_preflight(flow)
        first, second, w4_baseline = _roleless_pair(flow, baseline)
        w4, first_note, first_key, result, initial = _claim_held_ready(flow, first, w4_baseline)
        second_note, fresh_key = _refresh_reason_and_release_key(flow, second, w4, first_note, first_key)
        created = flow.observer.sessions().ids - baseline.ids
        if created != frozenset({first, second, w4}):
            _fail(f"B7 reason and release operations changed the session set: {sorted(created)}")
        flow.late_argv(w4, "releaseok.argv", (TELEC, TODO, ACT, flow_module.ITEM, "release", "--key", fresh_key))
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
        initial_standing = initial.get("standing")
        if (
            not isinstance(released_standing, Mapping)
            or not isinstance(initial_standing, Mapping)
            or released_standing.get(FIELD_STANDING_PHASE) != flow_module.READY_PHASE
            or released_standing.get(FIELD_READY_COMMIT) != initial_standing.get(FIELD_READY_COMMIT)
            or released_standing.get(FIELD_ADMITTED) is not None
            or released_standing.get("held_by") is not None
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
        for session in (w4, first, second):
            _end(flow, session)
        for label in ("session-S_R", "session-S2"):
            attempt_id = next(
                identifier for identifier, attempt in flow.require_ledger().attempts.items() if attempt.label == label
            )
            flow.require_ledger().discharge(attempt_id, "public session end completed and retained record closed")
        flow.sessions.update({first: "roleless", second: "roleless", w4: ROLE_WORK})
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
                    "release_key": fresh_key,
                },
            )
        else:
            flow.finalize()
    except BaseException as error:
        flow.finalize(str(error))
        raise
