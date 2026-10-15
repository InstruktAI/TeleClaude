"""Creative stage — lifecycle state machine for creative work.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import ARTIFACT_DESIGN_SPEC, ARTIFACT_INPUT
from teleclaude.core.db import Db
from teleclaude.core.next_machine._types import CreativePhase, StateValue
from teleclaude.core.next_machine.output_formatting import (
    ToolCallRequest,
    dispatch_or_reuse,
    format_terminal_claim_handoff,
    format_tool_call,
)
from teleclaude.core.next_machine.runtime.sessions import find_all_live_sessions_for_slug, find_live_session_for_slug
from teleclaude.core.workflow_machine.creative import CreativeCapability, open_episode
from teleclaude.core.workflow_machine.creative_commit import Handoff, hand_off_to_creative, open_creative_episode
from teleclaude.types.claim_change import workflow_record_of
from teleclaude.types.workflow_record import EffectKind

if TYPE_CHECKING:
    from teleclaude.core.workflow_store.store import WorkflowStore

from teleclaude.core.next_machine.lanes import LifecycleProcedure
from teleclaude.core.workflow_store.store import get_workflow_store

logger = get_logger(__name__)

_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".svg"})


_ENDED_PHASES = frozenset({CreativePhase.CREATIVE_COMPLETE, CreativePhase.BLOCKED})


def _handoff_for(phase: CreativePhase, slug: str, cwd: str, instruction: str) -> Handoff:
    """The dispatch of a phase: the creative orchestrator the lane already has, or the instruction at its end.

    The creative lane is driven by the creative orchestrator, which calls the machine in a loop. A holder's handoff
    starts it; when the design is already complete or blocked there is nothing to drive, and the instruction is the
    dispatch.
    """
    if phase in _ENDED_PHASES:
        return Handoff(instruction=instruction, creative_phase=phase.value)
    return Handoff(
        instruction=instruction,
        creative_phase=phase.value,
        worker_command=LifecycleProcedure.CREATE.value,
        worker_args=slug,
        worker_project=cwd,
    )


def _committed_dispatch(state: Mapping[str, StateValue], caller_session_id: str, phase: CreativePhase) -> str | None:
    """The instruction already committed for this caller's handoff when the call repeats it at the same creative phase.

    A repeat of the call that made the handoff, even after the release, returns the committed outcome. A call made at
    a later creative phase is the next call of the lane and gets its own instruction.
    """
    record = workflow_record_of(state)
    owed = {EffectKind.SWEEP_HELPERS, EffectKind.CREATIVE_DISPATCH, EffectKind.RELEASE_CLAIM}
    finished = state.get("active_runner") != caller_session_id and not any(
        effect.kind in owed for effect in record.pending_effects
    )
    if (
        finished
        and caller_session_id
        and caller_session_id in record.dispatch_recipients
        and record.dispatched
        and record.dispatched_phase == phase.value
    ):
        return list(record.dispatched.values())[-1]
    return None


_CLAIM_CLOSING = (
    "CLAIM_CLOSING: {slug}\n\n"
    "Your claim is closing and the sessions you started are still ending. No instruction is given until they have;\n"
    "call `telec todo design {slug}` again."
)


def _human_review_file_list(cwd: str, slug: str, folder: str, suffixes: set[str] | frozenset[str]) -> str:
    """Return a newline-separated list of reviewable files."""
    target_dir = Path(cwd) / "workspace" / slug / folder
    files = sorted(f.name for f in target_dir.iterdir() if f.suffix.lower() in suffixes) if target_dir.is_dir() else []
    return "\n".join(f"  workspace/{slug}/{folder}/{file_name}" for file_name in files)


def _design_discovery_required(slug: str) -> str:
    return (
        f"DESIGN_DISCOVERY_REQUIRED: {slug}\n\n"
        f"design-spec does not exist. Run design discovery with the human.\n"
        f"This is an interactive session — the human participates directly.\n"
        f"Read input via `telec todo artifacts read {slug} input` for context. Present reference sites,\n"
        f"collect images the human provides (save to workspace/{slug}/input/),\n"
        f"and facilitate the dialogue that produces the design-spec artifact.\n\n"
        f"After design-spec is written, call `telec todo design {slug}` again."
    )


def _design_spec_pending_confirmation(slug: str) -> str:
    return (
        f"DESIGN_SPEC_PENDING_CONFIRMATION: {slug}\n\n"
        f"design-spec.md exists but the human has not confirmed it.\n"
        f"Present the design spec to the human. Highlight any [proposed] values.\n"
        f"When confirmed: run `telec todo stamp {slug} --design-spec-confirmed`.\n"
        f"When the human requests revisions: update design-spec.md accordingly.\n\n"
        f"After confirmation, call `telec todo design {slug}` again."
    )


def _art_pending_approval(slug: str, cwd: str) -> str:
    file_list = _human_review_file_list(cwd, slug, "art", _IMAGE_EXTENSIONS)
    return (
        f"ART_PENDING_APPROVAL: {slug}\n\n"
        f"Art images exist but are not approved. Present to the human:\n"
        f"{file_list}\n\n"
        f"When approved: run `telec todo stamp {slug} --art-approved`.\n"
        f"When the human requests changes: relay feedback to the artist session.\n\n"
        f"After approval, call `telec todo design {slug}` again."
    )


def _visuals_pending_approval(slug: str, cwd: str) -> str:
    file_list = _human_review_file_list(cwd, slug, "html", {".html"})
    return (
        f"VISUALS_PENDING_APPROVAL: {slug}\n\n"
        f"Visual artifacts exist but are not approved. Tell the human to review:\n"
        f"{file_list}\n\n"
        f"When approved: run `telec todo stamp {slug} --visuals-approved`.\n"
        f"When the human requests changes: relay feedback for revision.\n\n"
        f"After approval, call `telec todo design {slug}` again."
    )


def _creative_complete(slug: str, live_sessions: list[str]) -> str:
    end_step = "telec sessions end\n\n" if live_sessions else ""
    return (
        f"CREATIVE_COMPLETE: {slug}\n\n"
        f"All creative artifacts are confirmed and approved:\n"
        f"  - design-spec.md: confirmed\n"
        f"  - art/: approved\n"
        f"  - html/: approved\n\n"
        f"The todo is ready for the prepare phase (`telec todo prepare {slug}`), for whoever "
        f"claims it next.\n\n"
        f"Execute in order:\n\n"
        f"{end_step}"
        f"{format_terminal_claim_handoff(slug)}"
    )


def _creative_blocked(slug: str, live_sessions: list[str]) -> str:
    sessions_block = "\n".join(f"  - {sid}" for sid in live_sessions) if live_sessions else "  (no live sessions)"
    return (
        f"BLOCKED: {slug}\n\n"
        f"The creative machine encountered a condition it cannot resolve.\n"
        f"Check `telec todo show {slug}` for details.\n\n"
        f"Live sessions kept alive for human inspection:\n"
        f"{sessions_block}"
    )


def _derive_creative_phase(
    workspace_dir: Path, has_design_spec: bool, creative: dict[str, StateValue]
) -> CreativePhase:
    """Derive the current creative phase from workspace binary artifacts, DB flag, and state."""
    art_dir = workspace_dir / "art"
    html_dir = workspace_dir / "html"

    phase = CreativePhase.DESIGN_DISCOVERY_REQUIRED
    if has_design_spec:
        ds_state = creative.get("design_spec")
        ds_dict = ds_state if isinstance(ds_state, dict) else {}
        phase = CreativePhase.DESIGN_SPEC_PENDING_CONFIRMATION
        if ds_dict.get("confirmed"):
            art_images = [
                f for f in (art_dir.iterdir() if art_dir.is_dir() else []) if f.suffix.lower() in _IMAGE_EXTENSIONS
            ]
            phase = CreativePhase.ART_GENERATION_REQUIRED
            if art_images:
                art_state = creative.get("art")
                art_dict = art_state if isinstance(art_state, dict) else {}
                phase = CreativePhase.ART_PENDING_APPROVAL
                if art_dict.get("approved"):
                    html_files = [
                        f for f in (html_dir.iterdir() if html_dir.is_dir() else []) if f.suffix.lower() == ".html"
                    ]
                    phase = CreativePhase.VISUAL_DRAFTS_REQUIRED
                    if html_files:
                        vis_state = creative.get("visuals")
                        vis_dict = vis_state if isinstance(vis_state, dict) else {}
                        phase = (
                            CreativePhase.CREATIVE_COMPLETE
                            if vis_dict.get("approved")
                            else CreativePhase.VISUALS_PENDING_APPROVAL
                        )
    return phase


def _creative_state_of(state: Mapping[str, StateValue]) -> dict[str, StateValue]:
    creative = state.get("creative")
    return creative if isinstance(creative, dict) else {}


def _lane_incomplete(cwd: str, slug: str, creative_state: dict[str, StateValue], has_design_spec: bool) -> bool:
    """Whether the derivation reads the design as not complete, for a todo that has an input artifact."""
    if not creative_state and not has_design_spec:
        return False
    workspace_dir = Path(cwd) / "workspace" / slug
    return _derive_creative_phase(workspace_dir, has_design_spec, creative_state) != CreativePhase.CREATIVE_COMPLETE


def creative_incomplete_observed(
    cwd: str, slug: str, state: Mapping[str, StateValue], *, has_input: bool, has_design_spec: bool
) -> bool:
    """The creative answer derived from artifact presence the caller observed once, for a caller that fences on it."""
    if not has_input:
        return False
    return _lane_incomplete(cwd, slug, _creative_state_of(state), has_design_spec)


async def creative_incomplete(todos_db: WorkflowStore, cwd: str, slug: str, state: Mapping[str, StateValue]) -> bool:
    """Whether the todo is on the creative lane with its design not complete.

    The phase is never cached: it is re-derived from the workspace artifacts and the stored flags.
    """
    if not await todos_db.artifact_exists(slug, ARTIFACT_INPUT):
        return False
    has_design_spec = await todos_db.artifact_exists(slug, ARTIFACT_DESIGN_SPEC)
    return await asyncio.to_thread(_lane_incomplete, cwd, slug, _creative_state_of(state), has_design_spec)


def creative_incomplete_sync(todos_db: WorkflowStore, cwd: str, slug: str, state: Mapping[str, StateValue]) -> bool:
    """The same answer for a caller on a worker thread: one derivation, read through the store's synchronous reads."""
    if not todos_db.artifact_exists_sync(slug, ARTIFACT_INPUT):
        return False
    return _lane_incomplete(
        cwd, slug, _creative_state_of(state), todos_db.artifact_exists_sync(slug, ARTIFACT_DESIGN_SPEC)
    )


