"""Prepare state machine — phase step handlers and dispatcher.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR, SlashCommand
from teleclaude.core.db import Db
from teleclaude.core.next_machine._types import (
    DEFAULT_MAX_REVIEW_ROUNDS,
    DOR_READY_THRESHOLD,
    PreparePhase,
    StateValue,
)
from teleclaude.core.next_machine.artifacts import compute_artifact_diff, compute_todo_folder_diff
from teleclaude.core.next_machine.git_ops import compose_agent_guidance, run_git_command
from teleclaude.core.next_machine.output_formatting import ToolCallRequest, format_prepared, format_tool_call
from teleclaude.core.next_machine.prepare_events import _emit_prepare_event
from teleclaude.core.next_machine.prepare_scripts import (
    _fix_findings_message,
    _format_review_approved_script,
    _format_review_blocked_script,
    _format_review_needs_work_script,
)
from teleclaude.core.next_machine.state_mutation import GroundingManager, StateWriter
from teleclaude.core.next_machine.worktrees import ensure_worktree_with_policy_async

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb

logger = get_logger(__name__)


def _worker_idle_post_block(slug: str) -> str:
    """Post-block emitted after dispatching a worker — tells the orchestrator to re-enter when idle."""
    return f"WHEN WORKER IDLES:\nCall telec todo prepare {slug}. The state machine emits the next action."


def _reviewer_idle_post_block(slug: str) -> str:
    """Post-block emitted after dispatching a reviewer — reads verdict when idle."""
    return (
        f"WHEN REVIEWER IDLES:\n"
        f"Call telec todo prepare {slug}. The state machine will read the verdict and emit the next action."
    )


def _derive_project_root(cwd: str, slug: str) -> str:
    """Extract canonical project root from an effective cwd that may be a worktree.

    When ``cwd`` is ``{project_root}/trees/{slug}``, returns the project root.
    Otherwise returns ``cwd`` unchanged (already the project root).
    Used for ToolCallRequest.project and worktree creation, which always need the
    project root rather than the worktree path.
    """
    suffix = f"/{WORKTREE_DIR}/{slug}"
    if cwd.endswith(suffix):
        return cwd[: -len(suffix)]
    return cwd


async def _find_live_session_for_slug(
    db: Db,
    slug: str,
    command_prefix: str,
    subdir_override: str | None = None,
) -> str | None:
    """Return the session_id of a live session dispatched for this slug+command.

    Live means closed_at is null. Matches by subdir (defaults to trees/{slug})
    and session title starting with the command prefix (e.g. "/next-review-specs").
    Returns None when no matching live session exists.
    """
    sessions = await db.list_sessions(include_closed=False)
    expected_subdir = subdir_override if subdir_override is not None else f"{WORKTREE_DIR}/{slug}"
    for session in sessions:
        if session.subdir != expected_subdir:
            continue
        title = (session.title or "").lstrip()
        if title.startswith(command_prefix):
            return session.session_id
    return None


async def _find_all_live_sessions_for_slug(
    db: Db,
    slug: str,
    subdir_override: str | None = None,
) -> list[str]:
    """Return all live session_ids dispatched for this slug, regardless of command."""
    sessions = await db.list_sessions(include_closed=False)
    expected_subdir = subdir_override if subdir_override is not None else f"{WORKTREE_DIR}/{slug}"
    return [s.session_id for s in sessions if s.subdir == expected_subdir]


async def _commit_writer(
    writer: StateWriter,
    todos_db: TodosDb,
    slug: str,
    state: dict[str, StateValue],
) -> None:
    """Commit the writer and sync the validated payload back to *state*.

    The prepare dispatcher and its callers continue to read from the in-memory
    state dict after each step, so we refresh that dict from the validated
    commit payload. Persistence itself is still the typed-boundary writer.
    """
    payload = await writer.commit(todos_db, slug)
    state.clear()
    state.update(payload)


async def _prepare_step_input_assessment(
    db: Db,
    todos_db: TodosDb,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """INPUT_ASSESSMENT: choose requirements strategy and produce requirements."""
    # Ensure worktree exists from the very first prepare step so all phases
    # write state to the worktree, not repo root main.
    await ensure_worktree_with_policy_async(_derive_project_root(cwd, slug), slug)

    writer = StateWriter(state)
    writer.audit.input_assessment.started_at = datetime.now(UTC).isoformat()

    has_requirements = await todos_db.artifact_exists(slug, "requirements")
    if has_requirements:
        # Emit input_consumed event for observability (R13)
        input_digest = await todos_db.artifact_digest(slug, "input")
        _emit_prepare_event(
            "domain.software-development.prepare.input_consumed",
            {"slug": slug, "phase": "input_assessment", "digest": input_digest},
        )
        writer.audit.input_assessment.completed_at = datetime.now(UTC).isoformat()
        await _commit_writer(writer, todos_db, slug, state)
        return True, ""  # loop — derive routes to REQUIREMENTS_REVIEW

    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        ToolCallRequest(
            command=SlashCommand.NEXT_PREPARE_DISCOVERY,
            args=slug,
            project=_derive_project_root(cwd, slug),
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{slug}",
            note=(
                f"Read the input via `telec todo artifacts read {slug} input` and "
                f"produce requirements via `telec todo artifacts write {slug} requirements <content>`. "
                "Work solo if the input is already concrete enough. If important intent, "
                "constraints, or code grounding still need another perspective, run "
                "triangulated discovery with a complementary partner."
            ),
            next_call=f"telec todo prepare {slug}",
            post_block=_worker_idle_post_block(slug),
        )
    )


async def _prepare_step_requirements_review(  # pylint: disable=too-many-locals,too-many-statements
    db: Db,
    todos_db: TodosDb,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """REQUIREMENTS_REVIEW: tailored output per state (init/approved/needs_work/blocked/needs_decision)."""
    writer = StateWriter(state)
    now = datetime.now(UTC).isoformat()
    audit = writer.audit_entry("requirements_review")
    audit.started_at = now

    review = writer.review("requirements_review")
    verdict = review.verdict

    # Reconcile digest: reviewer may have modified the artifact (auto-remediation)
    if verdict:
        current_digest = await todos_db.artifact_digest(slug, "requirements")
        if current_digest and current_digest != writer.state.artifacts.requirements.digest:
            writer.state.artifacts.requirements.digest = current_digest

    reviewer_id = await _find_live_session_for_slug(db, slug, "/next-review-requirements")
    worker_id = await _find_live_session_for_slug(db, slug, "/next-prepare-discovery")

    if verdict == "approve":
        audit.completed_at = now
        audit.verdict = "approve"
        await _commit_writer(writer, todos_db, slug, state)
        _emit_prepare_event("domain.software-development.prepare.requirements_approved", {"slug": slug})
        return False, _format_review_approved_script(slug, reviewer_id, worker_id, "requirements")

    if verdict == "needs_decision":
        # Architectural blocker — requires human decision before proceeding
        open_count = sum(1 for f in review.findings if f.status != "resolved")
        await _commit_writer(writer, todos_db, slug, state)
        return False, (
            f"BLOCKED: {slug} requirements have {open_count} unresolved architectural finding(s) "
            f"requiring human decision. Read findings via "
            f"`telec todo artifacts read {slug} requirements-review-findings`.\n\n"
            f"Before acting, load the relevant worker role:\n"
            f"  telec docs index\n"
            f"Then use telec docs get to load the procedure for the role you are assuming."
        )

    if verdict == "needs_work":
        rounds = review.rounds + 1
        review.rounds = rounds
        review.verdict = ""
        # I3: block after exceeding max review rounds to prevent infinite cycles
        if rounds > DEFAULT_MAX_REVIEW_ROUNDS:
            await _commit_writer(writer, todos_db, slug, state)
            return False, _format_review_blocked_script(slug, "requirements", reviewer_id, worker_id)
        # Count-and-pointer pattern: no file content injection (R2)
        open_findings = [f for f in review.findings if f.status != "resolved"]
        open_count = len(open_findings)
        audit.completed_at = now
        audit.verdict = "needs_work"
        audit.rounds = rounds
        await _commit_writer(writer, todos_db, slug, state)
        # Emit scoped re-review event (I-3)
        _emit_prepare_event(
            "domain.software-development.prepare.review_scoped",
            {"slug": slug, "finding_ids": [f.id for f in open_findings]},
        )
        if worker_id and reviewer_id:
            message = _fix_findings_message(
                slug, "requirements", rounds, open_count, "requirements-review-findings", "requirements"
            )
            return False, _format_review_needs_work_script(slug, worker_id, reviewer_id, message)
        # Fallback: dispatch a fresh discovery worker with baseline diff context
        base_sha = review.baseline_commit
        req_diff = compute_artifact_diff(cwd, slug, "requirements", base_sha)
        folder_diff = compute_todo_folder_diff(cwd, slug, base_sha)
        additional_context = "\n\n".join(filter(None, [req_diff, folder_diff])) or ""
        findings_note = (
            f"Requirements need revision: {open_count} unresolved finding(s). "
            f"Read findings via `telec todo artifacts read {slug} requirements-review-findings`."
        )
        guidance = await compose_agent_guidance(db)
        return False, format_tool_call(
            ToolCallRequest(
                command=SlashCommand.NEXT_PREPARE_DISCOVERY,
                args=slug,
                project=_derive_project_root(cwd, slug),
                guidance=guidance,
                subfolder=f"{WORKTREE_DIR}/{slug}",
                note=findings_note,
                next_call=f"telec todo prepare {slug}",
                additional_context=additional_context,
                post_block=_worker_idle_post_block(slug),
            )
        )

    # No verdict yet — dispatch reviewer; record HEAD SHA as diff anchor (I-1)
    rc, head_sha, _ = run_git_command(["rev-parse", "HEAD"], cwd=cwd)
    if rc == 0 and head_sha.strip():
        review.baseline_commit = head_sha.strip()
        audit.baseline_commit = head_sha.strip()
        await _commit_writer(writer, todos_db, slug, state)
    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        ToolCallRequest(
            command=SlashCommand.NEXT_REVIEW_REQUIREMENTS,
            args=slug,
            project=_derive_project_root(cwd, slug),
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{slug}",
            note=(
                f"Review requirements via `telec todo artifacts read {slug} requirements` "
                f"and stamp verdict via "
                f"`telec todo stamp {slug} --verdict approve|needs_work --phase requirements_review`."
            ),
            next_call=f"telec todo prepare {slug}",
            post_block=_reviewer_idle_post_block(slug),
        )
    )


async def _prepare_step_test_spec_build(
    db: Db,
    todos_db: TodosDb,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """TEST_SPEC_BUILD: dispatch spec builder.

    Derivation routes past this phase when ``artifacts.test_specs.produced_at``
    is stamped. The step itself only dispatches the builder — the builder
    stamps ``produced_at`` via the stamp API when the specs land, and the
    next loop iteration advances to TEST_SPEC_REVIEW.
    """
    writer = StateWriter(state)
    writer.audit.test_spec_build.started_at = datetime.now(UTC).isoformat()
    await _commit_writer(writer, todos_db, slug, state)

    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        ToolCallRequest(
            command=SlashCommand.NEXT_BUILD_SPECS,
            args=slug,
            project=_derive_project_root(cwd, slug),
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{slug}",
            note=(
                f"Read requirements via `telec todo artifacts read {slug} requirements` and write "
                f"xfail-marked pytest test specs in the worktree. Each test should capture a "
                f"requirement as a failing test. Commit the specs to the worktree branch, then stamp "
                f"`telec todo stamp {slug} --specs-built` so the state machine advances to TEST_SPEC_REVIEW."
            ),
            next_call=f"telec todo prepare {slug}",
            post_block=_worker_idle_post_block(slug),
        )
    )


async def _prepare_step_test_spec_review(  # pylint: disable=too-many-locals,too-many-statements
    db: Db,
    todos_db: TodosDb,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """TEST_SPEC_REVIEW: tailored output per state."""
    writer = StateWriter(state)
    now = datetime.now(UTC).isoformat()
    audit = writer.audit_entry("test_spec_review")
    audit.started_at = now

    # test_spec_review uses TestSpecReviewState (no findings/baseline_commit),
    # so access it directly rather than via writer.review().
    spec_review = writer.state.test_spec_review
    verdict = spec_review.verdict

    reviewer_id = await _find_live_session_for_slug(db, slug, "/next-review-specs")
    worker_id = await _find_live_session_for_slug(db, slug, "/next-build-specs")

    if verdict == "approve":
        audit.completed_at = now
        audit.verdict = "approve"
        await _commit_writer(writer, todos_db, slug, state)
        _emit_prepare_event("domain.software-development.prepare.specs_approved", {"slug": slug})
        return False, _format_review_approved_script(slug, reviewer_id, worker_id, "test spec")

    if verdict == "needs_work":
        rounds = spec_review.rounds + 1
        spec_review.rounds = rounds
        spec_review.verdict = ""
        # Block after exceeding max review rounds to prevent infinite cycles
        if rounds > DEFAULT_MAX_REVIEW_ROUNDS:
            await _commit_writer(writer, todos_db, slug, state)
            return False, _format_review_blocked_script(slug, "test spec", reviewer_id, worker_id)
        # Clear produced_at so derivation routes back to TEST_SPEC_BUILD on the next
        # iteration. The builder will re-stamp it when the revised specs land.
        writer.state.artifacts.test_specs.produced_at = ""
        # Count open findings for relay message (test_spec_review has no typed findings list,
        # but the relay mechanic still carries a counter so the worker knows how many items
        # to resolve from spec-review-findings.md).
        open_count = 0
        audit.completed_at = now
        audit.verdict = "needs_work"
        audit.rounds = rounds
        await _commit_writer(writer, todos_db, slug, state)

        if worker_id and reviewer_id:
            message = _fix_findings_message(
                slug, "test spec", rounds, open_count, "spec-review-findings", "test spec files in the worktree"
            )
            return False, _format_review_needs_work_script(slug, worker_id, reviewer_id, message)

        # Fallback: dispatch fresh spec builder when no live worker is available
        guidance = await compose_agent_guidance(db)
        return False, format_tool_call(
            ToolCallRequest(
                command=SlashCommand.NEXT_BUILD_SPECS,
                args=slug,
                project=_derive_project_root(cwd, slug),
                guidance=guidance,
                subfolder=f"{WORKTREE_DIR}/{slug}",
                note=(
                    f"Test specs need revision (round {rounds}). "
                    f"Read findings via `telec todo artifacts read {slug} spec-review-findings` "
                    f"and update xfail test specs in the worktree."
                ),
                next_call=f"telec todo prepare {slug}",
                post_block=_worker_idle_post_block(slug),
            )
        )

    # No verdict yet — dispatch reviewer
    await _commit_writer(writer, todos_db, slug, state)
    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        ToolCallRequest(
            command=SlashCommand.NEXT_REVIEW_SPECS,
            args=slug,
            project=_derive_project_root(cwd, slug),
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{slug}",
            note=f"Review xfail test specs in {WORKTREE_DIR}/{slug} and stamp verdict via `telec todo stamp {slug} --verdict approve|needs_work --phase test_spec_review`.",  # pylint: disable=line-too-long
            next_call=f"telec todo prepare {slug}",
            post_block=_reviewer_idle_post_block(slug),
        )
    )


async def _prepare_step_plan_drafting(
    db: Db,
    todos_db: TodosDb,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """PLAN_DRAFTING: implementation-plan.md needed."""
    writer = StateWriter(state)
    writer.audit.plan_drafting.started_at = datetime.now(UTC).isoformat()

    has_plan = await todos_db.artifact_exists(slug, "implementation-plan")
    if has_plan:
        writer.audit.plan_drafting.completed_at = datetime.now(UTC).isoformat()
        await _commit_writer(writer, todos_db, slug, state)
        _emit_prepare_event("domain.software-development.prepare.plan_drafted", {"slug": slug})
        return True, ""  # loop — derive routes to PLAN_REVIEW

    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        ToolCallRequest(
            command=SlashCommand.NEXT_PREPARE_DRAFT,
            args=slug,
            project=_derive_project_root(cwd, slug),
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{slug}",
            note=(
                f"Ground the approved requirements for {slug}. If the work is atomic, "
                f"write the implementation plan via "
                f"`telec todo artifacts write {slug} implementation-plan <content>`. "
                "If planning shows the parent is too large, split it into child todos and "
                "update the holder breakdown."
            ),
            next_call=f"telec todo prepare {slug}",
            post_block=_worker_idle_post_block(slug),
        )
    )


async def _prepare_step_plan_review(  # pylint: disable=too-many-locals,too-many-statements
    db: Db,
    todos_db: TodosDb,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """PLAN_REVIEW: tailored output per state."""
    writer = StateWriter(state)
    now = datetime.now(UTC).isoformat()
    audit = writer.audit_entry("plan_review")
    audit.started_at = now

    review = writer.review("plan_review")
    verdict = review.verdict

    # Reconcile digest: reviewer may have modified the artifact (auto-remediation)
    if verdict:
        current_digest = await todos_db.artifact_digest(slug, "implementation-plan")
        if current_digest and current_digest != writer.state.artifacts.implementation_plan.digest:
            writer.state.artifacts.implementation_plan.digest = current_digest

    reviewer_id = await _find_live_session_for_slug(db, slug, "/next-review-plan")
    worker_id = await _find_live_session_for_slug(db, slug, "/next-prepare-draft")

    if verdict == "approve":
        audit.completed_at = now
        audit.verdict = "approve"
        await _commit_writer(writer, todos_db, slug, state)
        _emit_prepare_event("domain.software-development.prepare.plan_approved", {"slug": slug})
        return False, _format_review_approved_script(slug, reviewer_id, worker_id, "plan")

    if verdict == "needs_decision":
        # Architectural blocker — requires human decision before proceeding
        open_count = sum(1 for f in review.findings if f.status != "resolved")
        await _commit_writer(writer, todos_db, slug, state)
        return False, (
            f"BLOCKED: {slug} plan has {open_count} unresolved architectural finding(s) "
            f"requiring human decision. Read findings via "
            f"`telec todo artifacts read {slug} plan-review-findings`.\n\n"
            f"Before acting, load the relevant worker role:\n"
            f"  telec docs index\n"
            f"Then use telec docs get to load the procedure for the role you are assuming."
        )

    if verdict == "needs_work":
        rounds = review.rounds + 1
        review.rounds = rounds
        review.verdict = ""
        # I3: block after exceeding max review rounds to prevent infinite cycles
        if rounds > DEFAULT_MAX_REVIEW_ROUNDS:
            await _commit_writer(writer, todos_db, slug, state)
            return False, _format_review_blocked_script(slug, "plan", reviewer_id, worker_id)
        # Count-and-pointer pattern: no file content injection (R2)
        open_findings = [f for f in review.findings if f.status != "resolved"]
        open_count = len(open_findings)
        audit.completed_at = now
        audit.verdict = "needs_work"
        audit.rounds = rounds
        await _commit_writer(writer, todos_db, slug, state)
        # Emit scoped re-review event (I-3)
        _emit_prepare_event(
            "domain.software-development.prepare.review_scoped",
            {"slug": slug, "finding_ids": [f.id for f in open_findings]},
        )
        if worker_id and reviewer_id:
            message = _fix_findings_message(
                slug, "plan", rounds, open_count, "plan-review-findings", "implementation-plan"
            )
            return False, _format_review_needs_work_script(slug, worker_id, reviewer_id, message)
        # Fallback: dispatch fresh draft worker with baseline diff context when no live worker
        base_sha = review.baseline_commit
        plan_diff = compute_artifact_diff(cwd, slug, "implementation-plan", base_sha)
        folder_diff = compute_todo_folder_diff(cwd, slug, base_sha)
        additional_context = "\n\n".join(filter(None, [plan_diff, folder_diff])) or ""
        findings_note = (
            f"Implementation plan needs revision: {open_count} unresolved finding(s). "
            f"Read findings via `telec todo artifacts read {slug} plan-review-findings`."
        )
        guidance = await compose_agent_guidance(db)
        return False, format_tool_call(
            ToolCallRequest(
                command=SlashCommand.NEXT_PREPARE_DRAFT,
                args=slug,
                project=_derive_project_root(cwd, slug),
                guidance=guidance,
                subfolder=f"{WORKTREE_DIR}/{slug}",
                note=findings_note,
                next_call=f"telec todo prepare {slug}",
                additional_context=additional_context,
                post_block=_worker_idle_post_block(slug),
            )
        )

    # No verdict yet — dispatch reviewer; record HEAD SHA as diff anchor (I-1)
    rc, head_sha, _ = run_git_command(["rev-parse", "HEAD"], cwd=cwd)
    if rc == 0 and head_sha.strip():
        review.baseline_commit = head_sha.strip()
        audit.baseline_commit = head_sha.strip()
        await _commit_writer(writer, todos_db, slug, state)
    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        ToolCallRequest(
            command=SlashCommand.NEXT_REVIEW_PLAN,
            args=slug,
            project=_derive_project_root(cwd, slug),
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{slug}",
            note=(
                f"Review the plan via `telec todo artifacts read {slug} implementation-plan` "
                f"and stamp verdict via `telec todo stamp {slug} --verdict approve|needs_work --phase plan_review`."
            ),
            next_call=f"telec todo prepare {slug}",
            post_block=_reviewer_idle_post_block(slug),
        )
    )


async def _prepare_step_gate(
    db: Db,
    todos_db: TodosDb,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """GATE: DOR formal validation."""
    writer = StateWriter(state)
    writer.audit.gate.started_at = datetime.now(UTC).isoformat()
    dor = writer.state.dor

    if dor is not None and dor.score >= DOR_READY_THRESHOLD:
        writer.audit.gate.completed_at = datetime.now(UTC).isoformat()
        await _commit_writer(writer, todos_db, slug, state)
        return True, ""  # loop — derive routes to GROUNDING_CHECK

    # Dispatch gate worker to run DOR assessment (in worktree — test specs live there)
    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        ToolCallRequest(
            command=SlashCommand.NEXT_PREPARE_GATE,
            args=slug,
            project=_derive_project_root(cwd, slug),
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{slug}",
            note=(
                f"Requirements/plan exist for {slug}, but DOR score is below threshold. "
                f"Complete DOR assessment and set state.yaml.dor.score >= {DOR_READY_THRESHOLD}."
            ),
            next_call=f"telec todo prepare {slug}",
            post_block=_worker_idle_post_block(slug),
        )
    )


async def _prepare_step_grounding_check(  # pylint: disable=too-many-locals
    db: Db,
    todos_db: TodosDb,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """GROUNDING_CHECK: mechanical freshness check + stale re-anchor.

    When grounding is fresh the baseline is captured/refreshed and derivation
    routes to PREPARED on the next loop iteration. When stale, the baseline is
    re-anchored and a plan update worker is dispatched via
    :func:`_handle_stale_grounding`.
    """
    writer = StateWriter(state)
    grounding_mgr = GroundingManager(writer)
    base_sha = writer.grounding.base_sha

    rc, current_sha_raw, _ = run_git_command(["rev-parse", "HEAD"], cwd=cwd)
    current_sha = current_sha_raw.strip() if rc == 0 else ""

    current_input_digest = ""
    input_content = todos_db.read_artifact_sync(slug, "input")
    if input_content:
        current_input_digest = hashlib.sha256(input_content.encode("utf-8")).hexdigest()

    # First grounding: capture baseline. Derivation routes to PREPARED next.
    if not base_sha:
        grounding_mgr.capture_fresh(current_sha=current_sha, current_input_digest=current_input_digest)
        await _commit_writer(writer, todos_db, slug, state)
        _emit_prepare_event("domain.software-development.prepare.completed", {"slug": slug})
        return True, ""  # loop — derive routes to PREPARED

    # I2: git failure is fail-closed — treat as stale with no changed paths.
    if not current_sha:
        logger.warning("GROUNDING_CHECK: git rev-parse HEAD failed for %s, treating as stale", slug)
        return await _handle_stale_grounding(
            db=db,
            todos_db=todos_db,
            slug=slug,
            cwd=cwd,
            state=state,
            writer=writer,
            grounding_mgr=grounding_mgr,
            current_sha=current_sha,
            reason="files_changed",
            changed_paths=[],
        )

    # Collect files changed between base_sha and current_sha for reference-path diffing.
    changed_files: set[str] = set()
    if current_sha != base_sha:
        rc2, diff_output, _ = run_git_command(["diff", "--name-only", f"{base_sha}..{current_sha}"], cwd=cwd)
        if rc2 == 0:
            changed_files = {line.strip() for line in diff_output.splitlines() if line.strip()}

    result = grounding_mgr.check(
        current_sha=current_sha,
        current_input_digest=current_input_digest,
        changed_files=changed_files,
    )

    if result.is_stale:
        return await _handle_stale_grounding(
            db=db,
            todos_db=todos_db,
            slug=slug,
            cwd=cwd,
            state=state,
            writer=writer,
            grounding_mgr=grounding_mgr,
            current_sha=current_sha,
            reason=result.reason,
            changed_paths=result.changed_paths,
        )

    # Fresh — refresh baseline. Derivation routes to PREPARED next.
    grounding_mgr.capture_fresh(current_sha=current_sha, current_input_digest=current_input_digest)
    await _commit_writer(writer, todos_db, slug, state)
    _emit_prepare_event("domain.software-development.prepare.completed", {"slug": slug})
    return True, ""  # loop — derive routes to PREPARED


async def _handle_stale_grounding(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    *,
    db: Db,
    todos_db: TodosDb,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
    writer: StateWriter,
    grounding_mgr: GroundingManager,
    current_sha: str,
    reason: str,
    changed_paths: list[str],
) -> tuple[bool, str]:
    """Re-anchor grounding and dispatch a plan update against changed files.

    In the derived-phase model, ``grounding.valid`` gates whether derivation
    returns GROUNDING_CHECK or PREPARED. When staleness is detected we must
    advance the baseline (so the next iteration does not loop back here) and
    force a plan re-review by clearing the plan verdict. The draft worker is
    dispatched with the changed-file context so it can update the plan before
    review.
    """
    _emit_prepare_event(
        "domain.software-development.prepare.grounding_invalidated",
        {"slug": slug, "reason": reason, "changed_paths": changed_paths},
    )

    if current_sha:
        grounding_mgr.refresh(current_sha=current_sha)
    else:
        # Git failed — mark stale but leave base_sha alone so we re-check
        # once the repo recovers. The plan_review reset below still forces
        # forward motion on the derivation side.
        grounding_mgr.invalidate(reason=reason, changed_paths=changed_paths)

    # Reset plan_review verdict so derivation returns PLAN_REVIEW on the next
    # iteration after the draft worker writes the updated plan.
    writer.review("plan_review").verdict = ""
    await _commit_writer(writer, todos_db, slug, state)

    changed_note = f"Changed files: {', '.join(changed_paths)}" if changed_paths else "Codebase has evolved."
    guidance = await compose_agent_guidance(db)
    instruction = format_tool_call(
        ToolCallRequest(
            command=SlashCommand.NEXT_PREPARE_DRAFT,
            args=slug,
            project=_derive_project_root(cwd, slug),
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{slug}",
            note=(
                f"Update the implementation plan via "
                f"`telec todo artifacts read {slug} implementation-plan` + "
                f"`telec todo artifacts write {slug} implementation-plan <content>` "
                f"against current codebase. {changed_note}"
            ),
            next_call=f"telec todo prepare {slug}",
            post_block=_worker_idle_post_block(slug),
        )
    )
    _emit_prepare_event("domain.software-development.prepare.regrounded", {"slug": slug})
    return False, instruction


async def _prepare_step_prepared(db: Db, slug: str) -> tuple[bool, str]:
    """PREPARED: terminal success state. Emits cleanup for all live slug sessions + self-end."""
    live_sessions = await _find_all_live_sessions_for_slug(db, slug)
    return False, format_prepared(slug, session_ids_to_end=live_sessions)


# =============================================================================
# Prepare State Machine — step dispatcher
# =============================================================================


async def _prepare_dispatch(  # pylint: disable=too-many-return-statements,too-many-arguments
    *,
    db: Db,
    todos_db: TodosDb,
    slug: str,
    cwd: str,
    phase: PreparePhase,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """Dispatch to the appropriate phase handler. Returns (continue_loop, instruction).

    Only handlers for phases that derivation can return are listed. The
    ``TRIANGULATION``, ``RE_GROUNDING``, and ``BLOCKED`` enum values exist for
    backward compatibility with legacy emitters but are never produced by
    :func:`derive_prepare_phase` — their handlers have been removed.
    """
    if phase == PreparePhase.INPUT_ASSESSMENT:
        return await _prepare_step_input_assessment(db, todos_db, slug, cwd, state)
    if phase == PreparePhase.REQUIREMENTS_REVIEW:
        return await _prepare_step_requirements_review(db, todos_db, slug, cwd, state)
    if phase == PreparePhase.TEST_SPEC_BUILD:
        return await _prepare_step_test_spec_build(db, todos_db, slug, cwd, state)
    if phase == PreparePhase.TEST_SPEC_REVIEW:
        return await _prepare_step_test_spec_review(db, todos_db, slug, cwd, state)
    if phase == PreparePhase.PLAN_DRAFTING:
        return await _prepare_step_plan_drafting(db, todos_db, slug, cwd, state)
    if phase == PreparePhase.PLAN_REVIEW:
        return await _prepare_step_plan_review(db, todos_db, slug, cwd, state)
    if phase == PreparePhase.GATE:
        return await _prepare_step_gate(db, todos_db, slug, cwd, state)
    if phase == PreparePhase.GROUNDING_CHECK:
        return await _prepare_step_grounding_check(db, todos_db, slug, cwd, state)
    if phase == PreparePhase.PREPARED:
        return await _prepare_step_prepared(db, slug)
    return False, f"UNHANDLED_PHASE: No handler for prepare phase: {phase.value}"


__all__ = ["_commit_writer", "_prepare_dispatch"]
