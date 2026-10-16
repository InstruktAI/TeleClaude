"""Approved B5 black-box workflow journey on the shared B5/B7/B6 flow."""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Final, NoReturn, cast

from tools.ci import workflow_creation as creation
from tools.ci import workflow_driver as driver
from tools.ci import workflow_flow as flow_module
from tools.ci import workflow_foundation as foundation
from tools.ci import workflow_ledger as start_ledger
from tools.ci import workflow_publication as publication

TELEC: Final = "telec"
TODO: Final = "todo"
WORK: Final = "work"
ACT: Final = "act"
SHOW: Final = "show"
OPERATIONS: Final = "operations"
GET: Final = "get"
FIELD_OPERATION: Final = "operation_id"
FIELD_JOB: Final = "job"
FIELD_STATE: Final = "state"
FIELD_RESULT: Final = "result"
FIELD_ERROR: Final = "error"
FIELD_ROLE: Final = "role"
FIELD_NATIVE: Final = "native_session_id"
FIELD_INITIATOR: Final = "initiator_session_id"
FIELD_PROJECT: Final = "project_path"
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
POLL_SECONDS: Final = 2.0
START_SECONDS: Final = 900.0
OPERATION_SECONDS: Final = 300.0
FRAME_SECONDS: Final = 60.0
DETAIL_BINDING: Final = "B5 evidence did not bind to the shared flow: {detail}"
DETAIL_PLATFORM: Final = "B5 platform assertion failed: {detail}"
DETAIL_FRAME: Final = "fixture command {name} did not succeed: {frame!r}"
DETAIL_STATE: Final = "operation {operation} ended in {state!r}: {detail!r}"
DETAIL_KEY: Final = "finding returned no key: {result!r}"
DETAIL_PRECONDITION: Final = "B5 began outside the approved unclaimed work state: {item!r}"
DETAIL_WRITE_SCOPE: Final = "builder launch cwd and public project_path do not name the owned worktree"
DETAIL_INTEGRATOR: Final = "no started integrator has a public session record and mapped native control"


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
    state = publication.await_terminal(flow.observer, identifier, OPERATION_SECONDS)
    return identifier, state


def _frame_success(
    flow: flow_module.WorkflowFlow, session: str, name: str, *, writes: bool = False
) -> Mapping[str, object]:
    frame = flow.frame(session, f"cmd_{name}", FRAME_SECONDS)
    if writes:
        if frame.get("ok") is not True:
            _fail(DETAIL_FRAME.format(name=name, frame=frame))
        return frame
    run = frame.get("run")
    if not isinstance(run, Mapping) or run.get("exit_status") != 0 or run.get("timed_out") is True:
        _fail(DETAIL_FRAME.format(name=name, frame=frame))
    return frame


def _git(flow: flow_module.WorkflowFlow, *arguments: str, cwd: Path | None = None) -> str:
    return flow.git(arguments, cwd=cwd)


def _startup(
    flow: flow_module.WorkflowFlow, session: str, expected_role: str, procedure: str
) -> tuple[Mapping[str, object], Mapping[str, object]]:
    record = flow.session_record(session)
    _setup, launch = flow.control_for_session(session)
    if record.get(FIELD_ROLE) != expected_role or record.get(FIELD_JOB) != procedure:
        _fail(f"session {session} role/job mismatch: {record!r}")
    native = record.get(FIELD_NATIVE)
    if not isinstance(native, str) or launch.get(FIELD_NATIVE) != native:
        raise creation.binding_failure(DETAIL_BINDING.format(detail="native session identity mismatch"))
    journey = flow.journey(session)
    deadline = time.monotonic() + START_SECONDS
    for hook in (foundation.FRAME_SESSION_START, foundation.FRAME_PROMPT_SUBMIT):
        journey.require_hook(hook, journey.await_frame(hook, deadline))
    if not journey.started(record, native):
        _fail(f"session {session} is not publicly observed as started")
    first_inputs = journey.inputs()
    first = first_inputs[0].get("text") if first_inputs else None
    if not isinstance(first, str) or not first.startswith(f"TELECLAUDE COMMAND: {procedure}"):
        _fail(f"session {session} first prompt does not name {procedure}: {first!r}")
    return record, launch


def _run_command(
    flow: flow_module.WorkflowFlow, session: str, frame_name: str
) -> tuple[Mapping[str, object], Mapping[str, object]]:
    frame = _frame_success(flow, session, frame_name)
    _, terminal = _operation(flow, frame, frame_name)
    return frame, terminal


