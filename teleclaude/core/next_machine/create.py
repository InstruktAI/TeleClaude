"""Creative stage — lifecycle state machine for creative work.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.constants import SlashCommand
from teleclaude.core.db import Db
from teleclaude.core.next_machine._types import CreativePhase, ItemPhase, StateValue
from teleclaude.core.next_machine.git_ops import compose_agent_guidance
from teleclaude.core.next_machine.output_formatting import format_tool_call
from teleclaude.core.next_machine.roadmap import load_roadmap_slugs
from teleclaude.core.next_machine.slug_resolution import get_item_phase
from teleclaude.core.next_machine.state_io import read_phase_state, write_phase_state

logger = get_logger(__name__)

_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".svg"})


def _derive_creative_phase(todo_dir: Path, creative: dict[str, StateValue]) -> CreativePhase:
    """Derive the current creative phase from filesystem artifacts and state.yaml."""
    design_spec = todo_dir / "design-spec.md"
    art_dir = todo_dir / "art"
    html_dir = todo_dir / "html"

    # Phase 1: Design spec
    if not design_spec.exists():
        return CreativePhase.DESIGN_DISCOVERY_REQUIRED

    ds_state = creative.get("design_spec")
    ds_dict = ds_state if isinstance(ds_state, dict) else {}
    if not ds_dict.get("confirmed"):
        return CreativePhase.DESIGN_SPEC_PENDING_CONFIRMATION

    # Phase 2: Art generation
    art_images = [f for f in (art_dir.iterdir() if art_dir.is_dir() else []) if f.suffix.lower() in _IMAGE_EXTENSIONS]
    if not art_images:
        return CreativePhase.ART_GENERATION_REQUIRED

    art_state = creative.get("art")
    art_dict = art_state if isinstance(art_state, dict) else {}
    if not art_dict.get("approved"):
        return CreativePhase.ART_PENDING_APPROVAL

    # Phase 3: Visual drafting
    html_files = [f for f in (html_dir.iterdir() if html_dir.is_dir() else []) if f.suffix.lower() == ".html"]
    if not html_files:
        return CreativePhase.VISUAL_DRAFTS_REQUIRED

    vis_state = creative.get("visuals")
    vis_dict = vis_state if isinstance(vis_state, dict) else {}
    if not vis_dict.get("approved"):
        return CreativePhase.VISUALS_PENDING_APPROVAL

    return CreativePhase.CREATIVE_COMPLETE


def _find_next_creative_slug(cwd: str) -> str | None:
    """Find the next active slug that needs creative work.

    Looks for items with a creative section in state.yaml that is not yet complete,
    or items where input.md exists but creative artifacts are missing.
    """
    for slug in load_roadmap_slugs(cwd):
        phase = get_item_phase(cwd, slug)
        if phase == ItemPhase.DONE.value:
            continue

        todo_dir = Path(cwd) / "todos" / slug
        if not (todo_dir / "input.md").exists():
            continue

        state = read_phase_state(cwd, slug)
        creative = state.get("creative")
        if not isinstance(creative, dict):
            creative = {}

        # If creative section exists and has phase tracking, check if complete
        creative_phase_val = creative.get("phase", "")
        if creative_phase_val == CreativePhase.CREATIVE_COMPLETE.value:
            continue

        # If any creative signal exists (creative section in state, or design-spec.md),
        # this slug needs creative work
        if creative or (todo_dir / "design-spec.md").exists():
            return slug

    return None


async def _creative_instruction(slug: str, cwd: str, phase: CreativePhase, guidance: str) -> str:
    """Generate plain-text instruction for the orchestrator based on creative phase."""
    match phase:
        case CreativePhase.DESIGN_DISCOVERY_REQUIRED:
            return (
                f"DESIGN_DISCOVERY_REQUIRED: {slug}\n\n"
                f"design-spec.md does not exist. Run design discovery with the human.\n"
                f"This is an interactive session — the human participates directly.\n"
                f"Read todos/{slug}/input.md for context. Present reference sites,\n"
                f"collect images the human provides (save to todos/{slug}/input/),\n"
                f"and facilitate the dialogue that produces todos/{slug}/design-spec.md.\n\n"
                f"After design-spec.md is written, call `telec todo create {slug}` again."
            )

        case CreativePhase.DESIGN_SPEC_PENDING_CONFIRMATION:
            return (
                f"DESIGN_SPEC_PENDING_CONFIRMATION: {slug}\n\n"
                f"design-spec.md exists but the human has not confirmed it.\n"
                f"Present the design spec to the human. Highlight any [proposed] values.\n"
                f"When confirmed: update state.yaml creative.design_spec.confirmed to true,\n"
                f"set creative.design_spec.confirmed_at and confirmed_by.\n"
                f"When the human requests revisions: update design-spec.md accordingly.\n\n"
                f"After confirmation, call `telec todo create {slug}` again."
            )

        case CreativePhase.ART_GENERATION_REQUIRED:
            return format_tool_call(
                command=SlashCommand.NEXT_CREATE_ART,
                args=slug,
                project=cwd,
                guidance=guidance,
                subfolder="",
                note="Design spec confirmed. Dispatch artist to generate mood board images.",
                next_call=f"telec todo create {slug}",
            )

        case CreativePhase.ART_PENDING_APPROVAL:
            art_dir = Path(cwd) / "todos" / slug / "art"
            art_files = (
                sorted(f.name for f in art_dir.iterdir() if f.suffix.lower() in _IMAGE_EXTENSIONS)
                if art_dir.is_dir()
                else []
            )
            file_list = "\n".join(f"  todos/{slug}/art/{f}" for f in art_files)
            return (
                f"ART_PENDING_APPROVAL: {slug}\n\n"
                f"Art images exist but are not approved. Present to the human:\n"
                f"{file_list}\n\n"
                f"When approved: update state.yaml creative.art.approved to true,\n"
                f"set creative.art.approved_at and approved_by.\n"
                f"When the human requests changes: relay feedback to the artist session.\n\n"
                f"After approval, call `telec todo create {slug}` again."
            )

        case CreativePhase.ART_ITERATION_REQUIRED:
            return format_tool_call(
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

        case CreativePhase.VISUAL_DRAFTS_REQUIRED:
            return format_tool_call(
                command=SlashCommand.NEXT_CREATE_HTML,
                args=slug,
                project=cwd,
                guidance=guidance,
                subfolder="",
                note="Art approved. Dispatch frontender to produce HTML+CSS visual artifacts.",
                next_call=f"telec todo create {slug}",
            )

        case CreativePhase.VISUALS_PENDING_APPROVAL:
            html_dir = Path(cwd) / "todos" / slug / "html"
            html_files = (
                sorted(f.name for f in html_dir.iterdir() if f.suffix.lower() == ".html") if html_dir.is_dir() else []
            )
            file_list = "\n".join(f"  todos/{slug}/html/{f}" for f in html_files)
            return (
                f"VISUALS_PENDING_APPROVAL: {slug}\n\n"
                f"Visual artifacts exist but are not approved. Tell the human to review:\n"
                f"{file_list}\n\n"
                f"When approved: update state.yaml creative.visuals.approved to true,\n"
                f"set creative.visuals.approved_at and approved_by.\n"
                f"When the human requests changes: relay feedback for revision.\n\n"
                f"After approval, call `telec todo create {slug}` again."
            )

        case CreativePhase.VISUAL_ITERATION_REQUIRED:
            return format_tool_call(
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

        case CreativePhase.CREATIVE_COMPLETE:
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

        case CreativePhase.BLOCKED:
            return (
                f"BLOCKED: {slug}\n\n"
                f"The creative machine encountered a condition it cannot resolve.\n"
                f"Check todos/{slug}/state.yaml for details. End worker sessions\n"
                f"and report the blocker to the human."
            )

        case _:
            return f"UNKNOWN_PHASE: {slug} — phase={phase.value}. Inspect state.yaml."


async def next_create(db: Db, slug: str | None, cwd: str) -> str:
    """Creative lifecycle state machine.

    Derives creative phase from filesystem artifacts and state.yaml,
    returns plain text instructions for the orchestrator to execute.

    Args:
        db: Database instance
        slug: Optional explicit slug (resolved from roadmap if not provided)
        cwd: Current working directory (project root)

    Returns:
        Plain text instructions for the orchestrator to execute
    """
    resolved_slug = slug
    if not resolved_slug:
        resolved_slug = await asyncio.to_thread(_find_next_creative_slug, cwd)

    if not resolved_slug:
        return "NO_CREATIVE_ITEMS: No work items require creative work. Nothing to do."

    # Verify input.md exists
    todo_dir = Path(cwd) / "todos" / resolved_slug
    if not (todo_dir / "input.md").exists():
        return (
            f"BLOCKED: {resolved_slug} has no input.md. "
            f"Write todos/{resolved_slug}/input.md before starting creative work."
        )

    # Read state
    state = await asyncio.to_thread(read_phase_state, cwd, resolved_slug)
    creative = state.get("creative")
    if not isinstance(creative, dict):
        creative = {}

    # Derive phase from filesystem + state
    phase = await asyncio.to_thread(_derive_creative_phase, todo_dir, creative)

    logger.info("NEXT_CREATE_PHASE slug=%s phase=%s", resolved_slug, phase.value)

    # Update creative phase in state
    if "creative" not in state or not isinstance(state.get("creative"), dict):
        state["creative"] = {}
    creative_state = state["creative"]
    if isinstance(creative_state, dict):
        creative_state["phase"] = phase.value
        await asyncio.to_thread(write_phase_state, cwd, resolved_slug, state)

    # Generate instruction
    guidance = await compose_agent_guidance(db)
    return await _creative_instruction(resolved_slug, cwd, phase, guidance)


__all__ = ["next_create"]
