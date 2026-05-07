"""Creative stage — lifecycle state machine for creative work.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import SlashCommand
from teleclaude.core.db import Db
from teleclaude.core.next_machine._types import CreativePhase, StateValue
from teleclaude.core.next_machine.git_ops import compose_agent_guidance
from teleclaude.core.next_machine.output_formatting import ToolCallRequest, format_tool_call
from teleclaude.core.next_machine.runtime.sessions import find_all_live_sessions_for_slug, find_live_session_for_slug

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb
from teleclaude.core.todos_db import get_todos_db

logger = get_logger(__name__)

_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".svg"})


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
    end_lines = "\n".join(f"telec sessions end {sid}" for sid in live_sessions)
    cleanup = f"{end_lines}\ntelec sessions end self\n\n" if live_sessions else "telec sessions end self\n\n"
    return (
        f"CREATIVE_COMPLETE: {slug}\n\n"
        f"All creative artifacts are confirmed and approved:\n"
        f"  - design-spec.md: confirmed\n"
        f"  - art/: approved\n"
        f"  - html/: approved\n\n"
        f"Execute in order:\n\n"
        f"{cleanup}"
        f"The todo is ready for the prepare phase:\n"
        f"  telec todo prepare {slug}"
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


def _format_creative_iteration_script(
    slug: str,
    worker_session_id: str,
    phase_label: str,
    workspace_subdir: str,
) -> str:
    """Script for ART/VISUAL iteration: send feedback to the live worker."""
    message = (
        f"Iteration round for {phase_label}: the human reviewed your output and requested changes. "
        f"Read the feedback (look for the most recent human message and any updated review context), "
        f"revise the artifacts in {workspace_subdir}, and report when ready for re-review."
    )
    escaped = message.replace('"', '\\"')
    return (
        f"{phase_label.upper()} ITERATION REQUIRED: {slug}\n\n"
        f"Execute in order:\n\n"
        f'telec sessions send {worker_session_id} "{escaped}"\n\n'
        f"Cancel the old heartbeat timer via KillShell(shell_id=<task_id>).\n"
        f'Start a new non-blocking heartbeat timer via Bash(command="sleep 300", run_in_background=true) '
        f"and save the new task_id.\n"
        f"Wait for the worker to idle.\n"
        f"When the worker idles, call telec todo design {slug}."
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


async def _find_next_creative_slug(todos_db: TodosDb, cwd: str) -> str | None:
    """Find the next active slug that needs creative work from DB.

    Phase is never cached — each candidate is re-derived from workspace
    artifacts and DB flags so that CREATIVE_COMPLETE slugs are skipped
    without trusting stale state.
    """
    entries = await todos_db.list_roadmap()
    delivered = await todos_db.delivered_slugs()

    for entry in entries:
        slug = entry["slug"]
        if slug in delivered:
            continue

        has_input = await todos_db.artifact_exists(slug, "input")
        if not has_input:
            continue

        state = await todos_db.read_state(slug)
        if state is None:
            continue

        creative = state.get("creative")
        creative_state = creative if isinstance(creative, dict) else {}

        has_design_spec = await todos_db.artifact_exists(slug, "design-spec")
        workspace_dir = Path(cwd) / "workspace" / slug
        phase = await asyncio.to_thread(_derive_creative_phase, workspace_dir, has_design_spec, creative_state)
        if phase == CreativePhase.CREATIVE_COMPLETE:
            continue

        if creative_state or has_design_spec:
            return slug

    return None


async def _creative_instruction(db: Db, slug: str, cwd: str, phase: CreativePhase, guidance: str) -> str:
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
                command=SlashCommand.NEXT_CREATE_ART,
                args=slug,
                project=cwd,
                guidance=guidance,
                subfolder="",
                note="Design spec confirmed. Dispatch artist to generate mood board images.",
                next_call=f"telec todo design {slug}",
                post_block=post_block,
            )
        )
    if phase == CreativePhase.ART_PENDING_APPROVAL:
        return _art_pending_approval(slug, cwd)
    if phase == CreativePhase.ART_ITERATION_REQUIRED:
        artist_id = await find_live_session_for_slug(db, slug, "/next-create-art", subdir_override=creative_subdir)
        if artist_id is not None:
            return _format_creative_iteration_script(slug, artist_id, "art", f"workspace/{slug}/art/")
        # Fallback: dispatch fresh artist when no live session
        return format_tool_call(
            ToolCallRequest(
                command=SlashCommand.NEXT_CREATE_ART,
                args=slug,
                project=cwd,
                guidance=guidance,
                subfolder="",
                note="Human requested art changes. Dispatch artist with feedback for revision.",
                next_call=f"telec todo design {slug}",
                additional_context=(
                    "ITERATION: The human reviewed the art and wants changes. "
                    f"Read the feedback and revise the images in workspace/{slug}/art/."
                ),
                post_block=post_block,
            )
        )
    if phase == CreativePhase.VISUAL_DRAFTS_REQUIRED:
        return format_tool_call(
            ToolCallRequest(
                command=SlashCommand.NEXT_CREATE_HTML,
                args=slug,
                project=cwd,
                guidance=guidance,
                subfolder="",
                note="Art approved. Dispatch frontender to produce HTML+CSS visual artifacts.",
                next_call=f"telec todo design {slug}",
                post_block=post_block,
            )
        )
    if phase == CreativePhase.VISUALS_PENDING_APPROVAL:
        return _visuals_pending_approval(slug, cwd)
    if phase == CreativePhase.VISUAL_ITERATION_REQUIRED:
        frontender_id = await find_live_session_for_slug(db, slug, "/next-create-html", subdir_override=creative_subdir)
        if frontender_id is not None:
            return _format_creative_iteration_script(slug, frontender_id, "visual", f"workspace/{slug}/html/")
        return format_tool_call(
            ToolCallRequest(
                command=SlashCommand.NEXT_CREATE_HTML,
                args=slug,
                project=cwd,
                guidance=guidance,
                subfolder="",
                note="Human requested visual changes. Dispatch frontender with feedback for revision.",
                next_call=f"telec todo design {slug}",
                additional_context=(
                    "ITERATION: The human reviewed the visuals and wants changes. "
                    f"Read the feedback and revise the HTML+CSS in workspace/{slug}/html/."
                ),
                post_block=post_block,
            )
        )
    if phase == CreativePhase.CREATIVE_COMPLETE:
        live_sessions = await find_all_live_sessions_for_slug(db, slug, subdir_override=creative_subdir)
        return _creative_complete(slug, live_sessions)
    if phase == CreativePhase.BLOCKED:
        live_sessions = await find_all_live_sessions_for_slug(db, slug, subdir_override=creative_subdir)
        return _creative_blocked(slug, live_sessions)
    return f"UNKNOWN_PHASE: {slug} — phase={phase.value}. Inspect state.yaml."


async def next_create(db: Db, slug: str | None, cwd: str) -> str:
    """Creative lifecycle state machine.

    Derives creative phase from DB state and artifacts,
    returns plain text instructions for the orchestrator to execute.
    """
    todos_db = await get_todos_db(cwd)

    resolved_slug = slug or await _find_next_creative_slug(todos_db, cwd)
    if not resolved_slug:
        return "NO_CREATIVE_ITEMS: No work items require creative work. Nothing to do."

    has_input = await todos_db.artifact_exists(resolved_slug, "input")
    if not has_input:
        return (
            f"BLOCKED: {resolved_slug} has no input artifact. "
            f"Use telec todo artifacts write {resolved_slug} input before starting creative work."
        )

    state = await todos_db.read_state(resolved_slug)
    if state is None:
        state = {}
    creative = state.get("creative")
    creative_state = creative if isinstance(creative, dict) else {}
    workspace_dir = Path(cwd) / "workspace" / resolved_slug
    has_design_spec = await todos_db.artifact_exists(resolved_slug, "design-spec")
    phase = await asyncio.to_thread(_derive_creative_phase, workspace_dir, has_design_spec, creative_state)

    logger.info("NEXT_CREATE_PHASE slug=%s phase=%s", resolved_slug, phase.value)

    guidance = await compose_agent_guidance(db)
    return await _creative_instruction(db, resolved_slug, cwd, phase, guidance)


__all__ = ["next_create"]
