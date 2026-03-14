"""Prepare state machine — phase step handlers and dispatcher.

No imports from core.py (circular-import guard).
Note: _has_test_spec_artifacts lives in prepare_events.py (co-located with _derive_prepare_phase).
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR, SlashCommand
from teleclaude.core.db import Db
from teleclaude.core.next_machine._types import (
    DEFAULT_MAX_REVIEW_ROUNDS,
    DEFAULT_STATE,
    DOR_READY_THRESHOLD,
    PreparePhase,
    StateValue,
)
from teleclaude.core.next_machine.build_gates import check_file_has_content
from teleclaude.core.next_machine.git_ops import compose_agent_guidance
from teleclaude.core.next_machine.output_formatting import format_prepared, format_tool_call
from teleclaude.core.next_machine.prepare_events import _emit_prepare_event, _has_test_spec_artifacts
from teleclaude.core.next_machine.state_io import _run_git_prepare, write_phase_state
from teleclaude.core.next_machine.worktrees import ensure_worktree_with_policy_async

logger = get_logger(__name__)


async def _prepare_step_input_assessment(
    db: Db,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """INPUT_ASSESSMENT: choose requirements strategy and produce requirements."""
    from teleclaude.core.next_machine.prepare_helpers import stamp_audit

    _now = datetime.now(UTC).isoformat()
    stamp_audit(state, "input_assessment", "started_at", _now)

    if check_file_has_content(cwd, f"todos/{slug}/requirements.md"):
        # Emit input_consumed event before transitioning (R13)
        from teleclaude.core.next_machine.prepare_helpers import record_input_consumed

        await asyncio.to_thread(record_input_consumed, cwd, slug)
        stamp_audit(state, "input_assessment", "completed_at", datetime.now(UTC).isoformat())
        state["prepare_phase"] = PreparePhase.REQUIREMENTS_REVIEW.value
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
        return True, ""  # loop

    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        command=SlashCommand.NEXT_PREPARE_DISCOVERY,
        args=slug,
        project=cwd,
        guidance=guidance,
        subfolder="",
        note=(
            f"Assess todos/{slug}/input.md and produce todos/{slug}/requirements.md. "
            "Work solo if the input is already concrete enough. If important intent, "
            "constraints, or code grounding still need another perspective, run "
            "triangulated discovery with a complementary partner."
        ),
        next_call=f"telec todo prepare {slug}",
    )


async def _prepare_step_triangulation(
    db: Db,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """TRIANGULATION: requirements.md still needs discovery or revision."""
    if check_file_has_content(cwd, f"todos/{slug}/requirements.md"):
        # Transition to REQUIREMENTS_REVIEW
        state["prepare_phase"] = PreparePhase.REQUIREMENTS_REVIEW.value
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
        _emit_prepare_event("domain.software-development.prepare.requirements_drafted", {"slug": slug})
        return True, ""  # loop

    _emit_prepare_event("domain.software-development.prepare.triangulation_started", {"slug": slug})
    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        command=SlashCommand.NEXT_PREPARE_DISCOVERY,
        args=slug,
        project=cwd,
        guidance=guidance,
        subfolder="",
        note=(
            f"Produce todos/{slug}/requirements.md. Use solo discovery if you already have "
            "enough grounding; otherwise triangulate with a complementary partner before writing."
        ),
        next_call=f"telec todo prepare {slug}",
    )


async def _prepare_step_requirements_review(
    db: Db,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """REQUIREMENTS_REVIEW: awaiting review verdict."""
    from teleclaude.core.next_machine.prepare_helpers import stamp_audit

    stamp_audit(state, "requirements_review", "started_at", datetime.now(UTC).isoformat())

    req_review = state.get("requirements_review", {})
    verdict = (isinstance(req_review, dict) and req_review.get("verdict")) or ""

    if verdict == "approve":
        stamp_audit(state, "requirements_review", "completed_at", datetime.now(UTC).isoformat())
        stamp_audit(state, "requirements_review", "verdict", "approve")
        state["prepare_phase"] = PreparePhase.TEST_SPEC_BUILD.value
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
        _emit_prepare_event("domain.software-development.prepare.requirements_approved", {"slug": slug})
        return True, ""  # loop

    if verdict == "needs_decision":
        # Architectural blocker — requires human decision before proceeding
        findings = (isinstance(req_review, dict) and req_review.get("findings")) or []
        findings_list = findings if isinstance(findings, list) else []
        open_count = sum(1 for f in findings_list if isinstance(f, dict) and f.get("status") != "resolved")
        state["prepare_phase"] = PreparePhase.BLOCKED.value
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
        return False, (
            f"BLOCKED: {slug} requirements have {open_count} unresolved architectural finding(s) "
            f"requiring human decision. See todos/{slug}/requirements-review-findings.md.\n\n"
            f"Before acting, load the relevant worker role:\n"
            f"  telec docs index\n"
            f"Then use telec docs get to load the procedure for the role you are assuming."
        )

    if verdict == "needs_work":
        if isinstance(req_review, dict):
            rounds = int(req_review.get("rounds", 0)) + 1  # type: ignore[arg-type]
            req_review["rounds"] = rounds
            req_review["verdict"] = ""
        else:
            rounds = 1
        # I3: block after exceeding max review rounds to prevent infinite cycles
        if rounds > DEFAULT_MAX_REVIEW_ROUNDS:
            state["requirements_review"] = req_review
            state["prepare_phase"] = PreparePhase.BLOCKED.value
            await asyncio.to_thread(write_phase_state, cwd, slug, state)
            return False, (
                f"BLOCKED: {slug} requirements review exceeded {DEFAULT_MAX_REVIEW_ROUNDS} rounds. "
                f"Manual resolution required.\n\n"
                f"Before acting, load the relevant worker role:\n"
                f"  telec docs index\n"
                f"Then use telec docs get to load the procedure for the role you are assuming."
            )
        # Count-and-pointer pattern: no file content injection (R2)
        findings = (isinstance(req_review, dict) and req_review.get("findings")) or []
        findings_list = findings if isinstance(findings, list) else []
        open_count = sum(1 for f in findings_list if isinstance(f, dict) and f.get("status") != "resolved")
        findings_note = (
            f"Requirements need revision: {open_count} unresolved finding(s). "
            f"See todos/{slug}/requirements-review-findings.md."
        )
        stamp_audit(state, "requirements_review", "completed_at", datetime.now(UTC).isoformat())
        stamp_audit(state, "requirements_review", "verdict", "needs_work")
        stamp_audit(state, "requirements_review", "rounds", rounds)
        state["requirements_review"] = req_review
        state["prepare_phase"] = PreparePhase.TRIANGULATION.value
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
        # Compute diff context for re-dispatch (I-2)
        from teleclaude.core.next_machine.prepare_helpers import (
            compute_artifact_diff,
            compute_todo_folder_diff,
        )

        base_sha = (isinstance(req_review, dict) and req_review.get("baseline_commit")) or ""
        req_diff = compute_artifact_diff(cwd, slug, f"todos/{slug}/requirements.md", str(base_sha))
        folder_diff = compute_todo_folder_diff(cwd, slug, str(base_sha))
        additional_context = "\n\n".join(filter(None, [req_diff, folder_diff])) or ""
        # Emit scoped re-review event (I-3)
        _emit_prepare_event(
            "domain.software-development.prepare.review_scoped",
            {
                "slug": slug,
                "finding_ids": [
                    f.get("id", "")  # type: ignore[misc]
                    for f in findings_list
                    if isinstance(f, dict) and f.get("status") != "resolved"
                ],
            },
        )
        guidance = await compose_agent_guidance(db)
        return False, format_tool_call(
            command=SlashCommand.NEXT_PREPARE_DISCOVERY,
            args=slug,
            project=cwd,
            guidance=guidance,
            subfolder="",
            note=findings_note,
            next_call=f"telec todo prepare {slug}",
            additional_context=additional_context,
        )

    # No verdict yet — dispatch reviewer; record HEAD SHA as diff anchor (I-1)
    rc, head_sha, _ = _run_git_prepare(["rev-parse", "HEAD"], cwd=cwd)
    if rc == 0 and head_sha.strip():
        req_review_dict = state.get("requirements_review", {})
        if not isinstance(req_review_dict, dict):
            req_review_dict = {}
        req_review_dict["baseline_commit"] = head_sha.strip()
        state["requirements_review"] = req_review_dict
        stamp_audit(state, "requirements_review", "baseline_commit", head_sha.strip())
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        command=SlashCommand.NEXT_REVIEW_REQUIREMENTS,
        args=slug,
        project=cwd,
        guidance=guidance,
        subfolder="",
        note=f"Review todos/{slug}/requirements.md and write verdict to state.yaml requirements_review.verdict.",
        next_call=f"telec todo prepare {slug}",
    )


async def _prepare_step_test_spec_build(
    db: Db,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """TEST_SPEC_BUILD: xfail test specs needed in worktree."""
    from teleclaude.core.next_machine.prepare_helpers import stamp_audit

    stamp_audit(state, "test_spec_build", "started_at", datetime.now(UTC).isoformat())

    if await asyncio.to_thread(_has_test_spec_artifacts, cwd, slug):
        stamp_audit(state, "test_spec_build", "completed_at", datetime.now(UTC).isoformat())
        state["prepare_phase"] = PreparePhase.TEST_SPEC_REVIEW.value
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
        _emit_prepare_event("domain.software-development.prepare.specs_drafted", {"slug": slug})
        return True, ""  # loop

    # First prepare step that needs a worktree — ensure it exists
    await ensure_worktree_with_policy_async(cwd, slug)

    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        command=SlashCommand.NEXT_BUILD_SPECS,
        args=slug,
        project=cwd,
        guidance=guidance,
        subfolder=f"{WORKTREE_DIR}/{slug}",
        note=(
            f"Read todos/{slug}/requirements.md and write xfail-marked pytest test specs "
            f"in the worktree. Each test should capture a requirement as a failing test. "
            f"Commit the specs to the worktree branch."
        ),
        next_call=f"telec todo prepare {slug}",
    )


async def _prepare_step_test_spec_review(
    db: Db,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """TEST_SPEC_REVIEW: awaiting test spec review verdict."""
    from teleclaude.core.next_machine.prepare_helpers import stamp_audit

    stamp_audit(state, "test_spec_review", "started_at", datetime.now(UTC).isoformat())

    spec_review = state.get("test_spec_review", {})
    verdict = (isinstance(spec_review, dict) and spec_review.get("verdict")) or ""

    if verdict == "approve":
        stamp_audit(state, "test_spec_review", "completed_at", datetime.now(UTC).isoformat())
        stamp_audit(state, "test_spec_review", "verdict", "approve")
        state["prepare_phase"] = PreparePhase.PLAN_DRAFTING.value
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
        _emit_prepare_event("domain.software-development.prepare.specs_approved", {"slug": slug})
        return True, ""  # loop

    if verdict == "needs_work":
        if isinstance(spec_review, dict):
            rounds = int(spec_review.get("rounds", 0)) + 1  # type: ignore[arg-type]
            spec_review["rounds"] = rounds
            spec_review["verdict"] = ""
        else:
            rounds = 1
        # Block after exceeding max review rounds to prevent infinite cycles
        if rounds > DEFAULT_MAX_REVIEW_ROUNDS:
            state["test_spec_review"] = spec_review
            state["prepare_phase"] = PreparePhase.BLOCKED.value
            await asyncio.to_thread(write_phase_state, cwd, slug, state)
            return False, (
                f"BLOCKED: {slug} test spec review exceeded {DEFAULT_MAX_REVIEW_ROUNDS} rounds. "
                f"Manual resolution required.\n\n"
                f"Before acting, load the relevant worker role:\n"
                f"  telec docs index\n"
                f"Then use telec docs get to load the procedure for the role you are assuming."
            )
        stamp_audit(state, "test_spec_review", "completed_at", datetime.now(UTC).isoformat())
        stamp_audit(state, "test_spec_review", "verdict", "needs_work")
        stamp_audit(state, "test_spec_review", "rounds", rounds)
        state["test_spec_review"] = spec_review
        state["prepare_phase"] = PreparePhase.TEST_SPEC_BUILD.value
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
        guidance = await compose_agent_guidance(db)
        return False, format_tool_call(
            command=SlashCommand.NEXT_BUILD_SPECS,
            args=slug,
            project=cwd,
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{slug}",
            note=(
                f"Test specs need revision (round {rounds}). "
                f"Review feedback and update xfail test specs in the worktree."
            ),
            next_call=f"telec todo prepare {slug}",
        )

    # No verdict yet — dispatch reviewer
    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        command=SlashCommand.NEXT_REVIEW_SPECS,
        args=slug,
        project=cwd,
        guidance=guidance,
        subfolder=f"{WORKTREE_DIR}/{slug}",
        note=f"Review xfail test specs in {WORKTREE_DIR}/{slug} and write verdict to state.yaml test_spec_review.verdict.",
        next_call=f"telec todo prepare {slug}",
    )


async def _prepare_step_plan_drafting(
    db: Db,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """PLAN_DRAFTING: implementation-plan.md needed."""
    from teleclaude.core.next_machine.prepare_helpers import stamp_audit

    stamp_audit(state, "plan_drafting", "started_at", datetime.now(UTC).isoformat())

    if check_file_has_content(cwd, f"todos/{slug}/implementation-plan.md"):
        # R16: check that all referenced_paths exist before advancing to plan review
        grounding = state.get("grounding", {})
        referenced_paths: list[str] = []
        if isinstance(grounding, dict):
            rp = grounding.get("referenced_paths", [])
            referenced_paths = [p for p in (rp if isinstance(rp, list) else []) if isinstance(p, str)]
        missing_paths = [p for p in referenced_paths if not Path(cwd, p).exists()]
        if missing_paths:
            guidance = await compose_agent_guidance(db)
            missing_list = "\n".join(f"- {p}" for p in missing_paths)
            return False, format_tool_call(
                command=SlashCommand.NEXT_PREPARE_DRAFT,
                args=slug,
                project=cwd,
                guidance=guidance,
                subfolder="",
                note=(
                    f"FIX MODE: todos/{slug}/implementation-plan.md references {len(missing_paths)} "
                    f"path(s) that do not exist in the codebase. Correct the paths or remove "
                    f"references to non-existent files, then rewrite implementation-plan.md."
                ),
                next_call=f"telec todo prepare {slug}",
                additional_context=f"Missing referenced paths:\n{missing_list}",
            )

        stamp_audit(state, "plan_drafting", "completed_at", datetime.now(UTC).isoformat())
        state["prepare_phase"] = PreparePhase.PLAN_REVIEW.value
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
        _emit_prepare_event("domain.software-development.prepare.plan_drafted", {"slug": slug})
        return True, ""  # loop

    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        command=SlashCommand.NEXT_PREPARE_DRAFT,
        args=slug,
        project=cwd,
        guidance=guidance,
        subfolder="",
        note=(
            f"Ground the approved requirements for todos/{slug}. If the work is atomic, "
            f"write todos/{slug}/implementation-plan.md and demo.md. If planning shows the "
            "parent is too large, split it into child todos and update the holder breakdown."
        ),
        next_call=f"telec todo prepare {slug}",
    )


async def _prepare_step_plan_review(
    db: Db,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """PLAN_REVIEW: awaiting plan review verdict."""
    from teleclaude.core.next_machine.prepare_helpers import stamp_audit

    stamp_audit(state, "plan_review", "started_at", datetime.now(UTC).isoformat())

    plan_review = state.get("plan_review", {})
    verdict = (isinstance(plan_review, dict) and plan_review.get("verdict")) or ""

    if verdict == "approve":
        stamp_audit(state, "plan_review", "completed_at", datetime.now(UTC).isoformat())
        stamp_audit(state, "plan_review", "verdict", "approve")
        state["prepare_phase"] = PreparePhase.GATE.value
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
        _emit_prepare_event("domain.software-development.prepare.plan_approved", {"slug": slug})
        return True, ""  # loop

    if verdict == "needs_decision":
        # Architectural blocker — requires human decision before proceeding
        findings = (isinstance(plan_review, dict) and plan_review.get("findings")) or []
        findings_list = findings if isinstance(findings, list) else []
        open_count = sum(1 for f in findings_list if isinstance(f, dict) and f.get("status") != "resolved")
        state["prepare_phase"] = PreparePhase.BLOCKED.value
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
        return False, (
            f"BLOCKED: {slug} plan has {open_count} unresolved architectural finding(s) "
            f"requiring human decision. See todos/{slug}/plan-review-findings.md.\n\n"
            f"Before acting, load the relevant worker role:\n"
            f"  telec docs index\n"
            f"Then use telec docs get to load the procedure for the role you are assuming."
        )

    if verdict == "needs_work":
        if isinstance(plan_review, dict):
            rounds = int(plan_review.get("rounds", 0)) + 1  # type: ignore[arg-type]
            plan_review["rounds"] = rounds
            plan_review["verdict"] = ""
        else:
            rounds = 1
        # I3: block after exceeding max review rounds to prevent infinite cycles
        if rounds > DEFAULT_MAX_REVIEW_ROUNDS:
            state["plan_review"] = plan_review
            state["prepare_phase"] = PreparePhase.BLOCKED.value
            await asyncio.to_thread(write_phase_state, cwd, slug, state)
            return False, (
                f"BLOCKED: {slug} plan review exceeded {DEFAULT_MAX_REVIEW_ROUNDS} rounds. "
                f"Manual resolution required.\n\n"
                f"Before acting, load the relevant worker role:\n"
                f"  telec docs index\n"
                f"Then use telec docs get to load the procedure for the role you are assuming."
            )
        # Count-and-pointer pattern: no file content injection (R2)
        findings = (isinstance(plan_review, dict) and plan_review.get("findings")) or []
        findings_list = findings if isinstance(findings, list) else []
        open_count = sum(1 for f in findings_list if isinstance(f, dict) and f.get("status") != "resolved")
        findings_note = (
            f"Implementation plan needs revision: {open_count} unresolved finding(s). "
            f"See todos/{slug}/plan-review-findings.md."
        )
        stamp_audit(state, "plan_review", "completed_at", datetime.now(UTC).isoformat())
        stamp_audit(state, "plan_review", "verdict", "needs_work")
        stamp_audit(state, "plan_review", "rounds", rounds)
        state["plan_review"] = plan_review
        state["prepare_phase"] = PreparePhase.PLAN_DRAFTING.value
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
        # Compute diff context for re-dispatch (I-2)
        from teleclaude.core.next_machine.prepare_helpers import (
            compute_artifact_diff,
            compute_todo_folder_diff,
        )

        base_sha = (isinstance(plan_review, dict) and plan_review.get("baseline_commit")) or ""
        plan_diff = compute_artifact_diff(cwd, slug, f"todos/{slug}/implementation-plan.md", str(base_sha))
        folder_diff = compute_todo_folder_diff(cwd, slug, str(base_sha))
        additional_context = "\n\n".join(filter(None, [plan_diff, folder_diff])) or ""
        # Emit scoped re-review event (I-3)
        _emit_prepare_event(
            "domain.software-development.prepare.review_scoped",
            {
                "slug": slug,
                "finding_ids": [
                    f.get("id", "")  # type: ignore[misc]
                    for f in findings_list
                    if isinstance(f, dict) and f.get("status") != "resolved"
                ],
            },
        )
        guidance = await compose_agent_guidance(db)
        return False, format_tool_call(
            command=SlashCommand.NEXT_PREPARE_DRAFT,
            args=slug,
            project=cwd,
            guidance=guidance,
            subfolder="",
            note=findings_note,
            next_call=f"telec todo prepare {slug}",
            additional_context=additional_context,
        )

    # No verdict yet — dispatch reviewer; record HEAD SHA as diff anchor (I-1)
    rc, head_sha, _ = _run_git_prepare(["rev-parse", "HEAD"], cwd=cwd)
    if rc == 0 and head_sha.strip():
        plan_review_dict = state.get("plan_review", {})
        if not isinstance(plan_review_dict, dict):
            plan_review_dict = {}
        plan_review_dict["baseline_commit"] = head_sha.strip()
        state["plan_review"] = plan_review_dict
        stamp_audit(state, "plan_review", "baseline_commit", head_sha.strip())
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        command=SlashCommand.NEXT_REVIEW_PLAN,
        args=slug,
        project=cwd,
        guidance=guidance,
        subfolder="",
        note=f"Review todos/{slug}/implementation-plan.md and write verdict to state.yaml plan_review.verdict.",
        next_call=f"telec todo prepare {slug}",
    )


async def _prepare_step_gate(
    db: Db,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """GATE: DOR formal validation."""
    dor = state.get("dor", {})
    dor_score = dor.get("score") if isinstance(dor, dict) else None

    if isinstance(dor_score, int) and dor_score >= DOR_READY_THRESHOLD:
        state["prepare_phase"] = PreparePhase.GROUNDING_CHECK.value
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
        return True, ""  # loop

    # Dispatch gate worker to run DOR assessment
    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        command=SlashCommand.NEXT_PREPARE_GATE,
        args=slug,
        project=cwd,
        guidance=guidance,
        subfolder="",
        note=(
            f"Requirements/plan exist for {slug}, but DOR score is below threshold. "
            f"Complete DOR assessment and set state.yaml.dor.score >= {DOR_READY_THRESHOLD}."
        ),
        next_call=f"telec todo prepare {slug}",
    )


def _prepare_step_grounding_check(
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """GROUNDING_CHECK: mechanical freshness check (no agent dispatch)."""
    grounding = state.get("grounding", {})
    grounding_dict = {**DEFAULT_STATE["grounding"], **(grounding if isinstance(grounding, dict) else {})}  # type: ignore

    base_sha = str(grounding_dict.get("base_sha", ""))
    stored_input_digest = str(grounding_dict.get("input_digest", ""))
    referenced_paths = grounding_dict.get("referenced_paths", [])
    if not isinstance(referenced_paths, list):
        referenced_paths = []

    # Get current HEAD
    rc, current_sha, _ = _run_git_prepare(["rev-parse", "HEAD"], cwd=cwd)
    current_sha = current_sha.strip() if rc == 0 else ""

    # Get current input digest
    input_path = Path(cwd) / "todos" / slug / "input.md"
    current_input_digest = ""
    if input_path.exists():
        current_input_digest = hashlib.sha256(input_path.read_bytes()).hexdigest()

    now = datetime.now(UTC).isoformat()

    # First grounding: capture state and transition to PREPARED
    if not base_sha:
        grounding_dict["base_sha"] = current_sha
        grounding_dict["input_digest"] = current_input_digest
        grounding_dict["last_grounded_at"] = now
        grounding_dict["valid"] = True
        state["grounding"] = grounding_dict
        state["prepare_phase"] = PreparePhase.PREPARED.value
        write_phase_state(cwd, slug, state)
        _emit_prepare_event("domain.software-development.prepare.completed", {"slug": slug})
        return True, ""  # loop to PREPARED terminal

    # I2: git failure is fail-closed — treat missing sha as stale if we have a stored base
    if not current_sha and base_sha:
        logger.warning("GROUNDING_CHECK: git rev-parse HEAD failed for %s, treating as stale", slug)
        reason = "files_changed"
        grounding_dict["valid"] = False
        grounding_dict["invalidated_at"] = now
        grounding_dict["invalidation_reason"] = reason
        grounding_dict["changed_paths"] = []
        state["grounding"] = grounding_dict
        state["prepare_phase"] = PreparePhase.RE_GROUNDING.value
        write_phase_state(cwd, slug, state)
        _emit_prepare_event(
            "domain.software-development.prepare.grounding_invalidated",
            {"slug": slug, "reason": reason, "changed_paths": []},
        )
        return True, ""  # loop to RE_GROUNDING

    # Check for staleness
    sha_changed = bool(current_sha and current_sha != base_sha)
    # Backward compatibility: empty stored digest means "not yet recorded", not "changed".
    # Also treat wrong-length digests (e.g. MD5 written by agents) as unrecorded.
    digest_changed = bool(
        stored_input_digest
        and current_input_digest
        and len(stored_input_digest) == len(current_input_digest)
        and current_input_digest != stored_input_digest
    )

    # Check if referenced paths changed between base_sha and HEAD
    changed_paths: list[str] = []
    if sha_changed and referenced_paths and base_sha and current_sha:
        rc2, diff_output, _ = _run_git_prepare(["diff", "--name-only", f"{base_sha}..{current_sha}"], cwd=cwd)
        if rc2 == 0:
            changed_files = {line.strip() for line in diff_output.splitlines() if line.strip()}
            changed_paths = [p for p in referenced_paths if p in changed_files]  # type: ignore[misc]

    # Grounding staleness semantics:
    # - Always stale when input digest changed.
    # - If referenced paths are known, only stale when those paths changed.
    # - Fall back to sha-level staleness only when referenced paths are unavailable.
    references_known = bool(referenced_paths)
    paths_stale = bool(changed_paths)
    sha_fallback_stale = sha_changed and not references_known
    is_stale = bool(digest_changed) or paths_stale or sha_fallback_stale

    if is_stale:
        reason = "input_updated" if digest_changed else "files_changed"
        grounding_dict["valid"] = False
        grounding_dict["invalidated_at"] = now
        grounding_dict["invalidation_reason"] = reason
        grounding_dict["changed_paths"] = changed_paths  # type: ignore[assignment]  # I1: persist actual changed paths
        state["grounding"] = grounding_dict
        state["prepare_phase"] = PreparePhase.RE_GROUNDING.value
        write_phase_state(cwd, slug, state)
        _emit_prepare_event(
            "domain.software-development.prepare.grounding_invalidated",
            {"slug": slug, "reason": reason, "changed_paths": changed_paths},
        )
        return True, ""  # loop to RE_GROUNDING

    # Fresh — transition to PREPARED
    grounding_dict["base_sha"] = current_sha
    grounding_dict["input_digest"] = current_input_digest
    grounding_dict["last_grounded_at"] = now
    grounding_dict["valid"] = True
    state["grounding"] = grounding_dict
    state["prepare_phase"] = PreparePhase.PREPARED.value
    write_phase_state(cwd, slug, state)
    _emit_prepare_event("domain.software-development.prepare.completed", {"slug": slug})
    return True, ""  # loop to PREPARED terminal


async def _prepare_step_re_grounding(
    db: Db,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """RE_GROUNDING: dispatch plan update against changed files."""
    grounding = state.get("grounding", {})
    grounding_dict = {**DEFAULT_STATE["grounding"], **(grounding if isinstance(grounding, dict) else {})}  # type: ignore
    changed_paths = grounding_dict.get("changed_paths", [])  # I1: actual changed paths, not all referenced
    if not isinstance(changed_paths, list):
        changed_paths = []
    else:
        changed_paths = [path for path in changed_paths if isinstance(path, str)]

    # Set next phase to PLAN_REVIEW so re-grounded plan gets reviewed
    state["prepare_phase"] = PreparePhase.PLAN_REVIEW.value
    # Reset plan review verdict so fresh review runs
    plan_review = state.get("plan_review", {})
    if isinstance(plan_review, dict):
        plan_review["verdict"] = ""
    state["plan_review"] = plan_review
    await asyncio.to_thread(write_phase_state, cwd, slug, state)

    changed_note = f"Changed files: {', '.join(changed_paths)}" if changed_paths else "Codebase has evolved."  # type: ignore[arg-type]
    guidance = await compose_agent_guidance(db)
    result = format_tool_call(
        command=SlashCommand.NEXT_PREPARE_DRAFT,
        args=slug,
        project=cwd,
        guidance=guidance,
        subfolder="",
        note=f"Update todos/{slug}/implementation-plan.md against current codebase. {changed_note}",
        next_call=f"telec todo prepare {slug}",
    )
    _emit_prepare_event("domain.software-development.prepare.regrounded", {"slug": slug})
    return False, result


def _prepare_step_prepared(slug: str) -> tuple[bool, str]:
    """PREPARED: terminal success state."""
    return False, format_prepared(slug)


def _prepare_step_blocked(slug: str, state: dict[str, StateValue]) -> tuple[bool, str]:
    """BLOCKED: terminal failure state."""
    grounding = state.get("grounding", {})
    blocker = str(grounding.get("invalidation_reason", "unknown")) if isinstance(grounding, dict) else "unknown"
    _emit_prepare_event(
        "domain.software-development.prepare.blocked",
        {"slug": slug, "blocker": blocker},
    )
    return False, (
        f"BLOCKED: {slug} requires human decision. "
        f"Reason: {blocker}. "
        f"Inspect todos/{slug}/state.yaml and resolve the blocker manually."
    )


# =============================================================================
# Prepare State Machine — step dispatcher
# =============================================================================


async def _prepare_dispatch(
    *,
    db: Db,
    slug: str,
    cwd: str,
    phase: PreparePhase,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """Dispatch to the appropriate phase handler. Returns (continue_loop, instruction)."""
    if phase == PreparePhase.INPUT_ASSESSMENT:
        return await _prepare_step_input_assessment(db, slug, cwd, state)
    if phase == PreparePhase.TRIANGULATION:
        return await _prepare_step_triangulation(db, slug, cwd, state)
    if phase == PreparePhase.REQUIREMENTS_REVIEW:
        return await _prepare_step_requirements_review(db, slug, cwd, state)
    if phase == PreparePhase.TEST_SPEC_BUILD:
        return await _prepare_step_test_spec_build(db, slug, cwd, state)
    if phase == PreparePhase.TEST_SPEC_REVIEW:
        return await _prepare_step_test_spec_review(db, slug, cwd, state)
    if phase == PreparePhase.PLAN_DRAFTING:
        return await _prepare_step_plan_drafting(db, slug, cwd, state)
    if phase == PreparePhase.PLAN_REVIEW:
        return await _prepare_step_plan_review(db, slug, cwd, state)
    if phase == PreparePhase.GATE:
        return await _prepare_step_gate(db, slug, cwd, state)
    if phase == PreparePhase.GROUNDING_CHECK:
        return await asyncio.to_thread(_prepare_step_grounding_check, slug, cwd, state)
    if phase == PreparePhase.RE_GROUNDING:
        return await _prepare_step_re_grounding(db, slug, cwd, state)
    if phase == PreparePhase.PREPARED:
        return _prepare_step_prepared(slug)
    if phase == PreparePhase.BLOCKED:
        return _prepare_step_blocked(slug, state)
    return False, f"UNHANDLED_PHASE: No handler for prepare phase: {phase.value}"


__all__ = ["_prepare_dispatch"]
