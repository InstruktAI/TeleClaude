"""Approved B5 black-box workflow journey on the shared B5/B7/B6 flow."""

from __future__ import annotations

import base64
import hashlib
import re
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, NoReturn, cast

from tools.ci import workflow_creation as creation
from tools.ci import workflow_driver as driver
from tools.ci import workflow_events
from tools.ci import workflow_flow as flow_module
from tools.ci import workflow_foundation as foundation
from tools.ci import workflow_ledger as start_ledger
from tools.ci import workflow_waiting as waiting

TELEC: Final = "telec"
TODO: Final = "todo"
WORK: Final = "work"
ACT: Final = "act"
SHOW: Final = "show"
OPERATIONS: Final = "operations"
GET: Final = "get"
FIELD_OPERATION: Final = "operation_id"
FIELD_JOB: Final = "job"
FIELD_COMMAND: Final = "command"
FIELD_STATE: Final = "state"
FIELD_RESULT: Final = "result"
FIELD_ERROR: Final = "error"
FIELD_ROLE: Final = "role"
FIELD_NATIVE: Final = "native_session_id"
FIELD_INITIATOR: Final = "initiator_session_id"
FIELD_PROJECT: Final = "project_path"
FIELD_SUBDIR: Final = "subdir"
FIELD_ACTIVE: Final = "active_runner"
FIELD_PHASE: Final = "lifecycle_phase"
FIELD_STANDING_PHASE: Final = "phase"
FIELD_READY_COMMIT: Final = "ready_at_commit"
FIELD_ADMITTED: Final = "admitted"
FIELD_LOG: Final = "log"
STATE_COMPLETED: Final = "completed"
STATE_FAILED: Final = "failed"
ROLE_WORK: Final = "work-orchestrator"
ROLE_BUILDER: Final = "builder"
ROLE_INTEGRATOR: Final = "integrator"
PROC_WORK: Final = flow_module.PROC_WORK
PROC_BUILD: Final = flow_module.PROC_BUILD
LANE_ONE: Final = (
    "synthetic fixture lane report 1 of 2: recorded by the acceptance fixture; the constant-true native target exited 0; "
    "no application test suite ran; no specification approval is claimed"
)
LANE_TWO: Final = (
    "synthetic fixture lane report 2 of 2: recorded by the acceptance fixture after the head moved; "
    "the constant-true native target exited 0; no application test suite ran; no specification approval is claimed"
)
FINDING_TEXT: Final = "Important: the feature file lacks a trailing note"
REPLY_TEXT: Final = "fixed in the next commit"
ACT_REVIEWED: Final = "reviewed"
ACT_FINDING: Final = "finding"
ACT_REPLY: Final = "reply"
POLL_SECONDS: Final = 2.0
START_SECONDS: Final = 900.0
OPERATION_SECONDS: Final = 300.0
FRAME_SECONDS: Final = 60.0
DETAIL_BINDING: Final = "B5 evidence did not bind to the shared flow: {detail}"
DETAIL_FOLDED_ROLE: Final = "session {session} role {actual!r} does not match folded role {folded!r}"
DETAIL_STARTUP_RECORD: Final = "session {session} startup record contradicts {predicate}: {record!r}"
DETAIL_STARTUP_TIMEOUT: Final = "session {session} never showed a fresh positive startup record: {record!r}"
DETAIL_PLATFORM: Final = "B5 platform assertion failed: {detail}"
DETAIL_FRAME: Final = "fixture command {name} did not succeed: {frame!r}"
DETAIL_STATE: Final = "operation {operation} ended in {state!r}: {detail!r}"
DETAIL_KEY: Final = "finding returned no key: {result!r}"
B14_RESERVATION_KEY: Final = re.compile(r"\(reservation (?P<key>[^\s)]+)\)")
B14_RESERVATION_MISSING: Final = "B14 startup requires one unique nonempty native reservation key"
DETAIL_LEDGER: Final = "B5 ledger declaration failed: {detail}"
DETAIL_PRECONDITION: Final = "B5 began outside the approved unclaimed work state: {item!r}"
DETAIL_WRITE_SCOPE: Final = (
    "builder {session} write-scope mismatch: expected base {base!r}, subdir {subdir!r}, effective {effective!r}, "
    "owned worktree {owned!r}; "
    "public project_path {project!r}, public subdir {actual_subdir!r}, effective {actual_effective!r}, "
    "launch cwd {cwd!r}, public native {native!r}, launch native {launch_native!r}"
)
DETAIL_WRITE_FRAME_SCOPE: Final = "builder write frame cwd {cwd!r} does not name worktree {worktree}; frame {frame!r}"
B5_BUILDER_SUBDIR: Final = f"{flow_module.WORKTREE_DIRECTORY}/{flow_module.ITEM}"
DETAIL_INTEGRATOR: Final = "no started integrator has a public session record and mapped native control"
B11_SENTINEL_BYTES: Final = b"b11 dirty sentinel\n"
B11_SENTINEL_LINE: Final = "b11 dirty sentinel"
B11_BASE_FEATURE_BYTES: Final = b"b5 file one\nb5 file two\n"
B11_STATUS_MODIFIED: Final = " M feature.txt"
B11_STATUS_MODIFIED_BYTES: Final = b" M feature.txt\n"
B11_NUMSTAT: Final = "1\t0\tfeature.txt"
B11_DIRTY_REFUSAL: Final = "stamp: the worktree has uncommitted changes"
B11_LOCAL_COMMIT_MESSAGE: Final = flow_module.B11_LOCAL_HEAD_MESSAGE
B11_STAMP_UNCLEAN: Final = "stampunclean"
B11_STAMP_WORKTREE: Final = "stampworktree"
B11_SENTINEL_LABEL: Final = "dirty-sentinel"
B11_LOCAL_HEAD_LABEL: Final = "temporary-local-head"
B11_TRIGGER_UNCLEAN: Final = "stamp-unclean"
B11_TRIGGER_WORKTREE: Final = "stamp-worktree-head"
DIRECT_REFUSAL_ERRORS: Final = {
    "reviewed-wrong": "Error: 409 — reviewed requires the holding driver",
    "finding-wrong": "Error: 409 — finding requires the holding driver",
    "reply-wrong": "Error: 409 — reply requires a builder in the holder's claiming group",
    "kickback-wrong": "Error: 409 — kickback requires the holding driver",
    "release-wrong": "Error: 409 — release requires the holder, or the platform on session end",
}
WRONG_PERFORMER_TEXT: Final = "B9 wrong performer"
B11_UNCLEAN_ARGV: Final = "stampunclean.argv"
B11_WORKTREE_ARGV: Final = "stampworktree.argv"
B11_CLI_NAME: Final = "telec"
B11_STAMP_VERB: Final = "stamp"
B11_FEATURE_PATH: Final = "feature.txt"
B11_PAYLOAD_PATH: Final = "path"
B11_PAYLOAD_MODE: Final = "mode"
B11_PAYLOAD_BYTES: Final = "bytes"
B11_PAYLOAD_SHA: Final = "sha256"
B11_FRAME_WRITES: Final = "writes"
B11_EXPECTED_APPEND_COUNT: Final = 19


def _fail(detail: str) -> NoReturn:
    raise creation.platform_failure(detail)


def _operation(
    flow: flow_module.WorkflowFlow, frame: Mapping[str, object], name: str
) -> tuple[str, Mapping[str, object]]:
    run = frame.get("run")
    stdout = run.get("stdout") if isinstance(run, Mapping) else None
    receipt = foundation.json_object(stdout) if isinstance(stdout, str) else None
    identifier = receipt.get(FIELD_OPERATION) if receipt is not None else None
    if not isinstance(identifier, str) or not identifier:
        _fail(DETAIL_FRAME.format(name=name, frame=frame))
    state = flow.operation(identifier, OPERATION_SECONDS)
    return identifier, state


def _frame_success(
    flow: flow_module.WorkflowFlow,
    session: str,
    name: str,
    *,
    writes: bool = False,
    evidence: flow_module.MutableJson | None = None,
) -> Mapping[str, object]:
    frame = flow.frame(session, f"cmd_{name}", FRAME_SECONDS)
    if evidence is not None:
        evidence["frame"] = cast(flow_module.JsonValue, dict(frame))
    if writes:
        if frame.get("ok") is not True:
            _fail(DETAIL_FRAME.format(name=name, frame=frame))
        return frame
    run = frame.get("run")
    if not isinstance(run, Mapping) or run.get("exit_status") != 0 or run.get("timed_out") is True:
        _fail(DETAIL_FRAME.format(name=name, frame=frame))
    return frame


def _git(
    flow: flow_module.WorkflowFlow,
    *arguments: str,
    cwd: Path | None = None,
    evidence: list[flow_module.JsonValue] | None = None,
) -> str:
    return flow.git(arguments, cwd=cwd, evidence=evidence)


