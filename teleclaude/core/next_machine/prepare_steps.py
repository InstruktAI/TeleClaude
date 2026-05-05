"""Prepare state machine phase step handlers and dispatcher."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR, SlashCommand
from teleclaude.core.db import Db
from teleclaude.core.next_machine import prepare_step_support
from teleclaude.core.next_machine._types import DEFAULT_MAX_REVIEW_ROUNDS, PreparePhase, StateValue
from teleclaude.core.next_machine.artifacts import compute_artifact_diff, compute_todo_folder_diff
from teleclaude.core.next_machine.git_ops import compose_agent_guidance, run_git_command
from teleclaude.core.next_machine.lifecycle import apply_authoritative_signal
from teleclaude.core.next_machine.output_formatting import (
    ConvergenceAssessmentScript,
    PairFormationScript,
    ToolCallRequest,
    format_command_loader_message,
    format_convergence_assessment_script,
    format_pair_formation_script,
    format_tool_call,
)
from teleclaude.core.next_machine.prepare_diff_dispatch import (
    DispatchReason,
    build_upstream_diff_pairs,
    format_dispatch_reason,
    review_digest_pair,
)
from teleclaude.core.next_machine.prepare_events import _emit_prepare_event
from teleclaude.core.next_machine.prepare_grounding_steps import (
    prepare_step_grounding_check,
    prepare_step_re_grounding,
)
from teleclaude.core.next_machine.prepare_pair import (
    PRODUCTION_ROLES,
    REVIEW_ROLES,
    format_pair_member_send_script,
    format_pair_review_or_recovery_script,
    format_pair_write_or_recovery_script,
    format_requirements_human_approval_script,
    pair_members_idle,
    pair_writer_reviewer_slots,
    prepare_pair_agent_mapping,
)
from teleclaude.core.next_machine.runtime.scripts import (
    format_fix_findings_message,
    format_review_approved_script,
    format_review_blocked_script,
    format_review_needs_work_script,
)
from teleclaude.core.next_machine.runtime.sessions import (
    find_live_session_for_slug as _find_live_session_for_slug,
)
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.next_machine.worktrees import ensure_worktree_with_policy_async

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb


logger = get_logger(__name__)

_commit_writer = prepare_step_support.commit_writer
_derive_project_root = prepare_step_support.derive_project_root
_prepare_step_prepared = prepare_step_support.prepare_step_prepared
_reviewer_idle_post_block = prepare_step_support.reviewer_idle_post_block
_worker_idle_post_block = prepare_step_support.worker_idle_post_block


async def _prepare_step_input_assessment(
    db: Db,
    todos_db: TodosDb,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """INPUT_ASSESSMENT: choose requirements strategy and produce requirements."""
    writer = StateWriter(state)
    writer.audit.input_assessment.started_at = datetime.now(UTC).isoformat()

    if writer.state.artifacts.requirements.produced_at:
        apply_authoritative_signal(writer.state, "requirements_ready")
        input_digest = await todos_db.artifact_digest(slug, "input")
        _emit_prepare_event(
            "domain.software-development.prepare.input_consumed",
            {"slug": slug, "phase": "input_assessment", "digest": input_digest},
        )
        writer.audit.input_assessment.completed_at = datetime.now(UTC).isoformat()
        await _commit_writer(writer, todos_db, slug, state)
        return True, ""

    pair = writer.state.prepare_pair
    if pair is not None and pair.slot_a is not None and pair.slot_b is not None:
        await _commit_writer(writer, todos_db, slug, state)
        if await pair_members_idle(db, pair.slot_a, pair.slot_b):
            return False, format_convergence_assessment_script(
                ConvergenceAssessmentScript(slug=slug, slot_a=pair.slot_a.session_id, slot_b=pair.slot_b.session_id)
            )
        message = (
            f"Continue your paired discovery discussion for {slug}. "
            f"Surface any remaining unknowns and converge on what the requirements should contain. "
            f"Go idle when converged."
        )
        instruction = await format_pair_write_or_recovery_script(
            db=db,
            slug=slug,
            writer_slot=pair.slot_a,
            reviewer_slot=pair.slot_b,
            command=f"/{SlashCommand.NEXT_PREPARE_DISCOVERY.value}",
            project=_derive_project_root(cwd, slug),
            subfolder=f"{WORKTREE_DIR}/{slug}",
            message=message,
            next_step=f"telec todo prepare {slug}",
        )
        return False, instruction

    pair_agents = prepare_pair_agent_mapping()
    await _commit_writer(writer, todos_db, slug, state)
    return False, format_pair_formation_script(
        PairFormationScript(
            command=SlashCommand.NEXT_PREPARE_DISCOVERY,
            args=slug,
            project=_derive_project_root(cwd, slug),
            subfolder=f"{WORKTREE_DIR}/{slug}",
            agent_a=pair_agents["A"],
            agent_b=pair_agents["B"],
            mode_a="slow",
            mode_b="slow",
            slug=slug,
        )
    )


async def _prepare_step_triangulation(
    db: Db,
    todos_db: TodosDb,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """TRIANGULATION: force a multi-perspective discovery pass."""
    writer = StateWriter(state)
    writer.audit.triangulation.started_at = datetime.now(UTC).isoformat()
    await _commit_writer(writer, todos_db, slug, state)

    if writer.state.artifacts.requirements.produced_at:
        apply_authoritative_signal(writer.state, "requirements_ready")
        writer.audit.triangulation.completed_at = datetime.now(UTC).isoformat()
        await _commit_writer(writer, todos_db, slug, state)
        return True, ""

    has_input = await todos_db.artifact_exists(slug, "input")
    pair_slots = pair_writer_reviewer_slots(state, PreparePhase.TRIANGULATION, PRODUCTION_ROLES)
    if pair_slots is not None:
        writer_slot, reviewer_slot = pair_slots
        message = (
            f"Continue your paired discovery discussion for {slug}. "
            f"Converge on what the requirements should contain. "
            f"Go idle when converged."
        )
        instruction = await format_pair_write_or_recovery_script(
            db=db,
            slug=slug,
            writer_slot=writer_slot,
            reviewer_slot=reviewer_slot,
            command=f"/{SlashCommand.NEXT_PREPARE_DISCOVERY.value}",
            project=_derive_project_root(cwd, slug),
            subfolder=f"{WORKTREE_DIR}/{slug}",
            message=message,
            next_step=f"telec todo prepare {slug}",
        )
        return False, instruction

    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        ToolCallRequest(
            command=SlashCommand.NEXT_PREPARE_DISCOVERY,
            args=slug,
            project=_derive_project_root(cwd, slug),
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{slug}",
            note=(
                f"Run a triangulated discovery pass for {slug}. "
                + (
                    f"Read the input via `telec todo artifacts read {slug} input`, "
                    if has_input
                    else "There is no input artifact; work from the existing draft context and artifacts, "
                )
                + "incorporate a complementary "
                "perspective, rewrite requirements via "
                f"`telec todo artifacts write {slug} requirements <content>`, "
                f"then stamp via `telec todo stamp {slug} --requirements-ready`."
            ),
            next_call=f"telec todo prepare {slug}",
            post_block=_worker_idle_post_block(slug),
        )
    )


async def _prepare_step_requirements_review(
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

    pair_slots = pair_writer_reviewer_slots(state, PreparePhase.REQUIREMENTS_REVIEW, REVIEW_ROLES)
    if pair_slots is None:
        reviewer_id = await _find_live_session_for_slug(db, slug, "/next-review-requirements")
        worker_id = await _find_live_session_for_slug(db, slug, "/next-prepare-discovery")
    else:
        worker_slot, reviewer_slot = pair_slots
        worker_id = worker_slot.session_id
        reviewer_id = reviewer_slot.session_id

    if verdict == "approve":
        # Digest-bound approval: the verdict only stands while the artifact's
        # current digest matches the digest the reviewer approved. When they
        # diverge, fall through to dispatch a re-review.
        current_requirements_digest = await todos_db.artifact_digest(slug, "requirements")
        if review.approved_digest == current_requirements_digest:
            audit.completed_at = now
            audit.verdict = "approve"
            await _commit_writer(writer, todos_db, slug, state)
            _emit_prepare_event("domain.software-development.prepare.requirements_approved", {"slug": slug})
            if pair_slots is not None:
                return False, f"REQUIREMENTS REVIEW APPROVED: {slug}\n\ntelec todo prepare {slug}"
            return False, format_review_approved_script(slug, reviewer_id, worker_id, "requirements")
        # Stale approval — clear verdict to re-trigger reviewer dispatch below.
        review.verdict = ""
        verdict = ""
        await _commit_writer(writer, todos_db, slug, state)

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
            return False, format_review_blocked_script(slug, "requirements", reviewer_id, worker_id)
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
        if pair_slots is not None and worker_id and reviewer_id:
            message = format_fix_findings_message(
                slug, "requirements", rounds, open_count, "requirements-review-findings", "requirements"
            )
            return False, format_pair_member_send_script(
                slug=slug,
                session_id=worker_id,
                message=message,
                next_step=f"telec todo prepare {slug}",
            )
        if worker_id and reviewer_id:
            message = format_fix_findings_message(
                slug, "requirements", rounds, open_count, "requirements-review-findings", "requirements"
            )
            return False, format_review_needs_work_script(
                slug, worker_id, reviewer_id, message, next_step=f"telec todo prepare {slug}"
            )
        # Fallback: dispatch a fresh discovery worker with baseline diff context
        base_sha = review.baseline_commit
        req_diff = compute_artifact_diff(cwd, slug, "requirements", base_sha)
        folder_diff = compute_todo_folder_diff(cwd, slug, base_sha)
        additional_context = "\n\n".join(filter(None, [req_diff, folder_diff])) or ""
        findings_note = format_dispatch_reason(
            (
                f"Requirements need revision: {open_count} unresolved finding(s). "
                f"Read findings via `telec todo artifacts read {slug} requirements-review-findings`."
            ),
            slug,
            DispatchReason.FINDINGS_FIX,
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
    current_requirements_digest = await todos_db.artifact_digest(slug, "requirements")
    diff_pairs = review_digest_pair("requirements", "requirements", review.approved_digest, current_requirements_digest)
    review_reason = DispatchReason.UPSTREAM_CHANGED if diff_pairs else DispatchReason.FRESH
    if pair_slots is not None:
        message = format_dispatch_reason(
            format_command_loader_message("next-review-requirements", slug),
            slug,
            review_reason,
            diff_pairs,
        )
        instruction = await format_pair_review_or_recovery_script(
            db=db,
            slug=slug,
            writer_slot=pair_slots[0],
            reviewer_slot=pair_slots[1],
            command=f"/{SlashCommand.NEXT_REVIEW_REQUIREMENTS.value}",
            project=_derive_project_root(cwd, slug),
            subfolder=f"{WORKTREE_DIR}/{slug}",
            message=message,
            next_step=f"telec todo prepare {slug}",
        )
        return False, instruction
    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        ToolCallRequest(
            command=SlashCommand.NEXT_REVIEW_REQUIREMENTS,
            args=slug,
            project=_derive_project_root(cwd, slug),
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{slug}",
            note=format_dispatch_reason(
                (
                    f"Review requirements via `telec todo artifacts read {slug} requirements` "
                    f"and stamp verdict via "
                    f"`telec todo stamp {slug} --verdict approve|needs_work --phase requirements_review`."
                ),
                slug,
                review_reason,
                diff_pairs,
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
    """TEST_SPEC_BUILD: dispatch spec builder when specs are missing or stale.

    When ``artifacts.test_specs.produced_at`` is set AND the recorded upstream
    requirements digest still matches the current requirements digest, specs are
    fresh — emit ``specs_built`` to advance the lifecycle without dispatching.
    """
    await ensure_worktree_with_policy_async(_derive_project_root(cwd, slug), slug)

    writer = StateWriter(state)
    test_specs_entry = writer.state.artifacts.test_specs
    if test_specs_entry.produced_at:
        current_requirements_digest = await todos_db.artifact_digest(slug, "requirements")
        recorded_requirements_digest = test_specs_entry.upstream_digests.get("requirements", "")
        if recorded_requirements_digest == current_requirements_digest:
            apply_authoritative_signal(writer.state, "specs_built")
            writer.audit.test_spec_build.completed_at = datetime.now(UTC).isoformat()
            await _commit_writer(writer, todos_db, slug, state)
            return True, ""

    writer.audit.test_spec_build.started_at = datetime.now(UTC).isoformat()
    await _commit_writer(writer, todos_db, slug, state)

    build_diff_pairs = await build_upstream_diff_pairs(
        todos_db,
        slug,
        dict(test_specs_entry.upstream_digests),
        (("requirements", "requirements", "requirements"),),
    )

    if not test_specs_entry.produced_at:
        build_reason = DispatchReason.FRESH
    elif not test_specs_entry.upstream_digests:
        build_reason = DispatchReason.PROVENANCE_MISSING
    else:
        build_reason = DispatchReason.UPSTREAM_CHANGED

    pair_slots = pair_writer_reviewer_slots(state, PreparePhase.TEST_SPEC_BUILD, PRODUCTION_ROLES)
    if pair_slots is not None:
        writer_slot, reviewer_slot = pair_slots
        message = format_dispatch_reason(
            format_command_loader_message("next-build-specs", slug),
            slug,
            build_reason,
            build_diff_pairs,
        )
        instruction = await format_pair_write_or_recovery_script(
            db=db,
            slug=slug,
            writer_slot=writer_slot,
            reviewer_slot=reviewer_slot,
            command=f"/{SlashCommand.NEXT_BUILD_SPECS.value}",
            project=_derive_project_root(cwd, slug),
            subfolder=f"{WORKTREE_DIR}/{slug}",
            message=message,
            next_step=f"telec todo prepare {slug}",
        )
        return False, instruction

    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        ToolCallRequest(
            command=SlashCommand.NEXT_BUILD_SPECS,
            args=slug,
            project=_derive_project_root(cwd, slug),
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{slug}",
            note=format_dispatch_reason(
                (
                    f"Read requirements via `telec todo artifacts read {slug} requirements` and write "
                    f"xfail-marked pytest test specs in the worktree. Each test should capture a "
                    f"requirement as a failing test. Commit the specs to the worktree branch, then call "
                    f"`telec todo prepare {slug}` so the machine can continue from the resulting work."
                ),
                slug,
                build_reason,
                build_diff_pairs,
            ),
            next_call=f"telec todo prepare {slug}",
            post_block=_worker_idle_post_block(slug),
        )
    )


async def _prepare_step_test_spec_review(
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

    pair_slots = pair_writer_reviewer_slots(state, PreparePhase.TEST_SPEC_REVIEW, REVIEW_ROLES)
    if pair_slots is None:
        reviewer_id = await _find_live_session_for_slug(db, slug, "/next-review-specs")
        worker_id = await _find_live_session_for_slug(db, slug, "/next-build-specs")
    else:
        worker_slot, reviewer_slot = pair_slots
        worker_id = worker_slot.session_id
        reviewer_id = reviewer_slot.session_id

    if verdict == "approve":
        # Digest-bound approval: only stands while specs digest matches the
        # one the reviewer approved. When test_specs has no DB-backed digest
        # (no manifest), verdict alone gates approval.
        current_specs_digest = await todos_db.artifact_digest(slug, "test-specs")
        if not current_specs_digest or spec_review.approved_digest == current_specs_digest:
            audit.completed_at = now
            audit.verdict = "approve"
            await _commit_writer(writer, todos_db, slug, state)
            _emit_prepare_event("domain.software-development.prepare.specs_approved", {"slug": slug})
            if pair_slots is not None:
                return False, f"TEST SPEC REVIEW APPROVED: {slug}\n\ntelec todo prepare {slug}"
            return False, format_review_approved_script(slug, reviewer_id, worker_id, "test spec")
        # Stale approval — clear verdict to re-trigger reviewer dispatch below.
        spec_review.verdict = ""
        verdict = ""
        await _commit_writer(writer, todos_db, slug, state)

    if verdict == "needs_work":
        rounds = spec_review.rounds + 1
        spec_review.rounds = rounds
        spec_review.verdict = ""
        if rounds > DEFAULT_MAX_REVIEW_ROUNDS:
            await _commit_writer(writer, todos_db, slug, state)
            return False, format_review_blocked_script(slug, "test spec", reviewer_id, worker_id)
        writer.state.artifacts.test_specs.produced_at = ""
        open_count = 0
        audit.completed_at = now
        audit.verdict = "needs_work"
        audit.rounds = rounds
        await _commit_writer(writer, todos_db, slug, state)

        if pair_slots is not None and worker_id and reviewer_id:
            message = format_fix_findings_message(
                slug, "test spec", rounds, open_count, "spec-review-findings", "test spec files in the worktree"
            )
            return False, format_pair_member_send_script(
                slug=slug,
                session_id=worker_id,
                message=message,
                next_step=f"telec todo prepare {slug}",
            )
        if worker_id and reviewer_id:
            message = format_fix_findings_message(
                slug, "test spec", rounds, open_count, "spec-review-findings", "test spec files in the worktree"
            )
            return False, format_review_needs_work_script(
                slug, worker_id, reviewer_id, message, next_step=f"telec todo prepare {slug}"
            )

        # Fallback: dispatch fresh spec builder when no live worker is available
        guidance = await compose_agent_guidance(db)
        return False, format_tool_call(
            ToolCallRequest(
                command=SlashCommand.NEXT_BUILD_SPECS,
                args=slug,
                project=_derive_project_root(cwd, slug),
                guidance=guidance,
                subfolder=f"{WORKTREE_DIR}/{slug}",
                note=format_dispatch_reason(
                    (
                        f"Test specs need revision (round {rounds}). "
                        f"Read findings via `telec todo artifacts read {slug} spec-review-findings` "
                        f"and update xfail test specs in the worktree."
                    ),
                    slug,
                    DispatchReason.FINDINGS_FIX,
                ),
                next_call=f"telec todo prepare {slug}",
                post_block=_worker_idle_post_block(slug),
            )
        )

    # No verdict yet — dispatch reviewer
    await _commit_writer(writer, todos_db, slug, state)
    current_specs_digest = await todos_db.artifact_digest(slug, "test-specs")
    spec_diff_pairs = review_digest_pair("test_specs", "test-specs", spec_review.approved_digest, current_specs_digest)
    spec_review_reason = DispatchReason.UPSTREAM_CHANGED if spec_diff_pairs else DispatchReason.FRESH
    if pair_slots is not None:
        message = format_dispatch_reason(
            format_command_loader_message("next-review-specs", slug),
            slug,
            spec_review_reason,
            spec_diff_pairs,
        )
        instruction = await format_pair_review_or_recovery_script(
            db=db,
            slug=slug,
            writer_slot=pair_slots[0],
            reviewer_slot=pair_slots[1],
            command=f"/{SlashCommand.NEXT_REVIEW_SPECS.value}",
            project=_derive_project_root(cwd, slug),
            subfolder=f"{WORKTREE_DIR}/{slug}",
            message=message,
            next_step=f"telec todo prepare {slug}",
        )
        return False, instruction
    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        ToolCallRequest(
            command=SlashCommand.NEXT_REVIEW_SPECS,
            args=slug,
            project=_derive_project_root(cwd, slug),
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{slug}",
            note=format_dispatch_reason(
                (
                    f"Review xfail test specs in {WORKTREE_DIR}/{slug} and stamp verdict via "
                    f"`telec todo stamp {slug} --verdict approve|needs_work --phase test_spec_review`."
                ),
                slug,
                spec_review_reason,
                spec_diff_pairs,
            ),
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
    """PLAN_DRAFTING: implementation-plan.md needed when missing or upstream stale."""
    writer = StateWriter(state)
    writer.audit.plan_drafting.started_at = datetime.now(UTC).isoformat()

    plan_entry = writer.state.artifacts.implementation_plan
    plan_diff_pairs = await build_upstream_diff_pairs(
        todos_db,
        slug,
        dict(plan_entry.upstream_digests),
        (
            ("requirements", "requirements", "requirements"),
            ("test_specs", "test_specs", "test-specs"),
        ),
    )

    if plan_entry.produced_at and not plan_diff_pairs:
        apply_authoritative_signal(writer.state, "plan_ready")
        writer.audit.plan_drafting.completed_at = datetime.now(UTC).isoformat()
        await _commit_writer(writer, todos_db, slug, state)
        _emit_prepare_event("domain.software-development.prepare.plan_drafted", {"slug": slug})
        return True, ""

    if not plan_entry.produced_at:
        plan_reason = DispatchReason.FRESH
    elif not plan_entry.upstream_digests:
        plan_reason = DispatchReason.PROVENANCE_MISSING
    else:
        plan_reason = DispatchReason.UPSTREAM_CHANGED

    pair_slots = pair_writer_reviewer_slots(state, PreparePhase.PLAN_DRAFTING, PRODUCTION_ROLES)
    if pair_slots is not None:
        writer_slot, reviewer_slot = pair_slots
        await _commit_writer(writer, todos_db, slug, state)
        message = format_dispatch_reason(
            format_command_loader_message("next-prepare-draft", slug),
            slug,
            plan_reason,
            plan_diff_pairs,
        )
        instruction = await format_pair_write_or_recovery_script(
            db=db,
            slug=slug,
            writer_slot=writer_slot,
            reviewer_slot=reviewer_slot,
            command=f"/{SlashCommand.NEXT_PREPARE_DRAFT.value}",
            project=_derive_project_root(cwd, slug),
            subfolder=f"{WORKTREE_DIR}/{slug}",
            message=message,
            next_step=f"telec todo prepare {slug}",
        )
        return False, instruction

    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        ToolCallRequest(
            command=SlashCommand.NEXT_PREPARE_DRAFT,
            args=slug,
            project=_derive_project_root(cwd, slug),
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{slug}",
            note=format_dispatch_reason(
                (
                    f"Ground the approved requirements for {slug}. If the work is atomic, "
                    f"write the implementation plan via "
                    f"`telec todo artifacts write {slug} implementation-plan <content>`, then "
                    f"stamp via `telec todo stamp {slug} --plan-ready`. "
                    "If planning shows the parent is too large, split it into child todos and "
                    "update the holder breakdown."
                ),
                slug,
                plan_reason,
                plan_diff_pairs,
            ),
            next_call=f"telec todo prepare {slug}",
            post_block=_worker_idle_post_block(slug),
        )
    )


async def _prepare_step_plan_review(
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

    pair_slots = pair_writer_reviewer_slots(state, PreparePhase.PLAN_REVIEW, REVIEW_ROLES)
    if pair_slots is None:
        reviewer_id = await _find_live_session_for_slug(db, slug, "/next-review-plan")
        worker_id = await _find_live_session_for_slug(db, slug, "/next-prepare-draft")
    else:
        worker_slot, reviewer_slot = pair_slots
        worker_id = worker_slot.session_id
        reviewer_id = reviewer_slot.session_id

    if verdict == "approve":
        # Digest-bound approval: only stands while plan digest matches the
        # one the reviewer approved.
        current_plan_digest = await todos_db.artifact_digest(slug, "implementation-plan")
        if review.approved_digest == current_plan_digest:
            audit.completed_at = now
            audit.verdict = "approve"
            await _commit_writer(writer, todos_db, slug, state)
            _emit_prepare_event("domain.software-development.prepare.plan_approved", {"slug": slug})
            if pair_slots is not None:
                return False, f"PLAN REVIEW APPROVED: {slug}\n\ntelec todo prepare {slug}"
            return False, format_review_approved_script(slug, reviewer_id, worker_id, "plan")
        # Stale approval — clear verdict to re-trigger reviewer dispatch below.
        review.verdict = ""
        verdict = ""
        await _commit_writer(writer, todos_db, slug, state)

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
            return False, format_review_blocked_script(slug, "plan", reviewer_id, worker_id)
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
        if pair_slots is not None and worker_id and reviewer_id:
            message = format_fix_findings_message(
                slug, "plan", rounds, open_count, "plan-review-findings", "implementation-plan"
            )
            return False, format_pair_member_send_script(
                slug=slug,
                session_id=worker_id,
                message=message,
                next_step=f"telec todo prepare {slug}",
            )
        if worker_id and reviewer_id:
            message = format_fix_findings_message(
                slug, "plan", rounds, open_count, "plan-review-findings", "implementation-plan"
            )
            return False, format_review_needs_work_script(
                slug, worker_id, reviewer_id, message, next_step=f"telec todo prepare {slug}"
            )
        # Fallback: dispatch fresh draft worker with baseline diff context when no live worker
        base_sha = review.baseline_commit
        plan_diff = compute_artifact_diff(cwd, slug, "implementation-plan", base_sha)
        folder_diff = compute_todo_folder_diff(cwd, slug, base_sha)
        additional_context = "\n\n".join(filter(None, [plan_diff, folder_diff])) or ""
        findings_note = format_dispatch_reason(
            (
                f"Implementation plan needs revision: {open_count} unresolved finding(s). "
                f"Read findings via `telec todo artifacts read {slug} plan-review-findings`."
            ),
            slug,
            DispatchReason.FINDINGS_FIX,
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
    current_plan_digest = await todos_db.artifact_digest(slug, "implementation-plan")
    plan_diff_pairs = review_digest_pair(
        "implementation_plan", "implementation-plan", review.approved_digest, current_plan_digest
    )
    plan_review_reason = DispatchReason.UPSTREAM_CHANGED if plan_diff_pairs else DispatchReason.FRESH
    if pair_slots is not None:
        message = format_dispatch_reason(
            format_command_loader_message("next-review-plan", slug),
            slug,
            plan_review_reason,
            plan_diff_pairs,
        )
        instruction = await format_pair_review_or_recovery_script(
            db=db,
            slug=slug,
            writer_slot=pair_slots[0],
            reviewer_slot=pair_slots[1],
            command=f"/{SlashCommand.NEXT_REVIEW_PLAN.value}",
            project=_derive_project_root(cwd, slug),
            subfolder=f"{WORKTREE_DIR}/{slug}",
            message=message,
            next_step=f"telec todo prepare {slug}",
        )
        return False, instruction
    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        ToolCallRequest(
            command=SlashCommand.NEXT_REVIEW_PLAN,
            args=slug,
            project=_derive_project_root(cwd, slug),
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{slug}",
            note=format_dispatch_reason(
                (
                    f"Review the plan via `telec todo artifacts read {slug} implementation-plan` "
                    f"and stamp verdict via "
                    f"`telec todo stamp {slug} --verdict approve|needs_work --phase plan_review`."
                ),
                slug,
                plan_review_reason,
                plan_diff_pairs,
            ),
            next_call=f"telec todo prepare {slug}",
            post_block=_reviewer_idle_post_block(slug),
        )
    )


async def _prepare_dispatch(
    *,
    db: Db,
    todos_db: TodosDb,
    slug: str,
    cwd: str,
    phase: PreparePhase,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """Dispatch to the appropriate phase handler."""
    if phase == PreparePhase.INPUT_ASSESSMENT:
        return await _prepare_step_input_assessment(db, todos_db, slug, cwd, state)
    if phase == PreparePhase.TRIANGULATION:
        return await _prepare_step_triangulation(db, todos_db, slug, cwd, state)
    if phase == PreparePhase.REQUIREMENTS_REVIEW:
        return await _prepare_step_requirements_review(db, todos_db, slug, cwd, state)
    if phase == PreparePhase.REQUIREMENTS_HUMAN_APPROVAL:
        return False, format_requirements_human_approval_script(slug)
    if phase == PreparePhase.TEST_SPEC_BUILD:
        return await _prepare_step_test_spec_build(db, todos_db, slug, cwd, state)
    if phase == PreparePhase.TEST_SPEC_REVIEW:
        return await _prepare_step_test_spec_review(db, todos_db, slug, cwd, state)
    if phase == PreparePhase.PLAN_DRAFTING:
        return await _prepare_step_plan_drafting(db, todos_db, slug, cwd, state)
    if phase == PreparePhase.PLAN_REVIEW:
        return await _prepare_step_plan_review(db, todos_db, slug, cwd, state)
    if phase == PreparePhase.GATE:
        writer = StateWriter(state)
        writer.state.lifecycle_phase = PreparePhase.GROUNDING_CHECK.value
        await _commit_writer(writer, todos_db, slug, state)
        return True, ""
    if phase == PreparePhase.GROUNDING_CHECK:
        return await prepare_step_grounding_check(db, todos_db, slug, cwd, state)
    if phase == PreparePhase.RE_GROUNDING:
        return await prepare_step_re_grounding(db, todos_db, slug, cwd, state)
    if phase == PreparePhase.PREPARED:
        return await _prepare_step_prepared(db, slug)
    return False, f"UNHANDLED_PHASE: No handler for prepare phase: {phase.value}"


__all__ = ["_commit_writer", "_prepare_dispatch"]
