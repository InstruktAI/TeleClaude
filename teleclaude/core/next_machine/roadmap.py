"""Roadmap management — load, save, and query todos/roadmap.yaml.

Also owns dependency cycle detection.
slug_in_roadmap lives here (not slug_resolution) to prevent a circular
dep: check_dependencies_satisfied → slug_in_roadmap → load_roadmap_slugs.
No imports from core.py (circular-import guard).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from teleclaude.core.next_machine._types import (
    ItemPhase,
    PhaseName,
    PhaseStatus,
    RoadmapDict,
    RoadmapEntry,
)
from teleclaude.core.next_machine.state_io import read_phase_state, read_text_sync, write_text_sync


def _roadmap_path(cwd: str) -> Path:
    return Path(cwd) / "todos" / "roadmap.yaml"


def load_roadmap(cwd: str) -> list[RoadmapEntry]:
    """Parse todos/roadmap.yaml and return ordered list of entries."""
    path = _roadmap_path(cwd)
    if not path.exists():
        return []

    content = read_text_sync(path)
    raw = yaml.safe_load(content)
    if not isinstance(raw, list):
        return []

    entries: list[RoadmapEntry] = []
    for item in raw:
        if not isinstance(item, dict) or "slug" not in item:
            continue
        after = item.get("after")
        entries.append(
            RoadmapEntry(
                slug=item["slug"],
                group=item.get("group"),
                after=list(after) if isinstance(after, list) else [],
                description=item.get("description"),
            )
        )
    return entries


def save_roadmap(cwd: str, entries: list[RoadmapEntry]) -> None:
    """Write entries back to todos/roadmap.yaml."""
    path = _roadmap_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)

    data: list[RoadmapDict] = []
    for entry in entries:
        item: RoadmapDict = {"slug": entry.slug}
        if entry.group:
            item["group"] = entry.group
        if entry.after:
            item["after"] = entry.after
        if entry.description:
            item["description"] = entry.description
        data.append(item)

    header = "# Priority order (first = highest). Per-item state in {slug}/state.yaml.\n\n"
    body = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    write_text_sync(path, header + body)


def load_roadmap_slugs(cwd: str) -> list[str]:
    """Return slug strings in roadmap order."""
    return [e.slug for e in load_roadmap(cwd)]


def load_roadmap_deps(cwd: str) -> dict[str, list[str]]:
    """Return dependency graph dict from roadmap (replaces read_dependencies)."""
    return {e.slug: e.after for e in load_roadmap(cwd) if e.after}


def slug_in_roadmap(cwd: str, slug: str) -> bool:
    """Check if a slug exists in todos/roadmap.yaml."""
    return slug in load_roadmap_slugs(cwd)


def add_to_roadmap(
    cwd: str,
    slug: str,
    *,
    group: str | None = None,
    after: list[str] | None = None,
    description: str | None = None,
    before: str | None = None,
) -> bool:
    """Add entry to roadmap.yaml at specified position (default: append).

    Returns True if the entry was added, False if it already existed.
    """
    entries = load_roadmap(cwd)
    # Avoid duplicates
    if any(e.slug == slug for e in entries):
        return False

    entry = RoadmapEntry(slug=slug, group=group, after=after or [], description=description)

    if before:
        for i, e in enumerate(entries):
            if e.slug == before:
                entries.insert(i, entry)
                save_roadmap(cwd, entries)
                return True

    entries.append(entry)
    save_roadmap(cwd, entries)
    return True


def remove_from_roadmap(cwd: str, slug: str) -> bool:
    """Remove entry from roadmap.yaml. Returns True if found and removed."""
    entries = load_roadmap(cwd)
    original_len = len(entries)
    entries = [e for e in entries if e.slug != slug]
    if len(entries) < original_len:
        save_roadmap(cwd, entries)
        return True
    return False


def move_in_roadmap(cwd: str, slug: str, *, before: str | None = None, after: str | None = None) -> bool:
    """Reorder entry in roadmap.yaml. Returns True if moved successfully."""
    entries = load_roadmap(cwd)
    source_idx = None
    for i, e in enumerate(entries):
        if e.slug == slug:
            source_idx = i
            break
    if source_idx is None:
        return False

    entry = entries.pop(source_idx)

    target: str | None = before or after
    target_idx = None
    for i, e in enumerate(entries):
        if e.slug == target:
            target_idx = i
            break

    if target_idx is None:
        entries.insert(source_idx, entry)
        return False

    if before:
        entries.insert(target_idx, entry)
    else:
        entries.insert(target_idx + 1, entry)
    save_roadmap(cwd, entries)
    return True


def check_dependencies_satisfied(cwd: str, slug: str, deps: dict[str, list[str]]) -> bool:
    """Check if all dependencies for a slug are satisfied.

    A dependency is satisfied if:
    - Its phase is "done" in state.yaml, OR
    - It is not present in roadmap.yaml (assumed completed/removed)

    Args:
        cwd: Project root directory
        slug: Work item to check
        deps: Dependency graph

    Returns:
        True if all dependencies are satisfied (or no dependencies)
    """
    item_deps = deps.get(slug, [])
    if not item_deps:
        return True

    for dep in item_deps:
        if not slug_in_roadmap(cwd, dep):
            # Not in roadmap - treat as satisfied (completed and cleaned up)
            continue

        dep_state = read_phase_state(cwd, dep)
        dep_phase = dep_state.get("phase")
        if dep_phase == ItemPhase.DONE.value:
            continue

        dep_review = dep_state.get(PhaseName.REVIEW.value)
        if dep_review == PhaseStatus.APPROVED.value:
            continue

        # Backward compatibility with older state where only build/review fields
        # were used and "phase" was derived later.
        if (
            dep_state.get(PhaseName.BUILD.value) == PhaseStatus.COMPLETE.value
            and dep_state.get(PhaseName.REVIEW.value) == PhaseStatus.APPROVED.value
        ):
            continue

        return False

    return True


def detect_circular_dependency(deps: dict[str, list[str]], slug: str, new_deps: list[str]) -> list[str] | None:
    """Detect if adding new_deps to slug would create a cycle.

    Args:
        deps: Current dependency graph
        slug: Item we're updating
        new_deps: New dependencies for slug

    Returns:
        List representing the cycle path if cycle detected, None otherwise
    """
    # Build graph with proposed change
    graph: dict[str, set[str]] = {k: set(v) for k, v in deps.items()}
    graph[slug] = set(new_deps)

    # DFS to detect cycle
    visited: set[str] = set()
    path: list[str] = []

    def dfs(node: str) -> list[str] | None:
        if node in path:
            # Found cycle - return path from cycle start
            cycle_start = path.index(node)
            return path[cycle_start:] + [node]

        if node in visited:
            return None

        visited.add(node)
        path.append(node)

        for dep in graph.get(node, set()):
            result = dfs(dep)
            if result:
                return result

        path.pop()
        return None

    # Check from the slug we're modifying
    for dep in new_deps:
        path = [slug]
        visited = {slug}
        result = dfs(dep)
        if result:
            return [slug] + result

    return None
