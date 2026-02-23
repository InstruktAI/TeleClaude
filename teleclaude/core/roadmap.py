"""Core roadmap assembly logic.

Centralizes the logic for reading roadmap.yaml, icebox, and todo directories
into a single list of rich TodoInfo objects. Used by CLI, API, and TUI.
"""

import re
from pathlib import Path

import yaml
from instrukt_ai_logging import get_logger

from teleclaude.core.models import TodoInfo
from teleclaude.core.next_machine.core import load_icebox, load_roadmap

logger = get_logger(__name__)


def assemble_roadmap(
    project_path: str,
    include_icebox: bool = False,
    icebox_only: bool = False,
) -> list[TodoInfo]:
    """Assemble a rich list of todos from roadmap, icebox, and filesystem.

    Args:
        project_path: Absolute path to project directory
        include_icebox: If True, include items from icebox.yaml
        icebox_only: If True, include ONLY items from icebox.yaml (implies include_icebox=True)

    Returns:
        List of TodoInfo objects with full metadata (DOR, build status, etc.)
    """
    if icebox_only:
        include_icebox = True

    todos_root = Path(project_path) / "todos"
    icebox_path = todos_root / "icebox.md"  # Legacy fallback

    todos: list[TodoInfo] = []
    seen_slugs: set[str] = set()

    if not todos_root.exists():
        return []

    def slugify_heading(value: str) -> str:
        """Normalize a todo title heading into a filesystem-style slug."""
        return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")

    # Load icebox data — full entries when yaml exists, slugs-only for legacy
    icebox_entries = []
    icebox_slugs: set[str] = set()
    icebox_groups: set[str] = set()

    icebox_yaml_path = todos_root / "icebox.yaml"
    if icebox_yaml_path.exists():
        icebox_entries = load_icebox(str(todos_root.parent))
        icebox_slugs = {e.slug for e in icebox_entries}
        icebox_groups = {e.group for e in icebox_entries if e.group}
    elif icebox_path.exists():
        heading_pattern = re.compile(r"^\s*#+\s+(.*)\s*$")
        table_pattern = re.compile(r"\|\s*([a-z0-9-]+)\s*\|")
        try:
            for line in icebox_path.read_text(encoding="utf-8").splitlines():
                heading_match = heading_pattern.match(line)
                if heading_match:
                    heading = heading_match.group(1).strip()
                    if heading and heading.lower() != "icebox":
                        icebox_slugs.add(slugify_heading(heading))
                    continue
                table_match = table_pattern.search(line)
                if table_match:
                    slug = table_match.group(1)
                    if slug != "slug":
                        icebox_slugs.add(slug)
        except OSError:
            pass

    def read_todo_metadata(
        todo_dir: Path,
    ) -> tuple[bool, bool, str | None, str | None, int | None, str | None, int, str, list[str]]:
        has_requirements = (todo_dir / "requirements.md").exists()
        has_impl_plan = (todo_dir / "implementation-plan.md").exists()
        build_status = None
        review_status = None
        dor_score = None
        deferrals_status = None
        findings_count = 0
        phase_status = "pending"

        state_path = todo_dir / "state.yaml"
        # Backward compat: fall back to state.json
        if not state_path.exists():
            legacy_path = todo_dir / "state.json"
            if legacy_path.exists():
                state_path = legacy_path

        if state_path.exists():
            try:
                state = yaml.safe_load(state_path.read_text())
                # Derive status from phase field
                raw_phase = state.get("phase")
                if raw_phase == "ready":
                    # Migration: normalize persisted "ready" to "pending"
                    phase_status = "pending"
                elif isinstance(raw_phase, str) and raw_phase in ("pending", "in_progress", "done"):
                    phase_status = raw_phase
                else:
                    # Migration: derive phase from existing fields
                    build_val = state.get("build")
                    if isinstance(build_val, str) and build_val != "pending":
                        phase_status = "in_progress"

                build_status = state.get("build") if isinstance(state.get("build"), str) else None
                review_status = state.get("review") if isinstance(state.get("review"), str) else None
                dor = state.get("dor")
                if isinstance(dor, dict):
                    raw_score = dor.get("score")
                    if isinstance(raw_score, int):
                        dor_score = raw_score
                deferrals_processed = state.get("deferrals_processed")
                if deferrals_processed is True:
                    deferrals_status = "processed"
                unresolved = state.get("unresolved_findings")
                if isinstance(unresolved, list):
                    findings_count = len(unresolved)

                # Build past pending means work has started
                if phase_status == "pending" and build_status and build_status != "pending":
                    phase_status = "in_progress"

                # Derive display status: pending + dor_score >= 8 shows as "ready"
                if phase_status == "pending" and isinstance(dor_score, int) and dor_score >= 8:
                    phase_status = "ready"
            except (yaml.YAMLError, OSError):
                pass

        files: list[str] = []
        if todo_dir.is_dir():
            files = sorted(f.name for f in todo_dir.iterdir() if f.is_file() and not f.name.startswith("."))

        return (
            has_requirements,
            has_impl_plan,
            build_status,
            review_status,
            dor_score,
            deferrals_status,
            findings_count,
            phase_status,
            files,
        )

    def append_todo(
        slug: str,
        description: str | None = None,
        after: list[str] | None = None,
        group: str | None = None,
    ) -> None:
        todo_dir = todos_root / slug
        (
            has_requirements,
            has_impl_plan,
            build_status,
            review_status,
            dor_score,
            deferrals_status,
            findings_count,
            phase_status,
            files,
        ) = read_todo_metadata(todo_dir)

        todos.append(
            TodoInfo(
                slug=slug,
                status=phase_status,
                description=description,
                has_requirements=has_requirements,
                has_impl_plan=has_impl_plan,
                build_status=build_status,
                review_status=review_status,
                dor_score=dor_score,
                deferrals_status=deferrals_status,
                findings_count=findings_count,
                files=files,
                after=after or [],
                group=group,
            )
        )

    def infer_input_description(todo_dir: Path) -> str | None:
        input_path = todo_dir / "input.md"
        if not input_path.exists():
            return None
        try:
            for line in input_path.read_text().splitlines():
                cleaned = line.strip()
                if not cleaned:
                    continue
                if cleaned.startswith("#"):
                    return cleaned.lstrip("#").strip()
                return cleaned
        except OSError:
            return None
        return None

    # 1. Load active roadmap items
    if not icebox_only:
        roadmap_entries = load_roadmap(project_path)
        for entry in roadmap_entries:
            slug = entry.slug
            if slug in seen_slugs:
                logger.warning("Duplicate todo slug '%s' in roadmap.yaml, ignoring duplicate", slug)
                continue
            if slug in icebox_slugs:
                logger.info("Skipping todo '%s' because it is in icebox", slug)
                continue

            seen_slugs.add(slug)
            append_todo(slug, description=entry.description, after=entry.after, group=entry.group)

    # 2. Load icebox entries with their real metadata (group, after, description)
    if include_icebox:
        for entry in icebox_entries:
            if entry.slug in seen_slugs:
                continue
            seen_slugs.add(entry.slug)
            append_todo(entry.slug, description=entry.description, after=entry.after, group=entry.group)

    # 3. Scan for remaining directories (orphans or untracked icebox containers)
    for todo_dir in sorted(todos_root.iterdir(), key=lambda p: p.name):
        if not todo_dir.is_dir():
            continue
        if todo_dir.name.startswith("."):
            continue
        if todo_dir.name in seen_slugs:
            continue

        is_icebox = todo_dir.name in icebox_slugs or todo_dir.name in icebox_groups

        if is_icebox and not include_icebox:
            continue
        if icebox_only and not is_icebox:
            continue

        seen_slugs.add(todo_dir.name)
        # Icebox group containers get their group name; stray icebox slugs get "Icebox"
        orphan_group: str | None = None
        if todo_dir.name in icebox_groups:
            orphan_group = todo_dir.name
        elif todo_dir.name in icebox_slugs:
            orphan_group = "Icebox"
        append_todo(
            todo_dir.name,
            description=infer_input_description(todo_dir),
            group=orphan_group,
        )

    # 4. Inject container→child relationships from breakdown.todos in state.yaml.
    # This makes container todos appear as tree parents of their sub-items.
    # The reordering loop below is safe because it rebuilds slug_to_idx after each mutation,
    # ensuring that hierarchical containers (no circular deps) are correctly repositioned
    # before their children regardless of discovery order.
    slug_to_idx = {t.slug: i for i, t in enumerate(todos)}
    for todo in list(todos):
        state_path = todos_root / todo.slug / "state.yaml"
        # Backward compat: fall back to state.json
        if not state_path.exists():
            legacy_path = todos_root / todo.slug / "state.json"
            if legacy_path.exists():
                state_path = legacy_path

        if not state_path.exists():
            continue
        try:
            state = yaml.safe_load(state_path.read_text())
            child_slugs = state.get("breakdown", {}).get("todos", [])
            if not child_slugs:
                continue
            # Only process if at least one child is in the list
            children_in_list = [cs for cs in child_slugs if cs in slug_to_idx]
            if not children_in_list:
                continue
            # Inject container as after-dependency for each child
            for cs in children_in_list:
                child = todos[slug_to_idx[cs]]
                if todo.slug not in child.after:
                    child.after.append(todo.slug)
            # Propagate group from first child if container has none
            if not todo.group:
                first_child = todos[slug_to_idx[children_in_list[0]]]
                if first_child.group:
                    todo.group = first_child.group
            # Move container before its first child for correct visual ordering
            container_idx = slug_to_idx[todo.slug]
            first_child_idx = min(slug_to_idx[cs] for cs in children_in_list)
            if container_idx > first_child_idx:
                todos.pop(container_idx)
                todos.insert(first_child_idx, todo)
                slug_to_idx = {t.slug: i for i, t in enumerate(todos)}
        except (yaml.YAMLError, OSError):
            continue

    return todos