async def _find_next_creative_slug(todos_db: WorkflowStore, cwd: str) -> str | None:
    """Find the next active slug that needs creative work from DB.

    Phase is never cached - each candidate is re-derived from workspace artifacts and DB flags so that
    CREATIVE_COMPLETE slugs are skipped without trusting stale state.
    """
    entries = await todos_db.list_todo()
    delivered = await todos_db.delivered_slugs()

    for entry in entries:
        slug = entry["slug"]
        if slug in delivered:
            continue
        state = await todos_db.read_state(slug)
        if state is None:
            continue
        if await creative_incomplete(todos_db, cwd, slug, state):
            return slug

    return None


async def _creative_instruction(db: Db, slug: str, cwd: str, phase: CreativePhase) -> str:
    """Generate plain-text instruction for the orchestrator based on creative phase."""
    creative_subdir = f"workspace/{slug}"
    post_block = f"WHEN WORKER IDLES:\nCall telec todo design {slug}. The state machine emits the next action."

    if phase == CreativePhase.DESIGN_DISCOVERY_REQUIRED:
        return _design_discovery_required(slug)
    if phase == CreativePhase.DESIGN_SPEC_PENDING_CONFIRMATION:
        return _design_spec_pending_confirmation(slug)
    if phase == CreativePhase.ART_GENERATION_REQUIRED:
        return format_tool_call(
            ToolCallRequest(
                command=LifecycleProcedure.CREATE_ART,
                args=slug,
                project=cwd,
                subfolder="",
                note="Design spec confirmed. Dispatch artist to generate mood board images.",
                next_call=f"telec todo design {slug}",
                post_block=post_block,
            )
        )
    if phase == CreativePhase.ART_PENDING_APPROVAL:
        return _art_pending_approval(slug, cwd)
    if phase == CreativePhase.ART_ITERATION_REQUIRED:
        artist_id = await find_live_session_for_slug(
            db, slug, LifecycleProcedure.CREATE_ART.value, subdir_override=creative_subdir
        )
        return dispatch_or_reuse(
            artist_id,
            request=ToolCallRequest(
                command=LifecycleProcedure.CREATE_ART,
                args=slug,
                project=cwd,
                subfolder="",
                note="Human requested art changes. Dispatch artist with feedback for revision.",
                next_call=f"telec todo design {slug}",
                additional_context=(
                    "ITERATION: The human reviewed the art and wants changes. "
                    f"Read the feedback and revise the images in workspace/{slug}/art/."
                ),
                post_block=post_block,
            ),
            slug=slug,
            message=(
                "Iteration round for art: the human reviewed your output and requested changes. "
                "Read the feedback (look for the most recent human message and any updated review context), "
                f"revise the artifacts in workspace/{slug}/art/, and report when ready for re-review."
            ),
            advance_call=f"telec todo design {slug}",
        )
    if phase == CreativePhase.VISUAL_DRAFTS_REQUIRED:
        return format_tool_call(
            ToolCallRequest(
                command=LifecycleProcedure.CREATE_HTML,
                args=slug,
                project=cwd,
                subfolder="",
                note="Art approved. Dispatch frontender to produce HTML+CSS visual artifacts.",
                next_call=f"telec todo design {slug}",
                post_block=post_block,
            )
        )
    if phase == CreativePhase.VISUALS_PENDING_APPROVAL:
        return _visuals_pending_approval(slug, cwd)
    if phase == CreativePhase.VISUAL_ITERATION_REQUIRED:
        frontender_id = await find_live_session_for_slug(
            db, slug, LifecycleProcedure.CREATE_HTML.value, subdir_override=creative_subdir
        )
        return dispatch_or_reuse(
            frontender_id,
            request=ToolCallRequest(
                command=LifecycleProcedure.CREATE_HTML,
                args=slug,
                project=cwd,
                subfolder="",
                note="Human requested visual changes. Dispatch frontender with feedback for revision.",
                next_call=f"telec todo design {slug}",
                additional_context=(
                    "ITERATION: The human reviewed the visuals and wants changes. "
                    f"Read the feedback and revise the HTML+CSS in workspace/{slug}/html/."
                ),
                post_block=post_block,
            ),
            slug=slug,
            message=(
                "Iteration round for visual: the human reviewed your output and requested changes. "
                "Read the feedback (look for the most recent human message and any updated review context), "
                f"revise the artifacts in workspace/{slug}/html/, and report when ready for re-review."
            ),
            advance_call=f"telec todo design {slug}",
        )
    if phase == CreativePhase.CREATIVE_COMPLETE:
        live_sessions = await find_all_live_sessions_for_slug(db, slug, subdir_override=creative_subdir)
        return _creative_complete(slug, live_sessions)
    if phase == CreativePhase.BLOCKED:
        live_sessions = await find_all_live_sessions_for_slug(db, slug, subdir_override=creative_subdir)
        return _creative_blocked(slug, live_sessions)
    return f"UNKNOWN_PHASE: {slug} — phase={phase.value}. Inspect state.yaml."