def _startup(
    flow: flow_module.WorkflowFlow,
    session: str,
    expected_role: str,
    procedure: str,
    *,
    activation: bool,
) -> tuple[Mapping[str, object], Mapping[str, object], str]:
    procedure_field = FIELD_JOB if activation else FIELD_COMMAND
    deadline = time.monotonic() + START_SECONDS
    role_path = flow.publication.clone / driver.DOCS_ROOT / f"{procedure}{driver.LIVE_SUFFIX}"
    folded_role = driver.declared_role(role_path)
    if expected_role != folded_role:
        raise creation.binding_failure(
            DETAIL_FOLDED_ROLE.format(session=session, actual=expected_role, folded=folded_role)
        )
    setup, initial_record, launch = flow.await_session_binding(
        session, folded_role, procedure, deadline, activation=activation
    )
    if initial_record.get(FIELD_ROLE) != folded_role or initial_record.get(procedure_field) != procedure:
        _fail(f"session {session} role/{procedure_field} mismatch: {initial_record!r}")
    native = initial_record.get(FIELD_NATIVE)
    if not isinstance(native, str) or launch.get(FIELD_NATIVE) != native:
        raise creation.binding_failure(DETAIL_BINDING.format(detail="native session identity mismatch"))
    journey = foundation.Journey(flow.host, setup, flow.project, flow.owner_email)
    journey.session_id = session
    for hook in (foundation.FRAME_SESSION_START, foundation.FRAME_PROMPT_SUBMIT):
        journey.require_hook(hook, journey.await_frame(hook, deadline))
    record: Mapping[str, object] | None = None
    last: Mapping[str, object] | None = None
    while time.monotonic() < deadline:
        remaining = max(0.1, deadline - time.monotonic())
        current = journey.record(min(FRAME_SECONDS, remaining), retain=False)
        last = current if current is not None else last
        if current is not None:
            for field_name, expected in (
                (FIELD_ROLE, folded_role),
                (procedure_field, procedure),
                (FIELD_NATIVE, native),
            ):
                found = current.get(field_name)
                if found is not None and found != expected:
                    _fail(DETAIL_STARTUP_RECORD.format(session=session, predicate=field_name, record=current))
            project_path = current.get(FIELD_PROJECT)
            if isinstance(project_path, str) and not journey.same_path(project_path):
                _fail(DETAIL_STARTUP_RECORD.format(session=session, predicate=FIELD_PROJECT, record=current))
            if journey.started(current, native):
                confirmed = journey.record(min(FRAME_SECONDS, max(0.1, deadline - time.monotonic())), retain=True)
                if journey.started(confirmed, native):
                    if confirmed is not None and (
                        confirmed.get(FIELD_ROLE) == folded_role and confirmed.get(procedure_field) == procedure
                    ):
                        record = confirmed
                        break
                    _fail(
                        DETAIL_STARTUP_RECORD.format(
                            session=session, predicate=f"role/{procedure_field}", record=confirmed
                        )
                    )
                last = confirmed if confirmed is not None else last
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(POLL_SECONDS, remaining))
    if record is None:
        journey.record(min(FRAME_SECONDS, max(0.1, deadline - time.monotonic())), retain=True)
        _fail(DETAIL_STARTUP_TIMEOUT.format(session=session, record=last))
    first_inputs = journey.inputs()
    first = first_inputs[0].get("text") if first_inputs else None
    if not isinstance(first, str) or not first.startswith(f"TELECLAUDE COMMAND: {procedure}"):
        _fail(f"session {session} first prompt does not name {procedure}: {first!r}")
    return record, launch, folded_role


def _operation_command(
    flow: flow_module.WorkflowFlow,
    session: str,
    frame_name: str,
    attempt_id: str | None = None,
    *,
    evidence: flow_module.MutableJson | None = None,
) -> tuple[Mapping[str, object], Mapping[str, object]]:
    try:
        frame = _frame_success(flow, session, frame_name, evidence=evidence)
    except BaseException:
        if attempt_id is not None:
            flow.require_ledger().unknown(attempt_id)
        raise
    if attempt_id is None:
        _, terminal = _operation(flow, frame, frame_name)
        return frame, terminal
    run = frame.get("run")
    stdout = run.get("stdout") if isinstance(run, Mapping) else None
    receipt = foundation.json_object(stdout) if isinstance(stdout, str) else None
    operation = receipt.get(FIELD_OPERATION) if receipt is not None else None
    if not isinstance(operation, str) or not operation:
        flow.require_ledger().unknown(attempt_id)
        raise creation.binding_failure(DETAIL_BINDING.format(detail=f"{frame_name} receipt is missing"))
    flow.require_ledger().record_operation(attempt_id, operation)
    terminal = flow.operation(operation, OPERATION_SECONDS)
    return frame, terminal


def _require_builder_write_scope(
    session: str,
    builder_record: Mapping[str, object],
    builder_launch: Mapping[str, object],
    base_project: Path,
    expected_subdir: str,
    expected_worktree: Path,
) -> None:
    """Bind the public base/subdir projection and independent native cwd to the owned worktree."""
    expected_base = base_project.resolve()
    expected_effective = (expected_base / expected_subdir).resolve()
    owned_worktree = expected_worktree.resolve()
    raw_project = builder_record.get(FIELD_PROJECT)
    actual_subdir = builder_record.get(FIELD_SUBDIR)
    raw_cwd = builder_launch.get("cwd")
    native = builder_record.get(FIELD_NATIVE)
    launch_native = builder_launch.get(FIELD_NATIVE)
    actual_effective: Path | None = None
    base_matches = False
    if isinstance(raw_project, str) and Path(raw_project).is_absolute():
        try:
            actual_base = Path(raw_project).resolve()
            base_matches = actual_base == expected_base
            if isinstance(actual_subdir, str) and not Path(actual_subdir).is_absolute():
                actual_effective = (Path(raw_project) / actual_subdir).resolve()
        except (OSError, RuntimeError, ValueError):
            actual_effective = None
    cwd_matches = False
    if isinstance(raw_cwd, str) and Path(raw_cwd).is_absolute():
        try:
            cwd_matches = Path(raw_cwd).resolve() == expected_effective
        except (OSError, RuntimeError, ValueError):
            cwd_matches = False
    if (
        not base_matches
        or actual_subdir != expected_subdir
        or actual_effective != expected_effective
        or owned_worktree != expected_effective
        or not cwd_matches
        or not isinstance(native, str)
        or not native
        or launch_native != native
    ):
        raise creation.binding_failure(
            DETAIL_WRITE_SCOPE.format(
                session=session,
                base=expected_base,
                subdir=expected_subdir,
                effective=expected_effective,
                owned=owned_worktree,
                project=raw_project,
                actual_subdir=actual_subdir,
                actual_effective=actual_effective,
                cwd=raw_cwd,
                native=native,
                launch_native=launch_native,
            )
        )


def _git_bytes(
    flow: flow_module.WorkflowFlow, *arguments: str, cwd: Path, evidence: list[flow_module.JsonValue] | None = None
) -> bytes:
    result = flow.host.process(("git", *arguments), cwd, flow.host.environment, FRAME_SECONDS)
    if evidence is not None:
        evidence.append(
            {"kind": "command", "cwd": str(cwd), "value": flow.public_command_evidence(("git", *arguments), result)}
        )
    if result.exit_status != 0:
        raise creation.binding_failure(DETAIL_BINDING.format(detail=f"git {' '.join(arguments)} failed"))
    return result.output.encode("utf-8")


def _direct_act(
    flow: flow_module.WorkflowFlow,
    session: str,
    frame_name: str,
    performed: str,
    *,
    evidence: flow_module.MutableJson | None = None,
) -> tuple[Mapping[str, object], str]:
    """Read a synchronous direct act's public CLI text; it has no operation receipt."""
    frame = _frame_success(flow, session, frame_name)
    if evidence is not None:
        evidence["frame"] = cast(flow_module.JsonValue, dict(frame))
    run = frame.get("run")
    stdout = run.get("stdout") if isinstance(run, Mapping) else None
    if not isinstance(stdout, str) or performed not in stdout:
        _fail(DETAIL_FRAME.format(name=frame_name, frame=frame))
    return frame, stdout


def _public_log(payload: Mapping[str, object]) -> list[tuple[str, str]]:
    artifact = payload.get("artifact_content")
    log = artifact.get("log") if isinstance(artifact, Mapping) else None
    if not isinstance(log, str):
        raise creation.trace_failure("the public item projection has no artifact_content.log")
    return waiting.log_entries(log)


def _expect_log_append(
    flow: flow_module.WorkflowFlow,
    before: list[tuple[str, str]],
    role: str,
    session: str,
    act: str,
    bound: str | None,
    text: str,
    *,
    evidence: flow_module.MutableJson | None = None,
    items: list[flow_module.JsonValue] | None = None,
) -> None:
    shown = flow.item(evidence=items)
    if evidence is not None:
        evidence["after_item"] = cast(flow_module.JsonValue, dict(shown))
        evidence["observed_ns"] = time.monotonic_ns()
    artifact = shown.get("artifact_content")
    raw_log = artifact.get(FIELD_LOG) if isinstance(artifact, Mapping) else None
    if not isinstance(raw_log, str):
        raise creation.binding_failure(DETAIL_BINDING.format(detail="public B5 log is unavailable"))
    entries = workflow_events.parse_log_entries(raw_log)
    after = [(entry.header, entry.body) for entry in entries]
    if len(after) != len(before) + 1 or after[:-1] != before:
        _fail(f"{act} log section did not append exactly once: {after[len(before) :]!r}")
    entry = entries[-1]
    expected_bound = bound
    if act in (ACT_FINDING, ACT_REPLY):
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        expected_bound = f"{bound}:{digest}" if bound else digest
    if (
        not entry.timestamp
        or entry.role != role
        or entry.session != session
        or entry.act != act
        or entry.bound != expected_bound
        or entry.body != text
    ):
        _fail(f"{act} public log actor, binding, or exact body differed: {entry!r}")