def _end(flow: flow_module.WorkflowFlow, session: str) -> None:
    current = flow.session_record(session)
    if current.get("closed_at") is not None and current.get("lifecycle_status") == "closed":
        return
    outcome = flow.observer.run((TELEC, "sessions", "end", session))
    receipt = foundation.json_object(outcome.output)
    operation = receipt.get(FIELD_OPERATION) if receipt is not None else None
    if outcome.exit_status != 0 or not isinstance(operation, str) or not operation:
        raise creation.binding_failure(DETAIL_BINDING.format(detail=f"sessions end {session}: {outcome.output[-300:]}"))
    terminal = publication.await_terminal(flow.observer, operation, START_SECONDS)
    if terminal.get(FIELD_STATE) != STATE_COMPLETED:
        _fail(
            DETAIL_STATE.format(operation=operation, state=terminal.get(FIELD_STATE), detail=terminal.get(FIELD_ERROR))
        )
    record = flow.session_record(session)
    if record.get("closed_at") is None or record.get("lifecycle_status") != "closed":
        _fail(f"session {session} end lacks a retained closed record: {record!r}")


def _start_work(
    flow: flow_module.WorkflowFlow,
) -> tuple[creation.SessionView, Path, str, str, str, str, int]:
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
    outcome = flow.observer.run((TELEC, TODO, WORK, flow_module.ITEM))
    receipt = foundation.json_object(outcome.output)
    operation = receipt.get(FIELD_OPERATION) if receipt is not None else None
    if outcome.exit_status != 0 or not isinstance(operation, str) or not operation:
        flow.require_ledger().unknown(parent_id)
        raise creation.binding_failure(DETAIL_BINDING.format(detail=outcome.output[-300:]))
    flow.require_ledger().record_operation(parent_id, operation)
    terminal = publication.await_terminal(flow.observer, operation, START_SECONDS)
    if terminal.get(FIELD_STATE) != STATE_COMPLETED:
        _fail(
            DETAIL_STATE.format(operation=operation, state=terminal.get(FIELD_STATE), detail=terminal.get(FIELD_ERROR))
        )
    w2 = flow.plan_actor(PROC_WORK, 1, ROLE_WORK)
    _startup(flow, w2, ROLE_WORK, PROC_WORK)
    child_frame = _frame_success(flow, w2, "child")
    child_run = child_frame.get("run")
    child_stdout = child_run.get("stdout") if isinstance(child_run, Mapping) else None
    match = re.search(r"Started sdlc/procedure/lifecycle/work/build-v2 as session ([A-Za-z0-9_-]+)", child_stdout or "")
    if not isinstance(child_stdout, str) or match is None:
        _fail(f"B5 builder child start text is absent: {child_frame!r}")
    builder = match.group(1)
    flow.require_ledger().record_session(child_attempt, builder)
    builder_record, builder_launch = _startup(flow, builder, ROLE_BUILDER, PROC_BUILD)
    if builder_record.get(FIELD_INITIATOR) != w2:
        _fail(f"builder initiator is {builder_record.get(FIELD_INITIATOR)!r}, not {w2}")
    if builder_record.get(FIELD_PROJECT) != str(worktree.resolve()) or builder_launch.get("cwd") != str(
        worktree.resolve()
    ):
        raise creation.binding_failure(DETAIL_WRITE_SCOPE)
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
    )
    instruction = case.claim_call((operation,))
    case.check_instruction(w2, instruction)
    case.observe_claim(w2, known_entries=known_claims)
    return baseline, worktree, w2, builder, operation, parent_id, known_claims


def _build_and_review(
    flow: flow_module.WorkflowFlow, worktree: Path, w2: str, builder: str, operation: str
) -> tuple[str, str, str]:
    flow.gate(builder, "go_w1")
    write_frame = _frame_success(flow, builder, "write1", writes=True)
    if write_frame.get("cwd") != str(worktree.resolve()):
        raise creation.binding_failure(DETAIL_WRITE_SCOPE)
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
        or body.strip() != flow_module.B5_COMMIT_1
        or f"Session: {builder}" not in body
        or author == "Runtime Acceptance Fixture"
        or count != "2"
    ):
        _fail(f"sealed builder commit {commit_one} did not publish the branch: {remote_one!r}")
    flow.late_argv(w2, "reviewed.argv", (TELEC, TODO, ACT, flow_module.ITEM, "reviewed", "--sha", commit_one))
    flow.gate(w2, "go_rev")
    _, reviewed = _run_command(flow, w2, "reviewed")
    if reviewed.get(FIELD_STATE) != STATE_COMPLETED:
        _fail(f"reviewed operation failed: {reviewed!r}")
    flow.late_argv(
        w2, "finding.argv", (TELEC, TODO, ACT, flow_module.ITEM, "finding", "--sha", commit_one, FINDING_TEXT)
    )
    flow.gate(w2, "go_find")
    _, finding = _run_command(flow, w2, "finding")
    if finding.get(FIELD_STATE) != STATE_COMPLETED:
        _fail(f"finding operation failed: {finding!r}")
    key_match = re.search(r"finding key:\s*(\S+)", str(finding.get(FIELD_RESULT, "")))
    if key_match is None:
        _fail(DETAIL_KEY.format(result=finding.get(FIELD_RESULT)))
    finding_key = key_match.group(1)
    flow.late_argv(
        builder, "reply.argv", (TELEC, TODO, ACT, flow_module.ITEM, "reply", "--finding", finding_key, REPLY_TEXT)
    )
    flow.gate(builder, "go_reply")
    _, reply = _run_command(flow, builder, "reply")
    if reply.get(FIELD_STATE) != STATE_COMPLETED:
        _fail(f"reply operation failed: {reply!r}")
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


