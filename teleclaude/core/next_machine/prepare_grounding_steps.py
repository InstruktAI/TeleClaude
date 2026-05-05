"""Grounding-related prepare step handlers.

Extracted from prepare_steps.py to keep that module under the size cap. These
handlers run after artifact reviews complete and validate that the codebase
hasn't drifted from the state at which artifacts were grounded. When drift is
detected, the plan drafter is re-dispatched with the changed-paths context.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR, SlashCommand
from teleclaude.core.db import Db
from teleclaude.core.next_machine import prepare_step_support
from teleclaude.core.next_machine._types import PreparePhase, StateValue
from teleclaude.core.next_machine.git_ops import compose_agent_guidance, run_git_command
from teleclaude.core.next_machine.lifecycle import apply_authoritative_signal
from teleclaude.core.next_machine.output_formatting import ToolCallRequest, format_tool_call
from teleclaude.core.next_machine.prepare_diff_dispatch import DispatchReason, format_dispatch_reason
from teleclaude.core.next_machine.prepare_events import _emit_prepare_event
from teleclaude.core.next_machine.prepare_pair import (
    PRODUCTION_ROLES,
    format_pair_write_or_recovery_script,
    pair_writer_reviewer_slots,
)
from teleclaude.core.next_machine.state_mutation import GroundingManager, StateWriter

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb


logger = get_logger(__name__)

_commit_writer = prepare_step_support.commit_writer
_derive_project_root = prepare_step_support.derive_project_root
_derive_worktree_cwd = prepare_step_support.derive_worktree_cwd
_worker_idle_post_block = prepare_step_support.worker_idle_post_block


async def prepare_step_grounding_check(
    db: Db,
    todos_db: TodosDb,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """GROUNDING_CHECK: mechanical freshness check + stale re-anchor."""
    writer = StateWriter(state)
    grounding_mgr = GroundingManager(writer)
    base_sha = writer.grounding.base_sha

    git_cwd = _derive_worktree_cwd(cwd, slug)
    rc, current_sha_raw, _ = run_git_command(["rev-parse", "HEAD"], cwd=git_cwd)
    current_sha = current_sha_raw.strip() if rc == 0 else ""

    current_input_digest = ""
    input_content = todos_db.read_artifact_sync(slug, "input")
    if input_content:
        current_input_digest = hashlib.sha256(input_content.encode("utf-8")).hexdigest()

    # First grounding: capture baseline and advance through the authoritative grounding signal.
    if not base_sha:
        grounding_mgr.capture_fresh(current_sha=current_sha, current_input_digest=current_input_digest)
        apply_authoritative_signal(writer.state, "grounding")
        await _commit_writer(writer, todos_db, slug, state)
        _emit_prepare_event("domain.software-development.prepare.completed", {"slug": slug})
        return True, ""

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
        rc2, diff_output, _ = run_git_command(["diff", "--name-only", f"{base_sha}..{current_sha}"], cwd=git_cwd)
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

    # Fresh — refresh baseline and advance through the authoritative grounding signal.
    grounding_mgr.capture_fresh(current_sha=current_sha, current_input_digest=current_input_digest)
    apply_authoritative_signal(writer.state, "grounding")
    await _commit_writer(writer, todos_db, slug, state)
    _emit_prepare_event("domain.software-development.prepare.completed", {"slug": slug})
    return True, ""


async def _handle_stale_grounding(
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
    """Re-anchor grounding and dispatch a plan update against changed files."""
    _emit_prepare_event(
        "domain.software-development.prepare.grounding_invalidated",
        {"slug": slug, "reason": reason, "changed_paths": changed_paths},
    )

    if current_sha:
        grounding_mgr.refresh(current_sha=current_sha)
    else:
        grounding_mgr.invalidate(reason=reason, changed_paths=changed_paths)

    apply_authoritative_signal(writer.state, "grounding_invalidated")
    await _commit_writer(writer, todos_db, slug, state)

    changed_note = f"Changed files: {', '.join(changed_paths)}" if changed_paths else "Codebase has evolved."
    note = format_dispatch_reason(
        (
            f"Update the implementation plan via `telec todo artifacts read {slug} implementation-plan` + "
            f"`telec todo artifacts write {slug} implementation-plan <content>`, then "
            f"stamp via `telec todo stamp {slug} --plan-ready`. {changed_note}"
        ),
        slug,
        DispatchReason.UPSTREAM_CHANGED,
    )
    pair_slots = pair_writer_reviewer_slots(state, PreparePhase.PLAN_DRAFTING, PRODUCTION_ROLES)
    if pair_slots is not None:
        writer_slot, reviewer_slot = pair_slots
        instruction = await format_pair_write_or_recovery_script(
            db=db,
            slug=slug,
            writer_slot=writer_slot,
            reviewer_slot=reviewer_slot,
            command=f"/{SlashCommand.NEXT_PREPARE_DRAFT.value}",
            project=_derive_project_root(cwd, slug),
            subfolder=f"{WORKTREE_DIR}/{slug}",
            message=note,
            next_step=f"telec todo prepare {slug}",
        )
        _emit_prepare_event("domain.software-development.prepare.regrounded", {"slug": slug})
        return False, instruction

    guidance = await compose_agent_guidance(db)
    instruction = format_tool_call(
        ToolCallRequest(
            command=SlashCommand.NEXT_PREPARE_DRAFT,
            args=slug,
            project=_derive_project_root(cwd, slug),
            guidance=guidance,
            subfolder=f"{WORKTREE_DIR}/{slug}",
            note=note,
            next_call=f"telec todo prepare {slug}",
            post_block=_worker_idle_post_block(slug),
        )
    )
    _emit_prepare_event("domain.software-development.prepare.regrounded", {"slug": slug})
    return False, instruction


async def prepare_step_re_grounding(
    db: Db,
    todos_db: TodosDb,
    slug: str,
    cwd: str,
    state: dict[str, StateValue],
) -> tuple[bool, str]:
    """RE_GROUNDING: refresh the plan against current truth before re-review."""
    writer = StateWriter(state)
    if writer.state.artifacts.implementation_plan.produced_at:
        apply_authoritative_signal(writer.state, "plan_ready")
        await _commit_writer(writer, todos_db, slug, state)
        return True, ""

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
                    f"Re-ground {slug} and rewrite the implementation plan via "
                    f"`telec todo artifacts read {slug} implementation-plan` + "
                    f"`telec todo artifacts write {slug} implementation-plan <content>`, "
                    f"then stamp via `telec todo stamp {slug} --plan-ready`."
                ),
                slug,
                DispatchReason.UPSTREAM_CHANGED,
            ),
            next_call=f"telec todo prepare {slug}",
            post_block=_worker_idle_post_block(slug),
        )
    )