def _direct_effect(flow: flow_module.WorkflowFlow, label: str) -> str:
    try:
        return flow.require_ledger().begin(flow_module.SFC_CHAIN_B5, label, start_ledger.RECORD_EFFECT)
    except ValueError as error:
        raise creation.binding_failure(DETAIL_LEDGER.format(detail=str(error))) from error


def _negative_direct_act(
    flow: flow_module.WorkflowFlow,
    actor: str,
    label: str,
    frame_name: str,
    argv_file: str,
    argv: Sequence[str],
) -> None:
    expected = DIRECT_REFUSAL_ERRORS[label]
    attempt = flow.require_ledger().begin(flow_module.SFC_CHAIN_B5, label, start_ledger.RECORD_EFFECT)
    before = flow.item()
    before_log = _public_log(before)
    evidence = flow.direct_input(attempt, actor, before)
    flow.late_argv(actor, argv_file, argv)
    flow.gate(actor, f"go_{frame_name}")
    frame = flow.frame(actor, f"cmd_{frame_name}")
    evidence["frame"] = cast(flow_module.JsonValue, dict(frame))
    raw_run = frame.get("run")
    run = raw_run if isinstance(raw_run, Mapping) else {}
    status = run.get("exit_status")
    output = f"{run.get('stdout', '')}{run.get('stderr', '')}"
    if status in (None, 0) or expected not in output or "Performed " in output:
        _fail(f"B9 {label} lacked its required refusal {expected!r}: {frame!r}")
    after = flow.item()
    evidence["after_item"] = cast(flow_module.JsonValue, dict(after))
    evidence["observed_ns"] = time.monotonic_ns()
    if after != before or _public_log(after) != before_log:
        _fail(f"B9 {label} changed the complete public item or parsed log")
    flow.require_ledger().discharge(attempt, f"direct refusal {expected!r}; public show and log unchanged")


def _negative_stamp(flow: flow_module.WorkflowFlow, builder: str, commit: str, worktree: Path) -> None:
    attempt = flow.require_ledger().begin(flow_module.SFC_CHAIN_B5, "stamp-performer", start_ledger.RECORD_TRIGGER)
    before = flow.item()
    evidence = flow.stamp_input(builder, before, attempt)
    before_git = cast(list[flow_module.JsonValue], evidence["before_git"])
    after_items = cast(list[flow_module.JsonValue], evidence["after_items"])
    before_log = _public_log(before)
    if (
        _git(flow, "rev-parse", "HEAD", cwd=worktree, evidence=before_git) != commit
        or _git(flow, "status", "--porcelain", cwd=worktree, evidence=before_git)
        or _git(flow, "ls-remote", flow_module.ORIGIN, f"refs/heads/{flow_module.ITEM}", evidence=before_git)
        != f"{commit}\trefs/heads/{flow_module.ITEM}"
    ):
        raise creation.binding_failure("B9 stamp-performer precondition is not a clean published C1 head")
    flow.late_argv(
        builder,
        "stampperformer.argv",
        (TELEC, TODO, ACT, flow_module.ITEM, "stamp", "--sha", commit, LANE_ONE),
    )
    flow.gate(builder, "go_stampperformer")
    frame = flow.frame(builder, "cmd_stampperformer")
    evidence["frame"] = cast(flow_module.JsonValue, dict(frame))
    raw_run = frame.get("run")
    run = raw_run if isinstance(raw_run, Mapping) else {}
    stdout = run.get("stdout")
    receipt = foundation.json_object(stdout) if isinstance(stdout, str) else None
    operation = receipt.get(FIELD_OPERATION) if receipt is not None else None
    if run.get("exit_status") != 0 or not isinstance(operation, str) or not operation:
        flow.require_ledger().unknown(attempt)
        raise creation.binding_failure(DETAIL_BINDING.format(detail=f"stamp-performer receipt missing: {frame!r}"))
    flow.require_ledger().record_operation(attempt, operation)
    terminal = flow.operation(operation, OPERATION_SECONDS)
    error = terminal.get(FIELD_ERROR)
    if (
        terminal.get(FIELD_STATE) != STATE_FAILED
        or not isinstance(error, str)
        or "stamp requires the holding driver" not in error
    ):
        _fail(f"B9 stamp-performer failed with {terminal.get(FIELD_STATE)!r}: {error!r}")
    after = flow.item(evidence=after_items)
    if after != before or _public_log(after) != before_log:
        _fail("B9 stamp-performer refusal changed the public item or parsed log")
    evidence["finished_ns"] = time.monotonic_ns()
    # The receipt-backed trigger stays open by the approved SFC contract.


def _end(flow: flow_module.WorkflowFlow, session: str) -> None:
    current = flow.session_record(session)
    if current.get("closed_at") is not None and current.get("lifecycle_status") == "closed":
        return
    outcome = flow.observer.run((TELEC, "sessions", "end", session))
    receipt = foundation.json_object(outcome.output)
    operation = receipt.get(FIELD_OPERATION) if receipt is not None else None
    if outcome.exit_status != 0 or not isinstance(operation, str) or not operation:
        raise creation.binding_failure(DETAIL_BINDING.format(detail=f"sessions end {session}: {outcome.output[-300:]}"))
    terminal = flow.operation(operation, START_SECONDS)
    if terminal.get(FIELD_STATE) != STATE_COMPLETED:
        _fail(
            DETAIL_STATE.format(operation=operation, state=terminal.get(FIELD_STATE), detail=terminal.get(FIELD_ERROR))
        )
    record = flow.session_record(session)
    if record.get("closed_at") is None or record.get("lifecycle_status") != "closed":
        _fail(f"session {session} end lacks a retained closed record: {record!r}")


def _start_work(
    flow: flow_module.WorkflowFlow,
) -> tuple[creation.SessionView, Path, str, str, str, str, int, driver.DriverCase]:
    baseline = flow.observer.sessions()
    item = flow.item()
    artifact = item.get("artifact_content")
    log = artifact.get(FIELD_LOG) if isinstance(artifact, Mapping) else None
    if not isinstance(log, str):
        raise creation.binding_failure(DETAIL_BINDING.format(detail="B5 start log is unavailable"))
    known_claims = len(driver.claim_entries(log))
    worktree = flow.project / flow_module.WORKTREE_DIRECTORY / flow_module.ITEM
    if not worktree.is_dir():
        raise creation.binding_failure(DETAIL_BINDING.format(detail=f"worktree absent: {worktree}"))
    child_attempt, parent_id = flow.require_ledger().begin_child_before_parent(
        flow_module.SFC_CHAIN_B5, "w2-child", "w2-start", start_ledger.RECORD_SESSION, start_ledger.RECORD_OPERATION
    )
    child_evidence: flow_module.MutableJson = {
        "attempt_id": child_attempt,
        "parent_attempt_id": parent_id,
        "started_ns": time.monotonic_ns(),
        "observed_ns": None,
        "parent_actor": None,
        "parent_native_session_id": None,
        "base_project": str(flow.project),
        "worktree": str(worktree),
        "frame": None,
        "public_record": None,
        "launch_record": None,
    }
    flow.public_child_evidence.append(child_evidence)
    outcome = flow.observer.run((TELEC, TODO, WORK, flow_module.ITEM))
    receipt = foundation.json_object(outcome.output)
    operation = receipt.get(FIELD_OPERATION) if receipt is not None else None
    if outcome.exit_status != 0 or not isinstance(operation, str) or not operation:
        flow.require_ledger().unknown(parent_id)
        raise creation.binding_failure(DETAIL_BINDING.format(detail=outcome.output[-300:]))
    flow.require_ledger().record_operation(parent_id, operation)
    terminal = flow.operation(operation, START_SECONDS)
    if terminal.get(FIELD_STATE) != STATE_COMPLETED:
        _fail(
            DETAIL_STATE.format(operation=operation, state=terminal.get(FIELD_STATE), detail=terminal.get(FIELD_ERROR))
        )
    w2 = flow.plan_actor(PROC_WORK, 1, ROLE_WORK)
    w2_record, w2_launch, w2_role = _startup(flow, w2, ROLE_WORK, PROC_WORK, activation=True)
    result = terminal.get(FIELD_RESULT)
    reservation_keys = list(B14_RESERVATION_KEY.finditer(result)) if isinstance(result, str) else []
    if len(reservation_keys) != 1:
        raise creation.binding_failure(B14_RESERVATION_MISSING)
    creation.require_b14_kickback(
        flow.observer,
        TELEC,
        flow_module.ITEM,
        creation.B14Case.START_IN_PROGRESS,
        starting_session=w2,
        reservation=reservation_keys[0].group("key"),
    )
    flow.gate(w2, flow_module.B14_CLAIM_GATE)
    child_evidence["parent_actor"] = w2
    child_evidence["parent_native_session_id"] = cast(flow_module.JsonValue, w2_record.get(FIELD_NATIVE))
    child_frame = _frame_success(flow, w2, "child")
    child_evidence["frame"] = cast(flow_module.JsonValue, dict(child_frame))
    child_run = child_frame.get("run")
    child_stdout = child_run.get("stdout") if isinstance(child_run, Mapping) else None
    match = re.search(r"Started sdlc/procedure/lifecycle/work/build-v2 as session ([A-Za-z0-9_-]+)", child_stdout or "")
    if not isinstance(child_stdout, str) or match is None:
        _fail(f"B5 builder child start text is absent: {child_frame!r}")
    builder = match.group(1)
    flow.require_ledger().record_session(child_attempt, builder)
    builder_record, builder_launch, _builder_role = _startup(flow, builder, ROLE_BUILDER, PROC_BUILD, activation=False)
    child_evidence["public_record"] = cast(flow_module.JsonValue, dict(builder_record))
    child_evidence["launch_record"] = cast(flow_module.JsonValue, dict(builder_launch))
    if builder_record.get(FIELD_INITIATOR) != w2:
        _fail(f"builder initiator is {builder_record.get(FIELD_INITIATOR)!r}, not {w2}")
    _require_builder_write_scope(
        builder,
        builder_record,
        builder_launch,
        flow.project,
        B5_BUILDER_SUBDIR,
        worktree,
    )
    child_evidence["observed_ns"] = time.monotonic_ns()
    case = driver.DriverCase(
        host=flow.host,
        observer=flow.observer,
        journey=flow.journey(w2),
        item=flow_module.ITEM,
        launch_setup=flow.setup_for_session(w2),
        clone=flow.publication.clone,
        baseline=baseline,
        driver_id=PROC_WORK,
        verb=WORK,
        phase=flow_module.WORK_PHASE,
        claim_evidence=flow.claim_input(parent_id, w2, flow_module.WORK_PHASE, w2_record, w2_launch),
    )
    case.titles[w2] = case.require_title(w2_record, w2_role)
    instruction = case.claim_call((operation,))
    case.check_instruction(w2, instruction)
    case.observe_claim(w2, known_entries=known_claims)
    return baseline, worktree, w2, builder, operation, parent_id, known_claims, case