def _exercise_stamps(flow: flow_module.WorkflowFlow, w2: str, commit_one: str, commit_two: str) -> None:
    worktree = flow.project / flow_module.WORKTREE_DIRECTORY / flow_module.ITEM
    snapshot = flow.item()
    refs = (
        _git(flow, "ls-remote", flow_module.ORIGIN, f"refs/heads/{flow_module.ITEM}"),
        _git(flow, "rev-parse", "HEAD", cwd=worktree),
        _git(flow, "rev-list", "--count", f"origin/{flow_module.MAIN}..{flow_module.ITEM}", cwd=worktree),
    )
    flow.late_argv(
        w2, "stamp_nonhead.argv", (TELEC, TODO, ACT, flow_module.ITEM, "stamp", "--sha", commit_one, LANE_ONE)
    )
    flow.require_ledger().begin(flow_module.SFC_CHAIN_B5, "stamp-nonhead", start_ledger.RECORD_TRIGGER)
    flow.gate(w2, "go_nh")
    _, rejected = _run_command(flow, w2, "stamp_nonhead")
    error = rejected.get(FIELD_ERROR)
    if (
        rejected.get(FIELD_STATE) != STATE_FAILED
        or not isinstance(error, str)
        or commit_one not in error
        or commit_two not in error
    ):
        _fail(f"non-head stamp did not refuse both refs: {rejected!r}")
    if flow.item() != snapshot:
        _fail("a refused non-head stamp changed the item snapshot")
    time.sleep(5.0)
    if flow.item() != snapshot:
        _fail("a refused non-head stamp changed the item during the stability window")
    current_refs = (
        _git(flow, "ls-remote", flow_module.ORIGIN, f"refs/heads/{flow_module.ITEM}"),
        _git(flow, "rev-parse", "HEAD", cwd=worktree),
        _git(flow, "rev-list", "--count", f"origin/{flow_module.MAIN}..{flow_module.ITEM}", cwd=worktree),
    )
    if current_refs != refs:
        _fail(f"a refused non-head stamp moved the branch refs: {current_refs!r}")
    flow.late_argv(w2, "stamp_empty.argv", (TELEC, TODO, ACT, flow_module.ITEM, "stamp", "--sha", commit_two))
    flow.require_ledger().begin(flow_module.SFC_CHAIN_B5, "stamp-empty", start_ledger.RECORD_TRIGGER)
    flow.gate(w2, "go_empty")
    _, empty = _run_command(flow, w2, "stamp_empty")
    if empty.get(FIELD_STATE) != STATE_FAILED or "lane report" not in str(empty.get(FIELD_ERROR, "")):
        _fail(f"empty stamp did not refuse the missing lane report: {empty!r}")
    if (
        flow.item() != snapshot
        or (
            _git(flow, "ls-remote", flow_module.ORIGIN, f"refs/heads/{flow_module.ITEM}"),
            _git(flow, "rev-parse", "HEAD", cwd=worktree),
            _git(flow, "rev-list", "--count", f"origin/{flow_module.MAIN}..{flow_module.ITEM}", cwd=worktree),
        )
        != refs
    ):
        _fail("empty stamp changed the item or branch refs")
    flow.late_argv(w2, "stamp_ok.argv", (TELEC, TODO, ACT, flow_module.ITEM, "stamp", "--sha", commit_two, LANE_ONE))
    flow.require_ledger().begin(flow_module.SFC_CHAIN_B5, "stamp-ok", start_ledger.RECORD_TRIGGER)
    flow.gate(w2, "go_ok")
    _, stamped = _run_command(flow, w2, "stamp_ok")
    if stamped.get(FIELD_STATE) != STATE_COMPLETED or not str(stamped.get(FIELD_RESULT, "")).startswith(
        f"Stamped {flow_module.ITEM} at {commit_two}"
    ):
        _fail(f"head stamp did not complete at {commit_two}: {stamped!r}")
    shown = flow.item()
    standing = shown.get("standing")
    if (
        not isinstance(standing, Mapping)
        or standing.get(FIELD_STANDING_PHASE) != "ready"
        or standing.get(FIELD_READY_COMMIT) != commit_two
        or FIELD_ADMITTED in standing
    ):
        _fail(f"successful stamp did not produce unadmitted ready at {commit_two}: {shown!r}")