async def next_create(db: Db, slug: str | None, cwd: str, caller_session_id: str = "") -> str:
    """Creative lifecycle state machine.

    Derives creative phase from DB state and artifacts,
    returns plain text instructions for the orchestrator to execute.
    """
    todos_db = await get_workflow_store(cwd)

    resolved_slug = slug or await _find_next_creative_slug(todos_db, cwd)
    if not resolved_slug:
        return "NO_CREATIVE_ITEMS: No work items require creative work. Nothing to do."

    has_input = await todos_db.artifact_exists(resolved_slug, ARTIFACT_INPUT)
    if not has_input:
        return (
            f"BLOCKED: {resolved_slug} has no input artifact. "
            f"Use telec todo artifacts write {resolved_slug} {ARTIFACT_INPUT} before starting creative work."
        )

    state = await todos_db.read_state(resolved_slug)
    if state is None:
        state = {}
    creative = state.get("creative")
    creative_state = creative if isinstance(creative, dict) else {}
    workspace_dir = Path(cwd) / "workspace" / resolved_slug
    has_design_spec = await todos_db.artifact_exists(resolved_slug, ARTIFACT_DESIGN_SPEC)
    phase = await asyncio.to_thread(_derive_creative_phase, workspace_dir, has_design_spec, creative_state)

    logger.info("NEXT_CREATE_PHASE slug=%s phase=%s", resolved_slug, phase.value)
    replayed = _committed_dispatch(state, caller_session_id, phase)
    if replayed is not None:
        return replayed
    if caller_session_id and state.get("active_runner") == caller_session_id:
        instruction = await _creative_instruction(db, resolved_slug, cwd, phase)
        dispatched = await hand_off_to_creative(
            todos_db, resolved_slug, caller_session_id, _handoff_for(phase, resolved_slug, cwd, instruction)
        )
        return dispatched if dispatched is not None else _CLAIM_CLOSING.format(slug=resolved_slug)
    if phase == CreativePhase.CREATIVE_COMPLETE:
        open_episode(resolved_slug, state, capability=CreativeCapability.DESIGN, caller_session_id=caller_session_id)
    else:
        await open_creative_episode(todos_db, resolved_slug, CreativeCapability.DESIGN, caller_session_id)

    return await _creative_instruction(db, resolved_slug, cwd, phase)


__all__ = ["next_create"]