def _build_and_review(
    flow: flow_module.WorkflowFlow, worktree: Path, w2: str, builder: str, operation: str
) -> tuple[str, str, str]:
    flow.gate(builder, "go_w1")
    write_frame = _frame_success(flow, builder, "write1", writes=True)
    if write_frame.get("cwd") != str(worktree.resolve()):
        raise creation.binding_failure(
            DETAIL_WRITE_FRAME_SCOPE.format(cwd=write_frame.get("cwd"), worktree=worktree.resolve(), frame=write_frame)
        )
    _frame_success(flow, builder, "commit1")
    commit_one = _git(flow, "rev-parse", "HEAD", cwd=worktree)
    subject = _git(flow, "show", "-s", "--format=%s", commit_one, cwd=worktree)
    body = _git(flow, "show", "-s", "--format=%B", commit_one, cwd=worktree)
    author = _git(flow, "show", "-s", "--format=%an", commit_one, cwd=worktree)
    remote_one = _git(flow, "ls-remote", flow_module.ORIGIN, f"refs/heads/{flow_module.ITEM}")
    count = _git(flow, "rev-list", "--count", f"origin/{flow_module.MAIN}..{flow_module.ITEM}", cwd=worktree)
    if (
        not remote_one.startswith(commit_one)
        or subject != flow_module.B5_COMMIT_1.splitlines()[0]
        or not body.startswith(f"{flow_module.B5_COMMIT_1}\n\n")
        or f"Session: {builder}" not in body
        or author == "Runtime Acceptance Fixture"
        or count != "2"
    ):
        _fail(f"sealed builder commit {commit_one} did not publish the branch: {remote_one!r}")
    _negative_direct_act(
        flow,
        builder,
        "reviewed-wrong",
        "reviewedwrong",
        "reviewedwrong.argv",
        (TELEC, TODO, ACT, flow_module.ITEM, "reviewed", "--sha", commit_one),
    )
    _negative_direct_act(
        flow,
        builder,
        "finding-wrong",
        "findingwrong",
        "findingwrong.argv",
        (TELEC, TODO, ACT, flow_module.ITEM, "finding", "--sha", commit_one, WRONG_PERFORMER_TEXT),
    )
    _negative_direct_act(
        flow,
        builder,
        "kickback-wrong",
        "kickbackwrong",
        "kickbackwrong.argv",
        (TELEC, TODO, ACT, flow_module.ITEM, "kickback", WRONG_PERFORMER_TEXT),
    )
    _negative_direct_act(
        flow,
        builder,
        "release-wrong",
        "releasewrong",
        "releasewrong.argv",
        (TELEC, TODO, ACT, flow_module.ITEM, "release"),
    )
    _negative_stamp(flow, builder, commit_one, worktree)
    reviewed_attempt = _direct_effect(flow, "reviewed")
    reviewed_before = flow.item()
    reviewed_log = _public_log(reviewed_before)
    reviewed_evidence = flow.direct_input(reviewed_attempt, w2, reviewed_before, commit_one)
    flow.late_argv(w2, "reviewed.argv", (TELEC, TODO, ACT, flow_module.ITEM, "reviewed", "--sha", commit_one))
    flow.gate(w2, "go_rev")
    _direct_act(flow, w2, "reviewed", f"Performed {ACT_REVIEWED} on {flow_module.ITEM}", evidence=reviewed_evidence)
    _expect_log_append(flow, reviewed_log, ROLE_WORK, w2, ACT_REVIEWED, commit_one, "", evidence=reviewed_evidence)
    flow.require_ledger().discharge(reviewed_attempt, "W2 performed reviewed on the published C1 head")
    finding_attempt = _direct_effect(flow, "finding")
    finding_before = flow.item()
    finding_log = _public_log(finding_before)
    finding_evidence = flow.direct_input(finding_attempt, w2, finding_before, commit_one)
    flow.late_argv(
        w2, "finding.argv", (TELEC, TODO, ACT, flow_module.ITEM, "finding", "--sha", commit_one, FINDING_TEXT)
    )
    flow.gate(w2, "go_find")
    _, finding_text = _direct_act(
        flow, w2, "finding", f"Performed {ACT_FINDING} on {flow_module.ITEM}", evidence=finding_evidence
    )
    _expect_log_append(
        flow, finding_log, ROLE_WORK, w2, ACT_FINDING, commit_one, FINDING_TEXT, evidence=finding_evidence
    )
    flow.require_ledger().discharge(finding_attempt, "W2 performed finding on the published C1 head")
    key_match = re.search(r"finding key:\s*(\S+)", finding_text)
    if key_match is None:
        _fail(DETAIL_KEY.format(result=finding_text))
    finding_key = key_match.group(1)
    _negative_direct_act(
        flow,
        w2,
        "reply-wrong",
        "replywrong",
        "replywrong.argv",
        (TELEC, TODO, ACT, flow_module.ITEM, "reply", "--finding", finding_key, WRONG_PERFORMER_TEXT),
    )
    reply_attempt = _direct_effect(flow, "reply")
    reply_before = flow.item()
    reply_log = _public_log(reply_before)
    reply_evidence = flow.direct_input(reply_attempt, builder, reply_before, finding_key)
    flow.late_argv(
        builder, "reply.argv", (TELEC, TODO, ACT, flow_module.ITEM, "reply", "--finding", finding_key, REPLY_TEXT)
    )
    flow.gate(builder, "go_reply")
    _direct_act(flow, builder, "reply", f"Performed {ACT_REPLY} on {flow_module.ITEM}", evidence=reply_evidence)
    _expect_log_append(
        flow, reply_log, ROLE_BUILDER, builder, ACT_REPLY, finding_key, REPLY_TEXT, evidence=reply_evidence
    )
    flow.require_ledger().discharge(reply_attempt, "the builder replied to W2's published finding key")
    flow.gate(builder, "go_c2")
    _frame_success(flow, builder, "write2", writes=True)
    _frame_success(flow, builder, "commit2")
    commit_two = _git(flow, "rev-parse", "HEAD", cwd=worktree)
    remote_two = _git(flow, "ls-remote", flow_module.ORIGIN, f"refs/heads/{flow_module.ITEM}")
    if commit_two == commit_one or not remote_two.startswith(commit_two):
        _fail("second sealed commit did not move and publish the branch head")
    feature_one = flow.host.process(
        ("git", "show", f"{commit_one}:feature.txt"), worktree, flow.host.environment, FRAME_SECONDS
    )
    makefile_one = flow.host.process(
        ("git", "show", f"{commit_one}:Makefile"), worktree, flow.host.environment, FRAME_SECONDS
    )
    feature_two = flow.host.process(
        ("git", "show", f"{commit_two}:feature.txt"), worktree, flow.host.environment, FRAME_SECONDS
    )
    if (
        feature_one.output.encode("utf-8") != b"b5 file one\n"
        or makefile_one.output.encode("utf-8") != b"test:\n\t@true\n"
        or feature_two.output.encode("utf-8") != b"b5 file one\nb5 file two\n"
    ):
        _fail("sealed builder commits do not contain the approved fixture bytes")
    return commit_one, commit_two, finding_key