def _observe_integrators(
    flow: flow_module.WorkflowFlow, baseline: creation.SessionView, w2: str, builder: str
) -> list[str]:
    deadline = time.monotonic() + 120.0
    observed: dict[str, str] = {}
    while time.monotonic() < deadline:
        for session in flow.observer.sessions(retain=False).ids - baseline.ids:
            if session in observed or session in (w2, builder):
                continue
            record = flow.session_record(session, retain=False)
            if record.get(FIELD_ROLE) != ROLE_INTEGRATOR:
                _fail(f"unexpected B5 session {session}: {record!r}")
            _startup(flow, session, ROLE_INTEGRATOR, flow_module.PROC_INTEGRATE)
            if record.get(FIELD_INITIATOR) not in (None, ""):
                _fail(f"standing integrator {session} has an initiator: {record!r}")
            flow.control_for_session(session)
            observed[session] = ROLE_INTEGRATOR
            flow.record_session(session, ROLE_INTEGRATOR)
        if observed:
            break
        time.sleep(POLL_SECONDS)
    if not observed:
        raise creation.binding_failure(DETAIL_INTEGRATOR)
    time.sleep(30.0)
    current = flow.item()
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
        if isinstance(standing, Mapping) and standing.get(FIELD_STANDING_PHASE) == flow_module.WORK_PHASE:
            return head
        time.sleep(POLL_SECONDS)
    _fail("the stale ready item did not read as work after the branch head moved")


def _restamp(flow: flow_module.WorkflowFlow, commit: str, known_claims: int) -> str:
    baseline = flow.observer.sessions()
    attempt = flow.require_ledger().begin(flow_module.SFC_CHAIN_B5, "w3-start", start_ledger.RECORD_OPERATION)
    outcome = flow.observer.run((TELEC, TODO, WORK, flow_module.ITEM))
    receipt = foundation.json_object(outcome.output)
    operation = receipt.get(FIELD_OPERATION) if receipt is not None else None
    if outcome.exit_status != 0 or not isinstance(operation, str) or not operation:
        flow.require_ledger().unknown(attempt)
        raise creation.binding_failure(DETAIL_BINDING.format(detail=outcome.output[-300:]))
    flow.require_ledger().record_operation(attempt, operation)
    terminal = publication.await_terminal(flow.observer, operation, START_SECONDS)
    if terminal.get(FIELD_STATE) != STATE_COMPLETED:
        _fail(
            DETAIL_STATE.format(operation=operation, state=terminal.get(FIELD_STATE), detail=terminal.get(FIELD_ERROR))
        )
    w3 = flow.plan_actor(PROC_WORK, 2, ROLE_WORK)
    _startup(flow, w3, ROLE_WORK, PROC_WORK)
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
    )
    instruction = case.claim_call((operation,))
    case.check_instruction(w3, instruction)
    case.observe_claim(w3, known_entries=known_claims + 1)
    flow.require_ledger().discharge(attempt, "work claim completed and held by the mapped W3 session")
    flow.require_ledger().begin(flow_module.SFC_CHAIN_B5, "stamp-ok2", start_ledger.RECORD_TRIGGER)
    flow.gate(w3, "go_ok2")
    _, stamped = _run_command(flow, w3, "stamp_ok2")
    if stamped.get(FIELD_STATE) != STATE_COMPLETED or not str(stamped.get(FIELD_RESULT, "")).startswith(
        f"Stamped {flow_module.ITEM} at {commit}"
    ):
        _fail(f"re-stamp did not complete at {commit}: {stamped!r}")
    _end(flow, w3)
    flow.sessions[w3] = ROLE_WORK
    return w3


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
        baseline, worktree, w2, builder, operation, parent_id, known_claims = _start_work(flow)
        commit_one, commit_two, _ = _build_and_review(flow, worktree, w2, builder, operation)
        _exercise_stamps(flow, w2, commit_one, commit_two)
        integrators = _observe_integrators(flow, baseline, w2, builder)
        _end(flow, w2)
        commit_three = _move_head(flow, worktree)
        w3 = _restamp(flow, commit_three, known_claims)
        _end(flow, builder)
        flow.require_ledger().discharge(parent_id, "public start completed and claim session observed")
        child_id = next(key for key, value in flow.require_ledger().attempts.items() if value.label == "w2-child")
        flow.require_ledger().discharge(child_id, "builder session retained record closed")
        flow.sessions[w2] = ROLE_WORK
        flow.sessions[builder] = ROLE_BUILDER
        flow.sessions.update({session: ROLE_INTEGRATOR for session in integrators})
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
