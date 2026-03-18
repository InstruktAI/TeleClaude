"""Prepare state machine — phase step handlers and dispatcher.

No imports from core.py (circular-import guard).
Note: _has_test_spec_artifacts lives in prepare_events.py (co-located with _derive_prepare_phase).
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
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
from teleclaude.core.next_machine.output_formatting import ToolCallRequest, format_prepared, format_tool_call
from teleclaude.core.next_machine.prepare_events import (
    _emit_prepare_event,
    _has_test_spec_artifacts,
    _is_artifact_produced_v2,
)
from teleclaude.core.next_machine.prepare_helpers import (
    compute_artifact_diff,
    compute_todo_folder_diff,
    record_input_consumed,
    stamp_audit,
)
from teleclaude.core.next_machine.state_io import _run_git_prepare, write_phase_state
from teleclaude.core.next_machine.worktrees import ensure_worktree_with_policy_async

logger = get_logger(__name__)


@dataclass(frozen=True)
class _PrepareDispatch:
    command: str
    subfolder: str
    note: str
    additional_context: str = ""


@dataclass(frozen=True)
class _PrepareStateContext:
    slug: str
    cwd: str
    state: dict[str, StateValue]


@dataclass(frozen=True)
class _ReviewReworkConfig:
    review_key: str
    review_label: str
    rework_phase: PreparePhase
    redispatch: _PrepareDispatch
    artifact_path: str


@dataclass(frozen=True)
class _GroundingTransition:
    phase: PreparePhase
    event_type: str
    event_payload: dict[str, str | list[str]]


@dataclass(frozen=True)
class _GroundingSnapshot:
    grounding_dict: dict[str, object]
    base_sha: str
    stored_input_digest: str
    referenced_paths: list[str]
    current_sha: str
    current_input_digest: str
    now: str


def _review_findings(review_state: object) -> list[dict[str, object]]:
    """Return normalized unresolved-review findings input."""
    findings = (isinstance(review_state, dict) and review_state.get("findings")) or []
    return [item for item in findings if isinstance(item, dict)] if isinstance(findings, list) else []


def _open_findings_count(findings: list[dict[str, object]]) -> int:
    """Count unresolved findings."""
    return sum(1 for finding in findings if finding.get("status") != "resolved")


def _unresolved_finding_ids(findings: list[dict[str, object]]) -> list[str]:
    """Extract unresolved finding identifiers for event payloads."""
    return [str(finding.get("id", "")) for finding in findings if finding.get("status") != "resolved"]


def _manual_resolution_message(slug: str, review_label: str) -> str:
    """Build the standard manual-resolution block."""
    return (
        f"BLOCKED: {slug} {review_label} review exceeded {DEFAULT_MAX_REVIEW_ROUNDS} rounds. "
        f"Manual resolution required.\n\n"
        f"Before acting, load the relevant worker role:\n"
        f"  telec docs index\n"
        f"Then use telec docs get to load the procedure for the role you are assuming."
    )


def _decision_block_message(slug: str, review_label: str, findings_path: str, open_count: int) -> str:
    """Build the standard decision-required block."""
    return (
        f"BLOCKED: {slug} {review_label} has {open_count} unresolved architectural finding(s) "
        f"requiring human decision. See todos/{slug}/{findings_path}.\n\n"
        f"Before acting, load the relevant worker role:\n"
        f"  telec docs index\n"
        f"Then use telec docs get to load the procedure for the role you are assuming."
    )


def _updated_review_state(review_state: object) -> tuple[dict[str, object], int]:
    """Increment review rounds and clear the prior verdict."""
    review_dict = dict(review_state) if isinstance(review_state, dict) else {}
    rounds = int(review_dict.get("rounds", 0)) + 1
    review_dict["rounds"] = rounds
    review_dict["verdict"] = ""
    return review_dict, rounds


def _review_diff_context(cwd: str, slug: str, artifact_path: str, base_sha: str) -> str:
    """Build re-dispatch diff context for review revision loops."""
    artifact_diff = compute_artifact_diff(cwd, artifact_path, base_sha)
    folder_diff = compute_todo_folder_diff(cwd, slug, base_sha)
    return "\n\n".join(filter(None, [artifact_diff, folder_diff])) or ""


async def _record_review_baseline(
    cwd: str,
    slug: str,
    state: dict[str, StateValue],
    review_key: str,
) -> None:
    """Persist the current HEAD SHA as the review diff baseline."""
    rc, head_sha, _ = _run_git_prepare(["rev-parse", "HEAD"], cwd=cwd)
    if rc != 0 or not head_sha.strip():
        return
    review_dict = state.get(review_key, {})
    if not isinstance(review_dict, dict):
        review_dict = {}
    review_dict["baseline_commit"] = head_sha.strip()
    state[review_key] = review_dict
    stamp_audit(state, review_key, "baseline_commit", head_sha.strip())
    await asyncio.to_thread(write_phase_state, cwd, slug, state)


async def _format_prepare_dispatch(
    db: Db,
    slug: str,
    cwd: str,
    request: _PrepareDispatch,
) -> tuple[bool, str]:
    """Compose the standard prepare-phase tool call."""
    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        ToolCallRequest(
            command=request.command,
            args=slug,
            project=cwd,
            guidance=guidance,
            subfolder=request.subfolder,
            note=request.note,
            next_call=f"telec todo prepare {slug}",
            additional_context=request.additional_context,
        )
    )


async def _handle_review_needs_decision(
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
    message: str,
) -> tuple[bool, str]:
    """Transition to BLOCKED when review findings require a human decision."""
    state["prepare_phase"] = PreparePhase.BLOCKED.value
    await asyncio.to_thread(write_phase_state, cwd, slug, state)
    return False, message


async def _handle_review_needs_work(
    db: Db,
    context: _PrepareStateContext,
    config: _ReviewReworkConfig,
    review_state: object,
    findings: list[dict[str, object]],
) -> tuple[bool, str]:
    """Handle review revision loops with round counting and diff context."""
    review_dict, rounds = _updated_review_state(review_state)
    if rounds > DEFAULT_MAX_REVIEW_ROUNDS:
        context.state[config.review_key] = review_dict
        context.state["prepare_phase"] = PreparePhase.BLOCKED.value
        await asyncio.to_thread(write_phase_state, context.cwd, context.slug, context.state)
        return False, _manual_resolution_message(context.slug, config.review_label)

    stamp_audit(context.state, config.review_key, "completed_at", datetime.now(UTC).isoformat())
    stamp_audit(context.state, config.review_key, "verdict", "needs_work")
    stamp_audit(context.state, config.review_key, "rounds", rounds)
    context.state[config.review_key] = review_dict
    context.state["prepare_phase"] = config.rework_phase.value
    await asyncio.to_thread(write_phase_state, context.cwd, context.slug, context.state)
    _emit_prepare_event(
        "domain.software-development.prepare.review_scoped",
        {"slug": context.slug, "finding_ids": _unresolved_finding_ids(findings)},
    )
    additional_context = _review_diff_context(
        context.cwd,
        context.slug,
        config.artifact_path,
        str(review_dict.get("baseline_commit", "")),
    )
    return await _format_prepare_dispatch(
        db,
        context.slug,
        context.cwd,
        _PrepareDispatch(
            command=config.redispatch.command,
            subfolder=config.redispatch.subfolder,
            note=config.redispatch.note,
            additional_context=additional_context,
        ),
    )


def _current_input_digest(cwd: str, slug: str) -> str:
    """Return the current input digest when the input file exists."""
    input_path = Path(cwd) / "todos" / slug / "input.md"
    if not input_path.exists():
        return ""
    return hashlib.sha256(input_path.read_bytes()).hexdigest()


def _transition_grounding_phase(
    cwd: str,
    slug: str,
    state: dict[str, StateValue],
    grounding_dict: dict[str, object],
    transition: _GroundingTransition,
) -> tuple[bool, str]:
    """Persist grounding state and emit the matching lifecycle event."""
    state["grounding"] = grounding_dict  # type: ignore[assignment]
    state["prepare_phase"] = transition.phase.value
    write_phase_state(cwd, slug, state)
    _emit_prepare_event(transition.event_type, transition.event_payload)
    return True, ""


def _changed_referenced_paths(
    cwd: str,
    base_sha: str,
    current_sha: str,
    referenced_paths: list[str],
) -> list[str]:
    """Return referenced paths changed between the two commits."""
    if not (referenced_paths and base_sha and current_sha):
        return []
    rc, diff_output, _ = _run_git_prepare(["diff", "--name-only", f"{base_sha}..{current_sha}"], cwd=cwd)
    if rc != 0:
        return []
    changed_files = {line.strip() for line in diff_output.splitlines() if line.strip()}
    return [path for path in referenced_paths if path in changed_files]


def _grounding_snapshot(cwd: str, slug: str, state: dict[str, StateValue]) -> _GroundingSnapshot:
    """Capture grounding state and current repository inputs."""
    grounding = state.get("grounding", {})
    grounding_dict = {
        **DEFAULT_STATE["grounding"],
        **(grounding if isinstance(grounding, dict) else {}),
    }
    referenced_paths = grounding_dict.get("referenced_paths", [])
    if not isinstance(referenced_paths, list):
        referenced_paths = []
    rc, current_sha, _ = _run_git_prepare(["rev-parse", "HEAD"], cwd=cwd)
    return _GroundingSnapshot(
        grounding_dict=grounding_dict,
        base_sha=str(grounding_dict.get("base_sha", "")),
        stored_input_digest=str(grounding_dict.get("input_digest", "")),
        referenced_paths=referenced_paths,
        current_sha=current_sha.strip() if rc == 0 else "",
        current_input_digest=_current_input_digest(cwd, slug),
        now=datetime.now(UTC).isoformat(),
    )


async def _prepare_step_input_assessment(
    db: Db,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """INPUT_ASSESSMENT: choose requirements strategy and produce requirements."""
    _now = datetime.now(UTC).isoformat()
    stamp_audit(state, "input_assessment", "started_at", _now)

    has_requirements = check_file_has_content(cwd, f"todos/{slug}/requirements.md")
    # Ghost artifact protection: v2 state requires produced_at stamp, not just file presence
    if has_requirements and not _is_artifact_produced_v2(state, "requirements"):
        has_requirements = False
    if has_requirements:
        # Emit input_consumed event before transitioning (R13)
        await asyncio.to_thread(record_input_consumed, cwd, slug)
        stamp_audit(state, "input_assessment", "completed_at", datetime.now(UTC).isoformat())
        state["prepare_phase"] = PreparePhase.REQUIREMENTS_REVIEW.value
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
        return True, ""  # loop

    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        ToolCallRequest(
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
    )


async def _prepare_step_triangulation(
    db: Db,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """TRIANGULATION: requirements.md still needs discovery or revision."""
    has_requirements = check_file_has_content(cwd, f"todos/{slug}/requirements.md")
    # Ghost artifact protection: v2 state requires produced_at stamp, not just file presence
    if has_requirements and not _is_artifact_produced_v2(state, "requirements"):
        has_requirements = False
    if has_requirements:
        # Transition to REQUIREMENTS_REVIEW
        state["prepare_phase"] = PreparePhase.REQUIREMENTS_REVIEW.value
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
        _emit_prepare_event("domain.software-development.prepare.requirements_drafted", {"slug": slug})
        return True, ""  # loop

    _emit_prepare_event("domain.software-development.prepare.triangulation_started", {"slug": slug})
    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        ToolCallRequest(
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
    )


async def _prepare_step_requirements_review(
    db: Db,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """REQUIREMENTS_REVIEW: awaiting review verdict."""
    stamp_audit(state, "requirements_review", "started_at", datetime.now(UTC).isoformat())

    req_review = state.get("requirements_review", {})
    verdict = (isinstance(req_review, dict) and req_review.get("verdict")) or ""
    findings = _review_findings(req_review)

    if verdict == "approve":
        stamp_audit(state, "requirements_review", "completed_at", datetime.now(UTC).isoformat())
        stamp_audit(state, "requirements_review", "verdict", "approve")
        state["prepare_phase"] = PreparePhase.TEST_SPEC_BUILD.value
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
        _emit_prepare_event("domain.software-development.prepare.requirements_approved", {"slug": slug})
        return True, ""  # loop

    if verdict == "needs_decision":
        return await _handle_review_needs_decision(
            slug,
            cwd,
            state,
            _decision_block_message(
                slug,
                "requirements",
                "requirements-review-findings.md",
                _open_findings_count(findings),
            ),
        )

    if verdict == "needs_work":
        return await _handle_review_needs_work(
            db,
            _PrepareStateContext(slug=slug, cwd=cwd, state=state),
            _ReviewReworkConfig(
                review_key="requirements_review",
                review_label="requirements",
                rework_phase=PreparePhase.TRIANGULATION,
                redispatch=_PrepareDispatch(
                    command=SlashCommand.NEXT_PREPARE_DISCOVERY,
                    subfolder="",
                    note=(
                        f"Requirements need revision: {_open_findings_count(findings)} unresolved "
                        f"finding(s). See todos/{slug}/requirements-review-findings.md."
                    ),
                ),
                artifact_path=f"todos/{slug}/requirements.md",
            ),
            review_state=req_review,
            findings=findings,
        )

    # No verdict yet — dispatch reviewer; record HEAD SHA as diff anchor (I-1)
    await _record_review_baseline(cwd, slug, state, "requirements_review")
    return await _format_prepare_dispatch(
        db,
        slug,
        cwd,
        _PrepareDispatch(
            command=SlashCommand.NEXT_REVIEW_REQUIREMENTS,
            subfolder="",
            note=(f"Review todos/{slug}/requirements.md and write verdict to state.yaml requirements_review.verdict."),
        ),
    )


async def _prepare_step_test_spec_build(
    db: Db,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """TEST_SPEC_BUILD: xfail test specs needed in worktree."""
    stamp_audit(state, "test_spec_build", "started_at", datetime.now(UTC).isoformat())

    has_test_specs = await asyncio.to_thread(_has_test_spec_artifacts, cwd, slug)
    # Ghost artifact protection: v2 state requires produced_at stamp, not just file presence
    if has_test_specs and not _is_artifact_produced_v2(state, "test_specs"):
        has_test_specs = False
    if has_test_specs:
        stamp_audit(state, "test_spec_build", "completed_at", datetime.now(UTC).isoformat())
        state["prepare_phase"] = PreparePhase.TEST_SPEC_REVIEW.value
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
        _emit_prepare_event("domain.software-development.prepare.specs_drafted", {"slug": slug})
        return True, ""  # loop

    # First prepare step that needs a worktree — ensure it exists
    await ensure_worktree_with_policy_async(cwd, slug)

    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        ToolCallRequest(
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
    )


async def _prepare_step_test_spec_review(
    db: Db,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """TEST_SPEC_REVIEW: awaiting test spec review verdict."""
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
            ToolCallRequest(
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
        )

    # No verdict yet — dispatch reviewer
    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        ToolCallRequest(
            command=SlashCommand.NEXT_REVIEW_SPECS,
            args=slug,
            project=cwd,
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{slug}",
            note=(
                f"Review xfail test specs in {WORKTREE_DIR}/{slug} and write verdict to state.yaml "
                "test_spec_review.verdict."
            ),
            next_call=f"telec todo prepare {slug}",
        )
    )


async def _prepare_step_plan_drafting(
    db: Db,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """PLAN_DRAFTING: implementation-plan.md needed."""
    stamp_audit(state, "plan_drafting", "started_at", datetime.now(UTC).isoformat())

    has_plan = check_file_has_content(cwd, f"todos/{slug}/implementation-plan.md")
    # Ghost artifact protection: v2 state requires produced_at stamp, not just file presence
    if has_plan and not _is_artifact_produced_v2(state, "implementation_plan"):
        has_plan = False
    if has_plan:
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
                ToolCallRequest(
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
            )

        stamp_audit(state, "plan_drafting", "completed_at", datetime.now(UTC).isoformat())
        state["prepare_phase"] = PreparePhase.PLAN_REVIEW.value
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
        _emit_prepare_event("domain.software-development.prepare.plan_drafted", {"slug": slug})
        return True, ""  # loop

    guidance = await compose_agent_guidance(db)
    return False, format_tool_call(
        ToolCallRequest(
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
    )


async def _prepare_step_plan_review(
    db: Db,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """PLAN_REVIEW: awaiting plan review verdict."""
    stamp_audit(state, "plan_review", "started_at", datetime.now(UTC).isoformat())

    plan_review = state.get("plan_review", {})
    verdict = (isinstance(plan_review, dict) and plan_review.get("verdict")) or ""
    findings = _review_findings(plan_review)

    if verdict == "approve":
        stamp_audit(state, "plan_review", "completed_at", datetime.now(UTC).isoformat())
        stamp_audit(state, "plan_review", "verdict", "approve")
        state["prepare_phase"] = PreparePhase.GATE.value
        await asyncio.to_thread(write_phase_state, cwd, slug, state)
        _emit_prepare_event("domain.software-development.prepare.plan_approved", {"slug": slug})
        return True, ""  # loop

    if verdict == "needs_decision":
        return await _handle_review_needs_decision(
            slug,
            cwd,
            state,
            _decision_block_message(
                slug,
                "plan",
                "plan-review-findings.md",
                _open_findings_count(findings),
            ),
        )

    if verdict == "needs_work":
        return await _handle_review_needs_work(
            db,
            _PrepareStateContext(slug=slug, cwd=cwd, state=state),
            _ReviewReworkConfig(
                review_key="plan_review",
                review_label="plan",
                rework_phase=PreparePhase.PLAN_DRAFTING,
                redispatch=_PrepareDispatch(
                    command=SlashCommand.NEXT_PREPARE_DRAFT,
                    subfolder="",
                    note=(
                        "Implementation plan needs revision: "
                        f"{_open_findings_count(findings)} unresolved finding(s). "
                        f"See todos/{slug}/plan-review-findings.md."
                    ),
                ),
                artifact_path=f"todos/{slug}/implementation-plan.md",
            ),
            review_state=plan_review,
            findings=findings,
        )

    # No verdict yet — dispatch reviewer; record HEAD SHA as diff anchor (I-1)
    await _record_review_baseline(cwd, slug, state, "plan_review")
    return await _format_prepare_dispatch(
        db,
        slug,
        cwd,
        _PrepareDispatch(
            command=SlashCommand.NEXT_REVIEW_PLAN,
            subfolder="",
            note=(f"Review todos/{slug}/implementation-plan.md and write verdict to state.yaml plan_review.verdict."),
        ),
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
        ToolCallRequest(
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
    )


def _prepare_step_grounding_check(
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """GROUNDING_CHECK: mechanical freshness check (no agent dispatch)."""
    snapshot = _grounding_snapshot(cwd, slug, state)

    if not snapshot.base_sha:
        snapshot.grounding_dict["base_sha"] = snapshot.current_sha
        snapshot.grounding_dict["input_digest"] = snapshot.current_input_digest
        snapshot.grounding_dict["last_grounded_at"] = snapshot.now
        snapshot.grounding_dict["valid"] = True
        return _transition_grounding_phase(
            cwd,
            slug,
            state,
            snapshot.grounding_dict,
            _GroundingTransition(
                phase=PreparePhase.PREPARED,
                event_type="domain.software-development.prepare.completed",
                event_payload={"slug": slug},
            ),
        )

    if not snapshot.current_sha and snapshot.base_sha:
        logger.warning("GROUNDING_CHECK: git rev-parse HEAD failed for %s, treating as stale", slug)
        snapshot.grounding_dict["valid"] = False
        snapshot.grounding_dict["invalidated_at"] = snapshot.now
        snapshot.grounding_dict["invalidation_reason"] = "files_changed"
        snapshot.grounding_dict["changed_paths"] = []
        return _transition_grounding_phase(
            cwd,
            slug,
            state,
            snapshot.grounding_dict,
            _GroundingTransition(
                phase=PreparePhase.RE_GROUNDING,
                event_type="domain.software-development.prepare.grounding_invalidated",
                event_payload={"slug": slug, "reason": "files_changed", "changed_paths": []},
            ),
        )

    sha_changed = bool(snapshot.current_sha and snapshot.current_sha != snapshot.base_sha)
    digest_changed = bool(
        snapshot.stored_input_digest
        and snapshot.current_input_digest
        and len(snapshot.stored_input_digest) == len(snapshot.current_input_digest)
        and snapshot.current_input_digest != snapshot.stored_input_digest
    )
    changed_paths = _changed_referenced_paths(
        cwd,
        snapshot.base_sha,
        snapshot.current_sha,
        snapshot.referenced_paths,
    )
    references_known = bool(snapshot.referenced_paths)
    paths_stale = bool(changed_paths)
    sha_fallback_stale = sha_changed and not references_known
    is_stale = bool(digest_changed) or paths_stale or sha_fallback_stale

    if is_stale:
        reason = "input_updated" if digest_changed else "files_changed"
        snapshot.grounding_dict["valid"] = False
        snapshot.grounding_dict["invalidated_at"] = snapshot.now
        snapshot.grounding_dict["invalidation_reason"] = reason
        snapshot.grounding_dict["changed_paths"] = changed_paths
        return _transition_grounding_phase(
            cwd,
            slug,
            state,
            snapshot.grounding_dict,
            _GroundingTransition(
                phase=PreparePhase.RE_GROUNDING,
                event_type="domain.software-development.prepare.grounding_invalidated",
                event_payload={"slug": slug, "reason": reason, "changed_paths": changed_paths},
            ),
        )

    snapshot.grounding_dict["base_sha"] = snapshot.current_sha
    snapshot.grounding_dict["input_digest"] = snapshot.current_input_digest
    snapshot.grounding_dict["last_grounded_at"] = snapshot.now
    snapshot.grounding_dict["valid"] = True
    return _transition_grounding_phase(
        cwd,
        slug,
        state,
        snapshot.grounding_dict,
        _GroundingTransition(
            phase=PreparePhase.PREPARED,
            event_type="domain.software-development.prepare.completed",
            event_payload={"slug": slug},
        ),
    )


async def _prepare_step_re_grounding(
    db: Db,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """RE_GROUNDING: dispatch plan update against changed files."""
    grounding = state.get("grounding", {})
    grounding_dict = {
        **DEFAULT_STATE["grounding"],
        **(grounding if isinstance(grounding, dict) else {}),
    }  # type: ignore
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

    changed_note = f"Changed files: {', '.join(changed_paths)}" if changed_paths else "Codebase has evolved."
    guidance = await compose_agent_guidance(db)
    result = format_tool_call(
        ToolCallRequest(
            command=SlashCommand.NEXT_PREPARE_DRAFT,
            args=slug,
            project=cwd,
            guidance=guidance,
            subfolder="",
            note=f"Update todos/{slug}/implementation-plan.md against current codebase. {changed_note}",
            next_call=f"telec todo prepare {slug}",
        )
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
    async_handlers = {
        PreparePhase.INPUT_ASSESSMENT: _prepare_step_input_assessment,
        PreparePhase.TRIANGULATION: _prepare_step_triangulation,
        PreparePhase.REQUIREMENTS_REVIEW: _prepare_step_requirements_review,
        PreparePhase.TEST_SPEC_BUILD: _prepare_step_test_spec_build,
        PreparePhase.TEST_SPEC_REVIEW: _prepare_step_test_spec_review,
        PreparePhase.PLAN_DRAFTING: _prepare_step_plan_drafting,
        PreparePhase.PLAN_REVIEW: _prepare_step_plan_review,
        PreparePhase.GATE: _prepare_step_gate,
        PreparePhase.RE_GROUNDING: _prepare_step_re_grounding,
    }
    if phase in async_handlers:
        return await async_handlers[phase](db, slug, cwd, state)
    if phase == PreparePhase.GROUNDING_CHECK:
        return await asyncio.to_thread(_prepare_step_grounding_check, slug, cwd, state)
    if phase == PreparePhase.PREPARED:
        return _prepare_step_prepared(slug)
    if phase == PreparePhase.BLOCKED:
        return _prepare_step_blocked(slug, state)
    return False, f"UNHANDLED_PHASE: No handler for prepare phase: {phase.value}"


__all__ = ["_prepare_dispatch"]