def _exercise_stamps(flow: flow_module.WorkflowFlow, w2: str, builder: str, commit_one: str, commit_two: str) -> str:
    worktree = flow.project / flow_module.WORKTREE_DIRECTORY / flow_module.ITEM
    snapshot = flow.item()
    snapshot_log = _public_log(snapshot)
    evidence = flow.stamp_input(w2, snapshot)
    before_git = cast(list[flow_module.JsonValue], evidence["before_git"])
    after_git = cast(list[flow_module.JsonValue], evidence["after_git"])
    after_items = cast(list[flow_module.JsonValue], evidence["after_items"])
    refs = (
        _git(flow, "ls-remote", flow_module.ORIGIN, f"refs/heads/{flow_module.ITEM}", evidence=before_git),
        _git(flow, "rev-parse", "HEAD", cwd=worktree, evidence=before_git),
        _git(
            flow,
            "rev-list",
            "--count",
            f"origin/{flow_module.MAIN}..{flow_module.ITEM}",
            cwd=worktree,
            evidence=before_git,
        ),
    )
    flow.late_argv(
        w2, "stamp_nonhead.argv", (TELEC, TODO, ACT, flow_module.ITEM, "stamp", "--sha", commit_one, LANE_ONE)
    )
    nonhead_attempt = flow.require_ledger().begin(
        flow_module.SFC_CHAIN_B5, "stamp-nonhead", start_ledger.RECORD_TRIGGER
    )
    evidence["attempt_id"] = nonhead_attempt
    flow.gate(w2, "go_nh")
    _, rejected = _operation_command(flow, w2, "stamp_nonhead", nonhead_attempt, evidence=evidence)
    error = rejected.get(FIELD_ERROR)
    if (
        rejected.get(FIELD_STATE) != STATE_FAILED
        or not isinstance(error, str)
        or commit_one not in error
        or commit_two not in error
    ):
        _fail(f"non-head stamp did not refuse both refs: {rejected!r}")
    if flow.item(evidence=after_items) != snapshot or _public_log(flow.item(evidence=after_items)) != snapshot_log:
        _fail("a refused non-head stamp changed the item snapshot")
    time.sleep(5.0)
    if flow.item(evidence=after_items) != snapshot or _public_log(flow.item(evidence=after_items)) != snapshot_log:
        _fail("a refused non-head stamp changed the item during the stability window")
    current_refs = (
        _git(flow, "ls-remote", flow_module.ORIGIN, f"refs/heads/{flow_module.ITEM}", evidence=after_git),
        _git(flow, "rev-parse", "HEAD", cwd=worktree, evidence=after_git),
        _git(
            flow,
            "rev-list",
            "--count",
            f"origin/{flow_module.MAIN}..{flow_module.ITEM}",
            cwd=worktree,
            evidence=after_git,
        ),
    )
    if current_refs != refs:
        _fail(f"a refused non-head stamp moved the branch refs: {current_refs!r}")
    evidence["finished_ns"] = time.monotonic_ns()
    flow.late_argv(w2, "stamp_empty.argv", (TELEC, TODO, ACT, flow_module.ITEM, "stamp", "--sha", commit_two))
    empty_attempt = flow.require_ledger().begin(flow_module.SFC_CHAIN_B5, "stamp-empty", start_ledger.RECORD_TRIGGER)
    evidence = flow.stamp_input(w2, snapshot, empty_attempt)
    evidence["before_git"] = list(before_git)
    after_git = cast(list[flow_module.JsonValue], evidence["after_git"])
    after_items = cast(list[flow_module.JsonValue], evidence["after_items"])
    flow.gate(w2, "go_empty")
    _, empty = _operation_command(flow, w2, "stamp_empty", empty_attempt, evidence=evidence)
    if empty.get(FIELD_STATE) != STATE_FAILED or "lane report" not in str(empty.get(FIELD_ERROR, "")):
        _fail(f"empty stamp did not refuse the missing lane report: {empty!r}")
    if (
        flow.item(evidence=after_items) != snapshot
        or _public_log(flow.item(evidence=after_items)) != snapshot_log
        or (
            _git(flow, "ls-remote", flow_module.ORIGIN, f"refs/heads/{flow_module.ITEM}", evidence=after_git),
            _git(flow, "rev-parse", "HEAD", cwd=worktree, evidence=after_git),
            _git(
                flow,
                "rev-list",
                "--count",
                f"origin/{flow_module.MAIN}..{flow_module.ITEM}",
                cwd=worktree,
                evidence=after_git,
            ),
        )
        != refs
    ):
        _fail("empty stamp changed the item or branch refs")
    evidence["finished_ns"] = time.monotonic_ns()
    _exercise_b11_stamp_refusals(flow, w2, builder, commit_two, worktree)
    success_before = flow.item()
    success_log = _public_log(success_before)
    flow.late_argv(w2, "stamp_ok.argv", (TELEC, TODO, ACT, flow_module.ITEM, "stamp", "--sha", commit_two, LANE_ONE))
    success_attempt = flow.require_ledger().begin(flow_module.SFC_CHAIN_B5, "stamp-ok", start_ledger.RECORD_TRIGGER)
    evidence = flow.stamp_input(w2, success_before, success_attempt)
    after_items = cast(list[flow_module.JsonValue], evidence["after_items"])
    flow.gate(w2, "go_ok")
    _, stamped = _operation_command(flow, w2, "stamp_ok", success_attempt, evidence=evidence)
    if stamped.get(FIELD_STATE) != STATE_COMPLETED or not str(stamped.get(FIELD_RESULT, "")).startswith(
        f"Stamped {flow_module.ITEM} at {commit_two}"
    ):
        _fail(f"head stamp did not complete at {commit_two}: {stamped!r}")
    shown = flow.item(evidence=after_items)
    standing = shown.get("standing")
    state = shown.get("state")
    _expect_log_append(flow, success_log, ROLE_WORK, w2, "stamp", commit_two, LANE_ONE, items=after_items)
    if (
        not isinstance(standing, Mapping)
        or standing.get(FIELD_STANDING_PHASE) != "ready"
        or standing.get(FIELD_READY_COMMIT) != commit_two
        or FIELD_ADMITTED in standing
        or not isinstance(state, Mapping)
        or state.get(FIELD_ACTIVE) not in (None, "")
    ):
        _fail(f"successful stamp did not produce unadmitted ready at {commit_two}: {shown!r}")
    builder_record = flow.session_record(builder)
    evidence["closed_child"] = cast(flow_module.JsonValue, dict(builder_record))
    if builder_record.get("closed_at") is None or builder_record.get("lifecycle_status") != "closed":
        _fail(f"successful stamp did not close the builder child: {builder_record!r}")
    ready_since = standing.get("ready_since")
    if not isinstance(ready_since, str) or not ready_since:
        raise creation.binding_failure("B10 requires the public C2 ready_since witness before the C3 head move")
    evidence["finished_ns"] = time.monotonic_ns()
    return ready_since


def _b11_ref_state(
    flow: flow_module.WorkflowFlow, worktree: Path, evidence: list[flow_module.JsonValue] | None = None
) -> tuple[str, str, str, str]:
    remote = _git(flow, "ls-remote", flow_module.ORIGIN, f"refs/heads/{flow_module.ITEM}", evidence=evidence)
    head = _git(flow, "rev-parse", "HEAD", cwd=worktree, evidence=evidence)
    branch = _git(flow, "show-ref", "--verify", f"refs/heads/{flow_module.ITEM}", cwd=worktree, evidence=evidence)
    count = _git(
        flow,
        "rev-list",
        "--count",
        f"origin/{flow_module.MAIN}..{flow_module.ITEM}",
        cwd=worktree,
        evidence=evidence,
    )
    return remote, head, branch, count


def _b11_file(path: Path, evidence: list[flow_module.JsonValue] | None) -> bytes:
    data = path.read_bytes()
    if evidence is not None:
        evidence.append({"kind": "file", "path": str(path), "raw_data": base64.b64encode(data).decode("ascii")})
    return data


def _b11_assert_clean_c2(
    flow: flow_module.WorkflowFlow,
    worktree: Path,
    commit: str,
    refs: tuple[str, str, str, str],
    evidence: list[flow_module.JsonValue] | None = None,
) -> None:
    expected_remote = f"{commit}\trefs/heads/{flow_module.ITEM}"
    expected_branch = f"{commit} refs/heads/{flow_module.ITEM}"
    feature = worktree / B11_FEATURE_PATH
    if (
        refs[0] != expected_remote
        or refs[1] != commit
        or refs[2] != expected_branch
        or not refs[3].isdigit()
        or _git(flow, "status", "--porcelain=v1", "--untracked-files=all", cwd=worktree, evidence=evidence)
        or _git(flow, "diff", "--cached", "--name-only", cwd=worktree, evidence=evidence)
        or _b11_file(feature, evidence) != B11_BASE_FEATURE_BYTES
        or _git_bytes(flow, "show", f"{commit}:{B11_FEATURE_PATH}", cwd=worktree, evidence=evidence)
        != B11_BASE_FEATURE_BYTES
    ):
        raise creation.binding_failure(DETAIL_BINDING.format(detail="B11 requires the clean published C2 tree"))


