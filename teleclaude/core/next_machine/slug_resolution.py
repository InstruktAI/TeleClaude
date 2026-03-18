"""Slug resolution — find runnable slugs and manage item phase transitions.

No imports from core.py (circular-import guard).
Note: slug_in_roadmap lives in roadmap.py (used by check_dependencies_satisfied there).
      is_bug_todo lives in state_io.py (avoids circular dep with build_gates).
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from teleclaude.core.next_machine._types import DOR_READY_THRESHOLD, ItemPhase, PhaseName, PhaseStatus
from teleclaude.core.next_machine.build_gates import check_file_has_content
from teleclaude.core.next_machine.roadmap import (
    check_dependencies_satisfied,
    load_roadmap,
    load_roadmap_slugs,
    slug_in_roadmap,
)
from teleclaude.core.next_machine.state_io import read_breakdown_state, read_phase_state, write_phase_state


def _find_next_prepare_slug(cwd: str) -> str | None:
    """Find the next active slug that still needs preparation work.

    Scans roadmap.yaml for slugs, then checks state.yaml phase for each.
    Active slugs have phase pending, ready, or in_progress.
    Returns the first slug that still needs action:
    - requirements.md missing
    - implementation-plan.md missing
    - phase still pending (needs promotion to ready)
    """
    for slug in load_roadmap_slugs(cwd):
        phase = get_item_phase(cwd, slug)

        # Skip done items
        if phase == ItemPhase.DONE.value:
            continue

        has_requirements = check_file_has_content(cwd, f"todos/{slug}/requirements.md")
        has_impl_plan = check_file_has_content(cwd, f"todos/{slug}/implementation-plan.md")
        if not has_requirements or not has_impl_plan:
            return slug

        if phase == ItemPhase.PENDING.value:
            return slug

    return None


def resolve_holder_children(cwd: str, holder_slug: str) -> list[str]:
    """Resolve container/holder child slugs in deterministic order.

    Resolution sources:
    - roadmap group mapping (`group == holder_slug`)
    - holder breakdown state (`state.yaml.breakdown.todos`)

    Roadmap order is authoritative when present. Breakdown-only children are
    appended in their declared order.
    """
    entries = load_roadmap(cwd)
    grouped_children = [entry.slug for entry in entries if entry.group == holder_slug]

    breakdown_state = read_breakdown_state(cwd, holder_slug)
    breakdown_children: list[str] = []
    if breakdown_state:
        raw_children = breakdown_state.get("todos")
        if isinstance(raw_children, list):
            breakdown_children = [child for child in raw_children if child]

    if not grouped_children and not breakdown_children:
        return []

    ordered_children = list(grouped_children)
    seen = set(ordered_children)
    for child in breakdown_children:
        if child not in seen:
            ordered_children.append(child)
            seen.add(child)
    return ordered_children


def resolve_first_runnable_holder_child(
    cwd: str,
    holder_slug: str,
    dependencies: dict[str, list[str]],
) -> tuple[str | None, str]:
    """Resolve first runnable child for a holder slug.

    Returns:
        (child_slug, reason)
        - reason == "ok" when child_slug is selected
        - reason in {"not_holder", "children_not_in_roadmap", "complete",
          "deps_unsatisfied", "item_not_ready"} otherwise
    """
    children = resolve_holder_children(cwd, holder_slug)
    reason = "not_holder"
    if not children:
        return None, reason

    has_children_in_roadmap = False
    has_incomplete_children = False
    has_deps_blocked = False
    has_not_ready = False

    for child in children:
        if not slug_in_roadmap(cwd, child):
            continue

        has_children_in_roadmap = True
        phase = get_item_phase(cwd, child)
        if phase == ItemPhase.DONE.value:
            continue

        has_incomplete_children = True
        is_ready = phase == ItemPhase.IN_PROGRESS.value or is_ready_for_work(cwd, child)
        if not is_ready:
            has_not_ready = True
            continue

        if not check_dependencies_satisfied(cwd, child, dependencies):
            has_deps_blocked = True
            continue

        return child, "ok"

    if has_children_in_roadmap:
        reason = "complete" if not has_incomplete_children else "item_not_ready"
        if has_deps_blocked:
            reason = "deps_unsatisfied"
        elif has_not_ready:
            reason = "item_not_ready"
    else:
        reason = "children_not_in_roadmap"
    return None, reason


def resolve_slug(
    cwd: str,
    slug: str | None,
    ready_only: bool = False,
    dependencies: dict[str, list[str]] | None = None,
) -> tuple[str | None, bool, str]:
    """Resolve slug from argument or roadmap.

    Phase is derived from state.yaml for each slug.

    Args:
        cwd: Current working directory (project root)
        slug: Optional explicit slug
        ready_only: If True, only match items with phase "ready" (for next_work)
        dependencies: Optional dependency graph for dependency gating (R6).
                     If provided with ready_only=True, only returns slugs with satisfied dependencies.

    Returns:
        Tuple of (slug, is_ready_or_in_progress, description).
        If slug provided, returns (slug, True, "").
        If found in roadmap, returns (slug, True if ready/in_progress, False if pending, description).
        If nothing found, returns (None, False, "").
    """
    resolved: tuple[str | None, bool, str] = (slug, True, "") if slug else (None, False, "")
    if not slug:
        entries = load_roadmap(cwd)
        for entry in entries:
            found_slug = entry.slug
            phase = get_item_phase(cwd, found_slug)
            is_ready = phase == ItemPhase.IN_PROGRESS.value or is_ready_for_work(cwd, found_slug)
            should_skip = ready_only and not is_ready
            if not ready_only and phase == ItemPhase.DONE.value:
                should_skip = True
            if (
                ready_only
                and dependencies is not None
                and not check_dependencies_satisfied(cwd, found_slug, dependencies)
            ):
                should_skip = True
            if should_skip:
                continue
            resolved = (found_slug, is_ready, entry.description or "")
            break

    return resolved


async def resolve_slug_async(
    cwd: str,
    slug: str | None,
    ready_only: bool = False,
    dependencies: dict[str, list[str]] | None = None,
) -> tuple[str | None, bool, str]:
    """Async wrapper for resolve_slug using a thread to avoid blocking."""
    return await asyncio.to_thread(resolve_slug, cwd, slug, ready_only, dependencies)


def check_file_exists(cwd: str, relative_path: str) -> bool:
    """Check if a file exists relative to cwd."""
    return (Path(cwd) / relative_path).exists()


def resolve_canonical_project_root(cwd: str) -> str:
    """Resolve canonical repository root from cwd.

    Accepts either the project root or a path inside a git worktree. Falls back
    to the provided cwd when git metadata is unavailable.
    """
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return cwd

    raw_common_dir = result.stdout.strip()
    if not raw_common_dir:
        return cwd

    common_dir = Path(raw_common_dir)
    if not common_dir.is_absolute():
        common_dir = (Path(cwd) / common_dir).resolve()
    else:
        common_dir = common_dir.resolve()

    return str((common_dir / "..").resolve())


def get_item_phase(cwd: str, slug: str) -> str:
    """Get current phase for a work item from state.yaml.

    Args:
        cwd: Project root directory
        slug: Work item slug to query

    Returns:
        One of "pending", "in_progress", "done"
    """
    state = read_phase_state(cwd, slug)
    phase = state.get("phase")
    return phase if isinstance(phase, str) else ItemPhase.PENDING.value


def is_ready_for_work(cwd: str, slug: str) -> bool:
    """Check if item is ready for work: pending phase + (build complete OR DOR score >= threshold)."""
    state = read_phase_state(cwd, slug)
    phase = state.get("phase")
    if phase != ItemPhase.PENDING.value:
        return False
    build = state.get(PhaseName.BUILD.value)
    # Build already complete (e.g. from-main items) — ready for review cycle
    if build == PhaseStatus.COMPLETE.value:
        return True
    if build != PhaseStatus.PENDING.value:
        return False
    dor = state.get("dor")
    if not isinstance(dor, dict):
        return False
    score = dor.get("score")
    return isinstance(score, int) and score >= DOR_READY_THRESHOLD


def set_item_phase(cwd: str, slug: str, phase: str) -> None:
    """Set phase for a work item in state.yaml.

    Args:
        cwd: Project root directory
        slug: Work item slug to update
        phase: One of "pending", "in_progress", "done"
    """
    state = read_phase_state(cwd, slug)
    state["phase"] = phase
    write_phase_state(cwd, slug, state)


__all__ = [
    "_find_next_prepare_slug",
    "check_file_exists",
    "get_item_phase",
    "is_ready_for_work",
    "resolve_canonical_project_root",
    "resolve_first_runnable_holder_child",
    "resolve_holder_children",
    "resolve_slug",
    "resolve_slug_async",
    "set_item_phase",
]
