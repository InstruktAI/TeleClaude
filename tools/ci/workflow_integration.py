"""Approved B6 integration and delivery observations on the shared native workflow flow."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Final

from tools.ci import workflow_creation as creation
from tools.ci import workflow_flow as flow_module
from tools.ci import workflow_ledger as start_ledger
from tools.ci import workflow_publication as publication
from tools.ci.workflow_prepared import text_capability_enabled
from tools.ci.workflow_review import (
    FIELD_ACTIVE,
    FIELD_ERROR,
    FIELD_OPERATION,
    FIELD_PHASE,
    FIELD_READY_COMMIT,
    FIELD_RESULT,
    FIELD_STATE,
    FRAME_SECONDS,
    ROLE_INTEGRATOR,
    START_SECONDS,
    STATE_COMPLETED,
    STATE_FAILED,
    TELEC,
    TODO,
    _end,
    _fail,
    _frame_success,
)

INTEGRATION_TREE: Final = "trees/_integration"
FEATURE_FILE: Final = "feature.txt"
MAKE_FILE: Final = "Makefile"
EXPECTED_FEATURE: Final = b"b5 file one\nb5 file two\n"
EXPECTED_MAKEFILE: Final = b"test:\n\t@true\n"
FIELD_ADMITTED: Final = "admitted"
FIELD_STANDING: Final = "standing"
FIELD_STANDING_PHASE: Final = "phase"
FIELD_STATUS: Final = "stage"
FIELD_ROADMAP: Final = "roadmap"
FIELD_DELIVERED: Final = "delivered"
FIELD_DELIVERED_COMMIT: Final = "delivered_commit"
FIELD_DELIVERED_AT: Final = "delivered_at"
DETAIL_HANDOVER: Final = "B6 did not receive the approved B7 handover"
DETAIL_ACTOR: Final = "no integrator session owns the first integrate plan claim"
DETAIL_DIRTY: Final = "the root worktree has an overlapping or unclassified dirty path: {status!r}"
DETAIL_INTEGRATION: Final = "integration worktree read-back differs: {found!r}; expected {expected!r}"
DETAIL_OPERATION: Final = "operation {operation} ended {state!r}: {detail!r}"
DETAIL_DELIVERED: Final = "the completed integration did not deliver the item at the expected main commit: {item!r}"
DETAIL_COMMIT: Final = "integration commit {found!r} does not match expected {expected!r}"


def _git(flow: flow_module.WorkflowFlow, *args: str, cwd: Path | None = None) -> str:
    return flow.git(args, cwd=cwd)


def _operation_result(flow: flow_module.WorkflowFlow, session: str, name: str, label: str) -> Mapping[str, object]:
    attempt = flow.require_ledger().begin(flow_module.SFC_CHAIN_B6, label, start_ledger.RECORD_TRIGGER)
    flow.gate(session, f"go_{name}")
    frame = _frame_success(flow, session, name)
    raw_run = frame.get("run")
    run = raw_run if isinstance(raw_run, Mapping) else {}
    receipt = creation.decode_object(str(run.get("stdout", "")))
    operation = receipt.get(FIELD_OPERATION) if receipt is not None else None
    if not isinstance(operation, str) or not operation:
        flow.require_ledger().unknown(attempt)
        raise creation.binding_failure(f"{name} returned no public operation receipt")
    flow.require_ledger().record_operation(attempt, operation)
    return publication.await_terminal(flow.observer, operation, START_SECONDS)


def _acting_integrator(flow: flow_module.WorkflowFlow) -> str:
    matches: list[str] = []
    for session in flow.observer.sessions(retain=False).ids:
        record = flow.session_record(session, retain=False)
        if record.get("role") != ROLE_INTEGRATOR:
            continue
        _setup, launch = flow.control_for_session(session)
        if (
            launch.get("key_kind") == "procedure"
            and launch.get("key") == flow_module.procedure_key(flow_module.PROC_INTEGRATE)
            and launch.get("index") == 1
        ):
            matches.append(session)
    if len(matches) != 1:
        raise creation.binding_failure(DETAIL_ACTOR)
    return matches[0]


def _refused_work(
    flow: flow_module.WorkflowFlow, baseline_item: Mapping[str, object], sessions: frozenset[str]
) -> None:
    attempt = flow.require_ledger().begin(flow_module.SFC_CHAIN_B6, "refused-work", start_ledger.RECORD_OPERATION)
    outcome = flow.observer.run((TELEC, TODO, "work", flow_module.ITEM))
    receipt = creation.decode_object(outcome.output) if outcome.exit_status == 0 else None
    operation = receipt.get(FIELD_OPERATION) if receipt is not None else None
    if outcome.exit_status != 0 or not isinstance(operation, str) or not operation:
        flow.require_ledger().unknown(attempt)
        raise creation.binding_failure(f"admission refusal returned no receipt: {outcome.output[-300:]}")
    flow.require_ledger().record_operation(attempt, operation)
    terminal = publication.await_terminal(flow.observer, operation, START_SECONDS)
    error = terminal.get(FIELD_ERROR)
    if (
        terminal.get(FIELD_STATE) != STATE_FAILED
        or not isinstance(error, str)
        or "admitted by the integrator" not in error
    ):
        _fail(f"admitted work entry was not refused by the admission door: {terminal!r}")
    if flow_module.ITEM not in error:
        _fail(f"admission refusal did not name {flow_module.ITEM}: {error!r}")
    standing_before = baseline_item.get(FIELD_STANDING)
    candidate = standing_before.get(FIELD_READY_COMMIT) if isinstance(standing_before, Mapping) else None
    if not isinstance(candidate, str) or candidate not in error:
        _fail(f"admission refusal did not name the admitted commit: {error!r}")
    if flow.item() != baseline_item or flow.observer.sessions().ids != sessions:
        _fail("the admitted work refusal changed the item or created a session")
    flow.require_ledger().discharge(attempt, "public admission refusal completed without a session or item mutation")


def _verify_staged(flow: flow_module.WorkflowFlow, integration: Path, base: str) -> None:
    head = _git(flow, "rev-parse", "HEAD", cwd=integration)
    status = _git(flow, "status", "--porcelain", cwd=integration)
    if head != base or "A  feature.txt" not in status or "A  Makefile" not in status:
        _fail(
            DETAIL_INTEGRATION.format(
                found={"head": head, "status": status}, expected={"head": base, "staged": "feature.txt, Makefile"}
            )
        )
    if _git(flow, "ls-remote", flow_module.ORIGIN, "refs/heads/main") != f"{base}\trefs/heads/main":
        _fail("int1 moved origin/main before the integration commit")


def _verify_docs_only_capability(flow: flow_module.WorkflowFlow, integration: Path) -> None:
    root_head = _git(flow, "show", "HEAD:teleclaude.yml")
    root_worktree = (flow.project / "teleclaude.yml").read_text(encoding="utf-8")
    integration_worktree = (integration / "teleclaude.yml").read_text(encoding="utf-8")
    for label, text in (
        ("root HEAD", root_head),
        ("root worktree", root_worktree),
        ("integration worktree", integration_worktree),
    ):
        if not text_capability_enabled(text, "docs") or text_capability_enabled(text, "code"):
            raise creation.binding_failure(f"{label} is not docs-enabled with code disabled")


def _verify_integration_commit(flow: flow_module.WorkflowFlow, integration: Path, base: str, session: str) -> str:
    head = _git(flow, "rev-parse", "HEAD", cwd=integration)
    parent = _git(flow, "rev-parse", "HEAD^", cwd=integration)
    subject = _git(flow, "show", "-s", "--format=%s", "HEAD", cwd=integration)
    feature = flow.host.process(
        ("git", "show", f"{head}:{FEATURE_FILE}"), integration, flow.host.environment, FRAME_SECONDS
    )
    makefile = flow.host.process(
        ("git", "show", f"{head}:{MAKE_FILE}"), integration, flow.host.environment, FRAME_SECONDS
    )
    if (
        head == base
        or parent != base
        or subject != flow_module.B6_COMMIT
        or feature.exit_status != 0
        or feature.output.encode("utf-8") != EXPECTED_FEATURE
        or makefile.exit_status != 0
        or makefile.output.encode("utf-8") != EXPECTED_MAKEFILE
    ):
        _fail(
            DETAIL_INTEGRATION.format(
                found={"head": head, "parent": parent, "subject": subject},
                expected={
                    "parent": base,
                    "subject": flow_module.B6_COMMIT,
                    "feature": EXPECTED_FEATURE.decode(),
                    "Makefile": EXPECTED_MAKEFILE.decode(),
                },
            )
        )
    message = _git(flow, "show", "-s", "--format=%B", "HEAD", cwd=integration)
    if f"Session: {session}" not in message:
        _fail(f"integration commit does not carry the acting session trailer: {message!r}")
    return head


def run_b6(flow: flow_module.WorkflowFlow) -> None:
    """Select the atomic integrate-plan claimant, admit, squash, publish and verify delivery."""
    try:
        manifest = flow.verify_manifest()
        if manifest.get("last_completed_case") != flow_module.SFC_CHAIN_B7:
            raise creation.binding_failure(DETAIL_HANDOVER)
        flow.begin_case(flow_module.SFC_CHAIN_B6, flow_module.B6_ACTIONS)
        item_before = flow.item()
        standing = item_before.get(FIELD_STANDING)
        if not isinstance(standing, Mapping) or standing.get(FIELD_STANDING_PHASE) != flow_module.READY_PHASE:
            raise creation.binding_failure(DETAIL_HANDOVER)
        candidate = standing.get(FIELD_READY_COMMIT)
        if not isinstance(candidate, str) or not candidate:
            raise creation.binding_failure(DETAIL_HANDOVER)
        integration = flow.project / INTEGRATION_TREE
        if not integration.is_dir():
            raise creation.binding_failure(DETAIL_HANDOVER)
        dirty = _git(flow, "status", "--porcelain")
        if FEATURE_FILE in dirty or MAKE_FILE in dirty:
            _fail(DETAIL_DIRTY.format(status=dirty))
        base = _git(flow, "rev-parse", "origin/main")
        if _git(flow, "ls-remote", flow_module.ORIGIN, "refs/heads/main") != f"{base}\trefs/heads/main":
            _fail("origin/main and the local origin/main read differ before admission")
        _verify_docs_only_capability(flow, integration)
        actor = _acting_integrator(flow)
        admission = _operation_result(flow, actor, "int1", "int1")
        if (
            admission.get(FIELD_STATE) != STATE_COMPLETED
            or not isinstance(admission.get(FIELD_RESULT), str)
            or not admission.get(FIELD_RESULT)
        ):
            _fail(
                DETAIL_OPERATION.format(
                    operation="int1", state=admission.get(FIELD_STATE), detail=admission.get(FIELD_ERROR)
                )
            )
        admitted = flow.item()
        admitted_standing = admitted.get(FIELD_STANDING)
        state = admitted.get("state")
        if (
            not isinstance(admitted_standing, Mapping)
            or admitted_standing.get(FIELD_ADMITTED) is None
            or not isinstance(admitted_standing.get(FIELD_ADMITTED), Mapping)
            or admitted_standing[FIELD_ADMITTED].get("commit") != candidate
            or not isinstance(state, Mapping)
            or state.get(FIELD_PHASE) != flow_module.READY_PHASE
            or state.get(FIELD_ACTIVE) not in (None, "")
        ):
            _fail(f"int1 did not admit the B7 candidate at {candidate}: {admitted!r}")
        _verify_staged(flow, integration, base)
        sessions = flow.observer.sessions().ids
        _refused_work(flow, admitted, sessions)
        flow.gate(actor, "go_commit")
        commit_frame = _frame_success(flow, actor, "commit_int")
        del commit_frame
        integrated_head = _verify_integration_commit(flow, integration, base, actor)
        if _git(flow, "ls-remote", flow_module.ORIGIN, "refs/heads/main") != f"{base}\trefs/heads/main":
            _fail("integration commit was published before the delivery gate")
        delivery_operation = _operation_result(flow, actor, "int2", "int2")
        if (
            delivery_operation.get(FIELD_STATE) != STATE_COMPLETED
            or not isinstance(delivery_operation.get(FIELD_RESULT), str)
            or not delivery_operation.get(FIELD_RESULT)
        ):
            _fail(
                DETAIL_OPERATION.format(
                    operation="int2",
                    state=delivery_operation.get(FIELD_STATE),
                    detail=delivery_operation.get(FIELD_ERROR),
                )
            )
        remote_main = _git(flow, "ls-remote", flow_module.ORIGIN, "refs/heads/main")
        main_head = remote_main.split()[0] if remote_main.split() else ""
        delivered = flow.item()
        roadmap = delivered.get(FIELD_ROADMAP)
        if (
            main_head == base
            or _git(flow, "rev-parse", "main") != main_head
            or delivered.get(FIELD_STATUS) != FIELD_DELIVERED
            or not isinstance(roadmap, Mapping)
            or roadmap.get(FIELD_DELIVERED) != FIELD_DELIVERED
            or roadmap.get(FIELD_DELIVERED_COMMIT) != main_head
            or not isinstance(roadmap.get(FIELD_DELIVERED_AT), str)
            or not roadmap.get(FIELD_DELIVERED_AT)
            or _git(flow, "rev-parse", f"{main_head}^") != base
            or _git(flow, "show", f"{main_head}:{FEATURE_FILE}").encode("utf-8") != EXPECTED_FEATURE
            or _git(flow, "show", f"{main_head}:{MAKE_FILE}").encode("utf-8") != EXPECTED_MAKEFILE
        ):
            _fail(DETAIL_DELIVERED.format(item=delivered))
        listing = flow.observer.run((TELEC, TODO, "list", "--json", "--include-delivered"))
        payload = creation.decode_object(listing.output) if listing.exit_status == 0 else None
        delivered_section = payload.get("delivered") if payload is not None else None
        active_section = payload.get("active") if payload is not None else None
        if (
            not isinstance(delivered_section, list)
            or flow_module.ITEM not in creation.collect_slugs(delivered_section)
            or flow_module.ITEM in creation.collect_slugs(active_section)
        ):
            _fail("public todo list did not move the item from active to delivered")
        _end(flow, actor)
        flow.sessions[actor] = ROLE_INTEGRATOR
        flow.handover(
            flow_module.SFC_CHAIN_B6,
            flow_module.SFC_CHAIN_B6,
            {
                "integrator": actor,
                "M0": base,
                "C3": candidate,
                "integration_commit": integrated_head,
                "delivered_main": main_head,
            },
        )
        flow.finalize()
    except BaseException as error:
        flow.finalize(str(error))
        raise