def _b11_assert_owned_append(
    flow: flow_module.WorkflowFlow, worktree: Path, evidence: list[flow_module.JsonValue] | None = None
) -> None:
    status = _git_bytes(flow, "status", "--porcelain=v1", "--untracked-files=all", cwd=worktree, evidence=evidence)
    additions = _git(flow, "diff", "--numstat", "--", B11_FEATURE_PATH, cwd=worktree, evidence=evidence)
    diff = _git(flow, "diff", "--no-ext-diff", "--unified=0", "--", B11_FEATURE_PATH, cwd=worktree, evidence=evidence)
    changed_lines = [
        line for line in diff.splitlines() if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]
    if (
        status != B11_STATUS_MODIFIED_BYTES
        or _git(flow, "diff", "--cached", "--name-only", cwd=worktree, evidence=evidence)
        or additions != B11_NUMSTAT
        or changed_lines != [f"+{B11_SENTINEL_LINE}"]
        or _b11_file(worktree / B11_FEATURE_PATH, evidence) != B11_BASE_FEATURE_BYTES + B11_SENTINEL_BYTES
    ):
        raise creation.binding_failure(
            DETAIL_BINDING.format(detail="B11 worktree differs from its owned sentinel append")
        )


def _b11_item_unchanged(
    flow: flow_module.WorkflowFlow,
    snapshot: Mapping[str, object],
    parsed_log: list[tuple[str, str]],
    where: str,
    evidence: flow_module.MutableJson | None = None,
    items: list[flow_module.JsonValue] | None = None,
) -> None:
    current = flow.item(evidence=items)
    if evidence is not None:
        evidence["after_item"] = cast(flow_module.JsonValue, dict(current))
        evidence["observed_ns"] = time.monotonic_ns()
    if current != snapshot or _public_log(current) != parsed_log:
        _fail(f"B11 {where} changed the strict public item or parsed log")


def _b11_refused_stamp(
    flow: flow_module.WorkflowFlow,
    w2: str,
    attempt_label: str,
    argv_file: str,
    frame_name: str,
    gate: str,
    requested_sha: str,
    expected_error: str,
    snapshot: Mapping[str, object],
    parsed_log: list[tuple[str, str]],
    unchanged_refs: tuple[str, str, str, str],
) -> None:
    attempt = flow.require_ledger().begin(flow_module.SFC_CHAIN_B5, attempt_label, start_ledger.RECORD_TRIGGER)
    evidence = flow.stamp_input(w2, snapshot, attempt)
    after_items = cast(list[flow_module.JsonValue], evidence["after_items"])
    after_git = cast(list[flow_module.JsonValue], evidence["after_git"])
    flow.late_argv(
        w2,
        argv_file,
        (TELEC, TODO, ACT, flow_module.ITEM, B11_STAMP_VERB, "--sha", requested_sha, LANE_ONE),
    )
    flow.gate(w2, gate)
    _, terminal = _operation_command(flow, w2, frame_name, attempt, evidence=evidence)
    error = terminal.get(FIELD_ERROR)
    if terminal.get(FIELD_STATE) != STATE_FAILED or not isinstance(error, str) or expected_error not in error:
        _fail(f"B11 {frame_name} did not return the exact approved refusal: {terminal!r}")
    _b11_item_unchanged(flow, snapshot, parsed_log, frame_name, items=after_items)
    if (
        _b11_ref_state(flow, flow.project / flow_module.WORKTREE_DIRECTORY / flow_module.ITEM, after_git)
        != unchanged_refs
    ):
        _fail(f"B11 {frame_name} changed the guarded Git refs")
    evidence["finished_ns"] = time.monotonic_ns()


def _b11_restore_dirty_sentinel(
    flow: flow_module.WorkflowFlow,
    worktree: Path,
    effect: str,
    snapshot: Mapping[str, object],
    parsed_log: list[tuple[str, str]],
    refs: tuple[str, str, str, str],
    staged_paths: str,
    evidence: flow_module.MutableJson,
) -> None:
    before = cast(list[flow_module.JsonValue], evidence["pre_restore_reads"])
    after = cast(list[flow_module.JsonValue], evidence["post_restore_reads"])
    _b11_assert_owned_append(flow, worktree, before)
    if (
        _b11_ref_state(flow, worktree, before) != refs
        or _git(flow, "diff", "--cached", "--name-only", cwd=worktree, evidence=before) != staged_paths
    ):
        raise creation.binding_failure(DETAIL_BINDING.format(detail="B11 staged index changed before sentinel restore"))
    restored = flow.host.process(
        ("git", "restore", "--worktree", "--", B11_FEATURE_PATH),
        worktree,
        flow.host.environment,
        FRAME_SECONDS,
    )
    evidence["restore_command"] = flow.public_command_evidence(
        ("git", "restore", "--worktree", "--", B11_FEATURE_PATH), restored
    )
    if restored.exit_status != 0:
        raise creation.binding_failure(DETAIL_BINDING.format(detail=restored.output[-300:]))
    if (
        _b11_ref_state(flow, worktree, after) != refs
        or _git(flow, "status", "--porcelain=v1", "--untracked-files=all", cwd=worktree, evidence=after)
        or _git(flow, "diff", "--cached", "--name-only", cwd=worktree, evidence=after) != staged_paths
        or _b11_file(worktree / B11_FEATURE_PATH, after) != B11_BASE_FEATURE_BYTES
        or _git_bytes(flow, "show", f"{refs[1]}:{B11_FEATURE_PATH}", cwd=worktree, evidence=after)
        != B11_BASE_FEATURE_BYTES
    ):
        raise creation.binding_failure(DETAIL_BINDING.format(detail="B11 sentinel restore did not return to exact C2"))
    _b11_item_unchanged(flow, snapshot, parsed_log, "sentinel restore", evidence)
    flow.require_ledger().discharge(
        effect, "owned 19-byte append restored; C2 refs, index, bytes and public item re-read"
    )


def _b11_evidence(
    flow: flow_module.WorkflowFlow,
    label: str,
    snapshot: Mapping[str, object],
    commit: str,
    worktree: Path,
    actor: str | None = None,
) -> tuple[flow_module.MutableJson, list[flow_module.JsonValue], list[flow_module.JsonValue]]:
    before: list[flow_module.JsonValue] = []
    changed: list[flow_module.JsonValue] = []
    evidence: flow_module.MutableJson = {
        "label": label,
        "actor": actor,
        "attempt_id": None,
        "started_ns": time.monotonic_ns(),
        "observed_ns": None,
        "base_project": str(flow.project),
        "worktree": str(worktree),
        "commit": commit,
        "before_item": cast(flow_module.JsonValue, dict(snapshot)),
        "after_item": None,
        "before_reads": before,
        "changed_reads": changed,
        "pre_restore_reads": [],
        "post_restore_reads": [],
        "write_frame": None,
        "mutation_command": None,
        "restore_command": None,
        "temporary_head": None,
    }
    flow.public_restoration_evidence.append(evidence)
    return evidence, before, changed


def _b11_unclean_probe(flow: flow_module.WorkflowFlow, w2: str, builder: str, commit: str, worktree: Path) -> None:
    snapshot = flow.item()
    parsed_log = _public_log(snapshot)
    evidence, before, changed = _b11_evidence(flow, B11_SENTINEL_LABEL, snapshot, commit, worktree, builder)
    refs = _b11_ref_state(flow, worktree, before)
    _b11_assert_clean_c2(flow, worktree, commit, refs, before)
    staged_paths = _git(flow, "diff", "--cached", "--name-only", cwd=worktree, evidence=before)
    effect = flow.require_ledger().begin(flow_module.SFC_CHAIN_B5, B11_SENTINEL_LABEL, start_ledger.RECORD_EFFECT)
    evidence["attempt_id"] = effect
    flow.gate(builder, "go_dirtywrite")
    frame = _frame_success(flow, builder, "writedirty", writes=True)
    evidence["write_frame"] = cast(flow_module.JsonValue, dict(frame))
    writes = frame.get(B11_FRAME_WRITES)
    row = writes[0] if isinstance(writes, list) and len(writes) == 1 else None
    if (
        frame.get("cwd") != str(worktree.resolve())
        or not isinstance(row, Mapping)
        or row.get(B11_PAYLOAD_PATH) != B11_FEATURE_PATH
        or row.get(B11_PAYLOAD_MODE) != "append"
        or row.get(B11_PAYLOAD_BYTES) != B11_EXPECTED_APPEND_COUNT
        or row.get(B11_PAYLOAD_SHA) != flow_module.B11_SENTINEL_SHA256
    ):
        raise creation.binding_failure(DETAIL_FRAME.format(name="writedirty", frame=frame))
    _b11_assert_owned_append(flow, worktree, changed)
    if _b11_ref_state(flow, worktree, changed) != refs:
        raise creation.binding_failure(DETAIL_BINDING.format(detail="B11 dirty write changed an item ref"))
    flow.require_ledger().record_effect(
        effect,
        f"feature.txt append bytes={B11_EXPECTED_APPEND_COUNT} sha256={flow_module.B11_SENTINEL_SHA256}",
    )
    try:
        _b11_refused_stamp(
            flow,
            w2,
            B11_TRIGGER_UNCLEAN,
            B11_UNCLEAN_ARGV,
            B11_STAMP_UNCLEAN,
            "go_unclean",
            commit,
            B11_DIRTY_REFUSAL,
            snapshot,
            parsed_log,
            refs,
        )
    except BaseException:
        flow.retain(flow_module.RETAINED_MARKER.format(path=flow.root))
        raise
    try:
        _b11_restore_dirty_sentinel(flow, worktree, effect, snapshot, parsed_log, refs, staged_paths, evidence)
    except BaseException:
        flow.retain(flow_module.RETAINED_MARKER.format(path=flow.root))
        raise


