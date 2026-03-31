"""Creative stage — lifecycle state machine for creative work.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.constants import SlashCommand
from teleclaude.core.db import Db
from teleclaude.core.next_machine._types import CreativePhase, StateValue
from teleclaude.core.next_machine.git_ops import compose_agent_guidance
from teleclaude.core.next_machine.output_formatting import ToolCallRequest, format_tool_call

if TYPE_CHECKING:
    from teleclaude.core.todos_db import TodosDb

logger = get_logger(__name__)

_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".svg"})


def _human_review_file_list(cwd: str, slug: str, folder: str, suffixes: set[str] | frozenset[str]) -> str:
    """Return a newline-separated list of reviewable files."""
    target_dir = Path(cwd) / "todos" / slug / folder
    files = sorted(f.name for f in target_dir.iterdir() if f.suffix.lower() in suffixes) if target_dir.is_dir() else []
    return "\n".join(f"  todos/{slug}/{folder}/{file_name}" for file_name in files)


def _design_discovery_required(slug: str) -> str:
    return (
        f"DESIGN_DISCOVERY_REQUIRED: {slug}\n\n"
        f"design-spec.md does not exist. Run design discovery with the human.\n"
        f"This is an interactive session — the human participates directly.\n"
        f"Read todos/{slug}/input.md for context. Present reference sites,\n"
        f"collect images the human provides (save to todos/{slug}/input/),\n"
        f"and facilitate the dialogue that produces todos/{slug}/design-spec.md.\n\n"
        f"After design-spec.md is written, call `telec todo create {slug}` again."
    )


def _design_spec_pending_confirmation(slug: str) -> str:
    return (
        f"DESIGN_SPEC_PENDING_CONFIRMATION: {slug}\n\n"
        f"design-spec.md exists but the human has not confirmed it.\n"
        f"Present the design spec to the human. Highlight any [proposed] values.\n"
        f"When confirmed: update state.yaml creative.design_spec.confirmed to true,\n"
        f"set creative.design_spec.confirmed_at and confirmed_by.\n"
        f"When the human requests revisions: update design-spec.md accordingly.\n\n"
        f"After confirmation, call `telec todo create {slug}` again."
    )


def _art_pending_approval(slug: str, cwd: str) -> str:
    file_list = _human_review_file_list(cwd, slug, "art", _IMAGE_EXTENSIONS)
    return (
        f"ART_PENDING_APPROVAL: {slug}\n\n"
        f"Art images exist but are not approved. Present to the human:\n"
        f"{file_list}\n\n"
        f"When approved: update state.yaml creative.art.approved to true,\n"
        f"set creative.art.approved_at and approved_by.\n"
        f"When the human requests changes: relay feedback to the artist session.\n\n"
        f"After approval, call `telec todo create {slug}` again."
    )


def _visuals_pending_approval(slug: str, cwd: str) -> str:
    file_list = _human_review_file_list(cwd, slug, "html", {".html"})
    return (
        f"VISUALS_PENDING_APPROVAL: {slug}\n\n"
        f"Visual artifacts exist but are not approved. Tell the human to review:\n"
        f"{file_list}\n\n"
        f"When approved: update state.yaml creative.visuals.approved to true,\n"
        f"set creative.visuals.approved_at and approved_by.\n"
        f"When the human requests changes: relay feedback for revision.\n\n"
        f"After approval, call `telec todo create {slug}` again."
    )


def _creative_complete(slug: str) -> str:
    return (
        f"CREATIVE_COMPLETE: {slug}\n\n"
        f"All creative artifacts are confirmed and approved:\n"
        f"  - design-spec.md: confirmed\n"
        f"  - art/: approved\n"
        f"  - html/: approved\n\n"
        f"The todo is ready for the prepare phase.\n"
        f"End all creative worker sessions and proceed to:\n"
        f"  telec todo prepare {slug}"
    )


def _creative_blocked(slug: str) -> str:
    return (
        f"BLOCKED: {slug}\n\n"
        f"The creative machine encountered a condition it cannot resolve.\n"
        f"Check todos/{slug}/state.yaml for details. End worker sessions\n"
        f"and report the blocker to the human."
    )


def _derive_creative_phase(todo_dir: Path, creative: dict[str, StateValue]) -> CreativePhase:
    """Derive the current creative phase from filesystem artifacts and state.yaml."""
    design_spec = todo_dir / "design-spec.md"
    art_dir = todo_dir / "art"
    html_dir = todo_dir / "html"

    phase = CreativePhase.DESIGN_DISCOVERY_REQUIRED
    if design_spec.exists():
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


async def _find_next_creative_slug(todos_db: TodosDb) -> str | None:
    """Find the next active slug that needs creative work from DB."""
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
        if not isinstance(creative, dict):
            creative = {}

        creative_phase_val = creative.get("phase", "")
        if creative_phase_val == CreativePhase.CREATIVE_COMPLETE.value:
            continue

        has_design_spec = await todos_db.artifact_exists(slug, "design-spec")
        if creative or has_design_spec:
            return slug

    return None


async def _creative_instruction(slug: str, cwd: str, phase: CreativePhase, guidance: str) -> str:
    """Generate plain-text instruction for the orchestrator based on creative phase."""
    builders = {
        CreativePhase.DESIGN_DISCOVERY_REQUIRED: lambda: _design_discovery_required(slug),
        CreativePhase.DESIGN_SPEC_PENDING_CONFIRMATION: lambda: _design_spec_pending_confirmation(slug),
        CreativePhase.ART_GENERATION_REQUIRED: lambda: format_tool_call(
            ToolCallRequest(
                command=SlashCommand.NEXT_CREATE_ART,
                args=slug,
                project=cwd,
                guidance=guidance,
                subfolder="",
                note="Design spec confirmed. Dispatch artist to generate mood board images.",
                next_call=f"telec todo create {slug}",
            )
        ),
        CreativePhase.ART_PENDING_APPROVAL: lambda: _art_pending_approval(slug, cwd),
        CreativePhase.ART_ITERATION_REQUIRED: lambda: format_tool_call(
            ToolCallRequest(
                command=SlashCommand.NEXT_CREATE_ART,
                args=slug,
                project=cwd,
                guidance=guidance,
                subfolder="",
                note="Human requested art changes. Dispatch artist with feedback for revision.",
                next_call=f"telec todo create {slug}",
                additional_context="ITERATION: The human reviewed the art and wants changes. "
                "Read the feedback and revise the images in todos/{slug}/art/.",
            )
        ),
        CreativePhase.VISUAL_DRAFTS_REQUIRED: lambda: format_tool_call(
            ToolCallRequest(
                command=SlashCommand.NEXT_CREATE_HTML,
                args=slug,
                project=cwd,
                guidance=guidance,
                subfolder="",
                note="Art approved. Dispatch frontender to produce HTML+CSS visual artifacts.",
                next_call=f"telec todo create {slug}",
            )
        ),
        CreativePhase.VISUALS_PENDING_APPROVAL: lambda: _visuals_pending_approval(slug, cwd),
        CreativePhase.VISUAL_ITERATION_REQUIRED: lambda: format_tool_call(
            ToolCallRequest(
                command=SlashCommand.NEXT_CREATE_HTML,
                args=slug,
                project=cwd,
                guidance=guidance,
                subfolder="",
                note="Human requested visual changes. Dispatch frontender with feedback for revision.",
                next_call=f"telec todo create {slug}",
                additional_context="ITERATION: The human reviewed the visuals and wants changes. "
                "Read the feedback and revise the HTML+CSS in todos/{slug}/html/.",
            )
        ),
        CreativePhase.CREATIVE_COMPLETE: lambda: _creative_complete(slug),
        CreativePhase.BLOCKED: lambda: _creative_blocked(slug),
    }
    builder: Callable[[], str] = builders.get(
        phase, lambda: f"UNKNOWN_PHASE: {slug} — phase={phase.value}. Inspect state.yaml."
    )
    return builder()


async def next_create(db: Db, slug: str | None, cwd: str) -> str:
    """Creative lifecycle state machine.

    Derives creative phase from DB state and artifacts,
    returns plain text instructions for the orchestrator to execute.
    """
    from teleclaude.core.todos_db import get_todos_db  # pylint: disable=import-outside-toplevel

    todos_db = await get_todos_db(cwd)

    resolved_slug = slug or await _find_next_creative_slug(todos_db)
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
    todo_dir = Path(cwd) / "todos" / resolved_slug
    phase = await asyncio.to_thread(_derive_creative_phase, todo_dir, creative_state)

    logger.info("NEXT_CREATE_PHASE slug=%s phase=%s", resolved_slug, phase.value)
    if "creative" not in state or not isinstance(state.get("creative"), dict):
        state["creative"] = {}
    if isinstance(state["creative"], dict):
        state["creative"]["phase"] = phase.value
        await todos_db.write_state(resolved_slug, state)

    guidance = await compose_agent_guidance(db)
    return await _creative_instruction(resolved_slug, cwd, phase, guidance)


__all__ = ["next_create"]