def _b11_restore_local_head(
    flow: flow_module.WorkflowFlow,
    worktree: Path,
    effect: str,
    c2: str,
    temporary: str,
    snapshot: Mapping[str, object],
    parsed_log: list[tuple[str, str]],
    original_refs: tuple[str, str, str, str],
    evidence: flow_module.MutableJson,
) -> None:
    before = cast(list[flow_module.JsonValue], evidence["pre_restore_reads"])
    after = cast(list[flow_module.JsonValue], evidence["post_restore_reads"])
    current_refs = _b11_ref_state(flow, worktree, before)
    parent = _git(flow, "rev-parse", f"{temporary}^", cwd=worktree, evidence=before)
    if (
        current_refs[0] != original_refs[0]
        or current_refs[1] != temporary
        or current_refs[2] != f"{temporary} refs/heads/{flow_module.ITEM}"
        or parent != c2
        or _git(flow, "status", "--porcelain=v1", "--untracked-files=all", cwd=worktree, evidence=before)
    ):
        raise creation.binding_failure(
            DETAIL_BINDING.format(detail="B11 temporary commit is no longer the sole owned change")
        )
    reset = flow.host.process(("git", "reset", "--hard", c2), worktree, flow.host.environment, FRAME_SECONDS)
    evidence["restore_command"] = flow.public_command_evidence(("git", "reset", "--hard", c2), reset)
    if reset.exit_status != 0:
        raise creation.binding_failure(DETAIL_BINDING.format(detail=reset.output[-300:]))
    if (
        _b11_ref_state(flow, worktree, after) != original_refs
        or _git(flow, "status", "--porcelain=v1", "--untracked-files=all", cwd=worktree, evidence=after)
        or _b11_file(worktree / B11_FEATURE_PATH, after) != B11_BASE_FEATURE_BYTES
    ):
        raise creation.binding_failure(
            DETAIL_BINDING.format(detail="B11 temporary commit restore did not return to C2")
        )
    _b11_item_unchanged(flow, snapshot, parsed_log, "temporary-head restore", evidence)
    flow.require_ledger().discharge(effect, f"owned local-only commit {temporary} reset to C2 and refs/item re-read")


def _b11_worktree_head_probe(flow: flow_module.WorkflowFlow, w2: str, c2: str, worktree: Path) -> None:
    snapshot = flow.item()
    parsed_log = _public_log(snapshot)
    evidence, before, changed = _b11_evidence(flow, B11_LOCAL_HEAD_LABEL, snapshot, c2, worktree)
    original_refs = _b11_ref_state(flow, worktree, before)
    _b11_assert_clean_c2(flow, worktree, c2, original_refs, before)
    effect = flow.require_ledger().begin(flow_module.SFC_CHAIN_B5, B11_LOCAL_HEAD_LABEL, start_ledger.RECORD_EFFECT)
    evidence["attempt_id"] = effect
    commit_result = flow.host.process(
        ("git", "commit", "--allow-empty", "-m", B11_LOCAL_COMMIT_MESSAGE),
        worktree,
        flow.host.environment,
        FRAME_SECONDS,
    )
    evidence["mutation_command"] = flow.public_command_evidence(
        ("git", "commit", "--allow-empty", "-m", B11_LOCAL_COMMIT_MESSAGE), commit_result
    )
    if commit_result.exit_status != 0:
        raise creation.binding_failure(DETAIL_BINDING.format(detail=commit_result.output[-300:]))
    temporary = _git(flow, "rev-parse", "HEAD", cwd=worktree, evidence=changed)
    evidence["temporary_head"] = temporary
    current_refs = _b11_ref_state(flow, worktree, changed)
    if (
        temporary == c2
        or current_refs[0] != original_refs[0]
        or current_refs[1] != temporary
        or current_refs[2] != f"{temporary} refs/heads/{flow_module.ITEM}"
        or _git(flow, "rev-parse", f"{temporary}^", cwd=worktree, evidence=changed) != c2
        or _git(flow, "status", "--porcelain=v1", "--untracked-files=all", cwd=worktree, evidence=changed)
    ):
        raise creation.binding_failure(DETAIL_BINDING.format(detail="B11 local-only commit is not isolated from C2"))
    flow.require_ledger().record_effect(effect, f"temporary local-only head {temporary} with parent C2 {c2}")
    try:
        expected_error = f"stamp: the worktree branch head {temporary} differs from {c2}"
        _b11_refused_stamp(
            flow,
            w2,
            B11_TRIGGER_WORKTREE,
            B11_WORKTREE_ARGV,
            B11_STAMP_WORKTREE,
            "go_worktree",
            c2,
            expected_error,
            snapshot,
            parsed_log,
            current_refs,
        )
    except BaseException:
        flow.retain(flow_module.RETAINED_MARKER.format(path=flow.root))
        raise
    try:
        _b11_restore_local_head(flow, worktree, effect, c2, temporary, snapshot, parsed_log, original_refs, evidence)
    except BaseException:
        flow.retain(flow_module.RETAINED_MARKER.format(path=flow.root))
        raise


def _exercise_b11_stamp_refusals(
    flow: flow_module.WorkflowFlow, w2: str, builder: str, c2: str, worktree: Path
) -> None:
    _b11_unclean_probe(flow, w2, builder, c2, worktree)
    _b11_worktree_head_probe(flow, w2, c2, worktree)


def _observe_integrators(
    flow: flow_module.WorkflowFlow, baseline: creation.SessionView, w2: str, builder: str
) -> list[str]:
    startup: list[flow_module.JsonValue] = []
    evidence: flow_module.MutableJson = {
        "started_ns": time.monotonic_ns(),
        "finished_ns": None,
        "baseline_ids": list[flow_module.JsonValue](sorted(baseline.ids)),
        "excluded_ids": [w2, builder],
        "startup": startup,
        "inert_item": None,
    }
    flow.public_integrator_evidence = evidence
    deadline = time.monotonic() + 120.0
    observed: dict[str, str] = {}
    while time.monotonic() < deadline:
        for session in flow.observer.sessions(retain=False).ids - baseline.ids:
            if session in observed or session in (w2, builder):
                continue
            record = flow.session_record(session, retain=False)
            if record.get(FIELD_ROLE) != ROLE_INTEGRATOR:
                _fail(f"unexpected B5 session {session}: {record!r}")
            record, _launch, _role = _startup(
                flow, session, ROLE_INTEGRATOR, flow_module.PROC_INTEGRATE, activation=False
            )
            if record.get(FIELD_INITIATOR) not in (None, ""):
                _fail(f"standing integrator {session} has an initiator: {record!r}")
            _, control_launch = flow.control_for_session(session)
            startup.append(
                {
                    "session_id": session,
                    "record": cast(flow_module.JsonValue, dict(record)),
                    "launch": cast(flow_module.JsonValue, dict(_launch)),
                    "control_launch": cast(flow_module.JsonValue, dict(control_launch)),
                }
            )
            observed[session] = ROLE_INTEGRATOR
            flow.record_session(session, ROLE_INTEGRATOR)
        if observed:
            break
        time.sleep(POLL_SECONDS)
    if not observed:
        raise creation.binding_failure(DETAIL_INTEGRATOR)
    time.sleep(30.0)
    current = flow.item()
    evidence["inert_item"] = cast(flow_module.JsonValue, dict(current))
    standing = current.get("standing")
    state = current.get("state")
    if (
        not isinstance(standing, Mapping)
        or standing.get(FIELD_STANDING_PHASE) != flow_module.READY_PHASE
        or FIELD_ADMITTED in standing
        or not isinstance(state, Mapping)
        or state.get(FIELD_PHASE) != flow_module.READY_PHASE
    ):
        _fail(f"an inert integrator changed the unadmitted ready item: {current!r}")
    evidence["finished_ns"] = time.monotonic_ns()
    return sorted(observed)


def _move_head(flow: flow_module.WorkflowFlow, worktree: Path) -> str:
    commit = flow.host.process(
        ("git", "commit", "--allow-empty", "-m", "chore(b5): owner moves the head"),
        worktree,
        flow.host.environment,
        FRAME_SECONDS,
    )
    if commit.exit_status != 0:
        _fail(f"owner commit failed: {commit.output[-300:]}")
    push = flow.host.process(
        ("git", "push", flow_module.ORIGIN, f"HEAD:refs/heads/{flow_module.ITEM}"),
        worktree,
        flow.host.environment,
        FRAME_SECONDS,
    )
    if push.exit_status != 0:
        _fail(f"owner push failed: {push.output[-300:]}")
    head = _git(flow, "rev-parse", "HEAD", cwd=worktree)
    if not _git(flow, "ls-remote", flow_module.ORIGIN, f"refs/heads/{flow_module.ITEM}").startswith(head):
        _fail(f"owner head {head} was not published")
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        item = flow.item()
        standing = item.get("standing")
        if (
            isinstance(standing, Mapping)
            and standing.get(FIELD_STANDING_PHASE) == flow_module.WORK_PHASE
            and FIELD_READY_COMMIT not in standing
        ):
            return head
        time.sleep(POLL_SECONDS)
    _fail("the stale ready item did not read as work after the branch head moved")


def _restamp(flow: flow_module.WorkflowFlow, commit: str, known_claims: int) -> tuple[str, str]:
    baseline = flow.observer.sessions()
    attempt = flow.require_ledger().begin(flow_module.SFC_CHAIN_B5, "w3-start", start_ledger.RECORD_OPERATION)
    outcome = flow.observer.run((TELEC, TODO, WORK, flow_module.ITEM))
    receipt = foundation.json_object(outcome.output)
    operation = receipt.get(FIELD_OPERATION) if receipt is not None else None
    if outcome.exit_status != 0 or not isinstance(operation, str) or not operation:
        flow.require_ledger().unknown(attempt)
        raise creation.binding_failure(DETAIL_BINDING.format(detail=outcome.output[-300:]))
    flow.require_ledger().record_operation(attempt, operation)
    terminal = flow.operation(operation, START_SECONDS)
    if terminal.get(FIELD_STATE) != STATE_COMPLETED:
        _fail(
            DETAIL_STATE.format(operation=operation, state=terminal.get(FIELD_STATE), detail=terminal.get(FIELD_ERROR))
        )
    w3 = flow.plan_actor(PROC_WORK, 2, ROLE_WORK)
    w3_record, w3_launch, w3_role = _startup(flow, w3, ROLE_WORK, PROC_WORK, activation=True)
    case = driver.DriverCase(
        host=flow.host,
        observer=flow.observer,
        journey=flow.journey(w3),
        item=flow_module.ITEM,
        launch_setup=flow.setup_for_session(w3),
        clone=flow.publication.clone,
        baseline=baseline,
        driver_id=PROC_WORK,
        verb=WORK,
        phase=flow_module.WORK_PHASE,
        claim_evidence=flow.claim_input(attempt, w3, flow_module.WORK_PHASE, w3_record, w3_launch),
    )
    case.titles[w3] = case.require_title(w3_record, w3_role)
    instruction = case.claim_call((operation,))
    case.check_instruction(w3, instruction)
    case.observe_claim(w3, known_entries=known_claims + 1)
    claimed = flow.item()
    standing = claimed.get("standing")
    state = claimed.get("state")
    if (
        not isinstance(standing, Mapping)
        or standing.get(FIELD_STANDING_PHASE) != flow_module.WORK_PHASE
        or FIELD_READY_COMMIT in standing
        or not isinstance(state, Mapping)
        or state.get(FIELD_PHASE) != flow_module.WORK_PHASE
        or state.get(FIELD_ACTIVE) != w3
    ):
        _fail(f"W3 claim did not clear the stale ready stamp: {claimed!r}")
    flow.require_ledger().discharge(attempt, "public work start completed and W3 claim was observed")
    success_attempt = flow.require_ledger().begin(flow_module.SFC_CHAIN_B5, "stamp-ok2", start_ledger.RECORD_TRIGGER)
    stamp_before = flow.item()
    stamp_before_log = _public_log(stamp_before)
    evidence = flow.stamp_input(w3, stamp_before, success_attempt)
    after_items = cast(list[flow_module.JsonValue], evidence["after_items"])
    flow.late_argv(
        w3,
        "stamp_ok2.argv",
        (TELEC, TODO, ACT, flow_module.ITEM, "stamp", "--sha", commit, LANE_TWO),
    )
    flow.gate(w3, "go_ok2")
    _, stamped = _operation_command(flow, w3, "stamp_ok2", success_attempt, evidence=evidence)
    if stamped.get(FIELD_STATE) != STATE_COMPLETED or not str(stamped.get(FIELD_RESULT, "")).startswith(
        f"Stamped {flow_module.ITEM} at {commit}"
    ):
        _fail(f"re-stamp did not complete at {commit}: {stamped!r}")
    _expect_log_append(flow, stamp_before_log, ROLE_WORK, w3, "stamp", commit, LANE_TWO, items=after_items)
    ready = flow.item(evidence=after_items)
    ready_standing = ready.get("standing")
    ready_state = ready.get("state")
    if (
        not isinstance(ready_standing, Mapping)
        or ready_standing.get(FIELD_STANDING_PHASE) != "ready"
        or ready_standing.get(FIELD_READY_COMMIT) != commit
        or not isinstance(ready_state, Mapping)
        or ready_state.get(FIELD_ACTIVE) not in (None, "")
    ):
        _fail(f"re-stamp did not restore unadmitted ready at {commit}: {ready!r}")
    ready_since = ready_standing.get("ready_since")
    if not isinstance(ready_since, str) or not ready_since:
        raise creation.binding_failure("B10 requires the public C3 ready_since witness before B7 handover")
    evidence["finished_ns"] = time.monotonic_ns()
    case.require_title_stable(w3)
    _end(flow, w3)
    flow.sessions[w3] = ROLE_WORK
    return w3, ready_since


def run_b5(flow: flow_module.WorkflowFlow) -> None:
    """Run B5 through the first work claim, review acts and stamp gate assertions."""
    try:
        item = flow.item()
        state = item.get("state")
        standing = item.get("standing")
        if (
            not isinstance(state, Mapping)
            or not isinstance(standing, Mapping)
            or (
                state.get(FIELD_PHASE) != flow_module.WORK_PHASE
                or state.get(FIELD_ACTIVE) not in (None, "")
                or standing.get(FIELD_STANDING_PHASE) != flow_module.WORK_PHASE
            )
        ):
            raise creation.binding_failure(DETAIL_PRECONDITION.format(item=item))
        baseline, worktree, w2, builder, operation, parent_id, known_claims, w2_case = _start_work(flow)
        commit_one, commit_two, finding_key = _build_and_review(flow, worktree, w2, builder, operation)
        ready_since_c2 = _exercise_stamps(flow, w2, builder, commit_one, commit_two)
        integrators = _observe_integrators(flow, baseline, w2, builder)
        w2_case.require_title_stable(w2)
        _end(flow, w2)
        commit_three = _move_head(flow, worktree)
        # _start_work already checked the original completed start and observed W2's claim; _end checked closure.
        # No later start has been issued. The original ledger records stay open until their existing discharge below.
        creation.require_b14_kickback(
            flow.observer, TELEC, flow_module.ITEM, creation.B14Case.STALE_WORK_UNCLAIMED, closed_driver=w2
        )
        w3, ready_since_c3 = _restamp(flow, commit_three, known_claims)
        _end(flow, builder)
        flow.require_ledger().discharge(parent_id, "public start completed and claim session observed")
        child_id = next(key for key, value in flow.require_ledger().attempts.items() if value.label == "w2-child")
        flow.require_ledger().discharge(child_id, "builder session retained record closed")
        flow.sessions[w2] = ROLE_WORK
        flow.sessions[builder] = ROLE_BUILDER
        flow.sessions.update({session: ROLE_INTEGRATOR for session in integrators})
        if flow.event_window is None:
            raise creation.binding_failure(DETAIL_BINDING.format(detail="B10 event window was not imported"))
        event_seal = workflow_events.append_case(
            flow.event_window,
            "B5",
            {
                "w2": w2,
                "builder": builder,
                "w3": w3,
                "integrators": integrators,
                "C1": commit_one,
                "C2": commit_two,
                "C3": commit_three,
                "finding_key": finding_key,
                "ready_since_C2": ready_since_c2,
                "ready_since_C3": ready_since_c3,
                "lane_one": LANE_ONE,
                "lane_two": LANE_TWO,
            },
            previous_case="B4",
            expected_previous_seal=flow.event_previous_seal,
        )
        flow.event_case_seal = event_seal
        flow.handover(
            flow_module.SFC_CHAIN_B5,
            flow_module.SFC_CHAIN_B7 if flow_module.SFC_CHAIN_B7 in flow.chain else flow_module.SFC_CHAIN_B5,
            {
                "w2": w2,
                "w3": w3,
                "builder": builder,
                "integrators": cast(flow_module.JsonValue, integrators),
                "C1": commit_one,
                "C2": commit_two,
                "C3": commit_three,
            },
        )
        if flow_module.SFC_CHAIN_B7 not in flow.chain:
            flow.finalize()
    except BaseException as error:
        flow.finalize(str(error))
        raise
