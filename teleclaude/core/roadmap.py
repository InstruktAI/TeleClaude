"""Core roadmap assembly logic.

Centralizes the logic for reading roadmap.yaml, icebox, and todo directories
into a single list of rich TodoInfo objects. Used by CLI, API, and TUI.
"""

import re
from pathlib import Path

import yaml
from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.models import TodoInfo
from teleclaude.core.next_machine._types import RoadmapEntry
from teleclaude.core.next_machine.core import load_delivered, load_icebox, load_roadmap

logger = get_logger(__name__)


def _slugify_heading(value: str) -> str:
    """Normalize a todo title heading into a filesystem-style slug."""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _load_icebox_data(
    todos_root: Path,
    icebox_root: Path,
    icebox_path: Path,
) -> tuple[list[RoadmapEntry], set[str], set[str]]:
    icebox_entries: list[RoadmapEntry] = []
    icebox_slugs: set[str] = set()
    icebox_groups: set[str] = set()
    icebox_yaml_path = icebox_root / "icebox.yaml"
    if icebox_yaml_path.exists():
        icebox_entries = load_icebox(str(todos_root.parent))
        icebox_slugs = {entry.slug for entry in icebox_entries}
        icebox_groups = {entry.group for entry in icebox_entries if entry.group}
        return icebox_entries, icebox_slugs, icebox_groups
    if not icebox_path.exists():
        return icebox_entries, icebox_slugs, icebox_groups

    heading_pattern = re.compile(r"^\s*#+\s+(.*)\s*$")
    table_pattern = re.compile(r"\|\s*([a-z0-9-]+)\s*\|")
    try:
        for line in icebox_path.read_text(encoding="utf-8").splitlines():
            heading_match = heading_pattern.match(line)
            if heading_match:
                heading = heading_match.group(1).strip()
                if heading and heading.lower() != "icebox":
                    icebox_slugs.add(_slugify_heading(heading))
                continue
            table_match = table_pattern.search(line)
            if table_match and table_match.group(1) != "slug":
                icebox_slugs.add(table_match.group(1))
    except OSError:
        pass
    return icebox_entries, icebox_slugs, icebox_groups


def _read_todo_metadata(
    project_path: str,
    todo_dir: Path,
) -> tuple[
    bool,
    bool,
    str | None,
    str | None,
    int | None,
    str | None,
    int,
    str,
    list[str],
    str | None,
    str | None,
    str | None,
]:
    has_requirements = (todo_dir / "requirements.md").exists()
    has_impl_plan = (todo_dir / "implementation-plan.md").exists()
    build_status = None
    review_status = None
    dor_score = None
    deferrals_status = None
    findings_count = 0
    phase_status = "pending"
    prepare_phase: str | None = None
    integration_phase: str | None = None
    finalize_status: str | None = None

    slug = todo_dir.name
    project_root = Path(project_path)
    worktree_state = project_root / WORKTREE_DIR / slug / "todos" / slug / "state.yaml"
    state_path = worktree_state if worktree_state.exists() else todo_dir / "state.yaml"
    if not state_path.exists():
        legacy_path = todo_dir / "state.json"
        if legacy_path.exists():
            state_path = legacy_path

    if state_path.exists():
        try:
            state = yaml.safe_load(state_path.read_text())
            build_status = state.get("build") if isinstance(state.get("build"), str) else "pending"
            review_status = state.get("review") if isinstance(state.get("review"), str) else "pending"
            dor = state.get("dor")
            if isinstance(dor, dict) and isinstance(dor.get("score"), int):
                dor_score = dor["score"]
            if state.get("deferrals_processed") is True:
                deferrals_status = "processed"
            unresolved = state.get("unresolved_findings")
            if isinstance(unresolved, list):
                findings_count = len(unresolved)
            prepare_phase = _non_empty_str(state.get("prepare_phase"))
            integration_phase = _non_empty_str(state.get("integration_phase"))
            finalize_status = _finalize_status(state.get("finalize"))
            phase_status = _derive_phase_status(state.get("phase"), build_status, dor_score)
        except (yaml.YAMLError, OSError):
            pass

    files = (
        sorted(f.name for f in todo_dir.iterdir() if f.is_file() and not f.name.startswith("."))
        if todo_dir.is_dir()
        else []
    )
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
        prepare_phase,
        integration_phase,
        finalize_status,
    )


def _non_empty_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _finalize_status(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    raw_status = value.get("status")
    if raw_status in ("pending", "ready", "handed_off"):
        return str(raw_status)
    return None


def _derive_phase_status(raw_phase: object, build_status: str | None, dor_score: int | None) -> str:
    if raw_phase in ("in_progress", "done"):
        return "in_progress"
    if build_status != "pending":
        return "in_progress"
    if isinstance(dor_score, int) and dor_score >= 8:
        return "ready"
    return "pending"


def _append_todo(
    todos: list[TodoInfo],
    *,
    project_path: str,
    todos_root: Path,
    icebox_root: Path,
    slug: str,
    description: str | None = None,
    after: list[str] | None = None,
    group: str | None = None,
    is_icebox_item: bool = False,
) -> None:
    todo_dir = (icebox_root / slug) if is_icebox_item and (icebox_root / slug).is_dir() else todos_root / slug
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
        prepare_phase,
        integration_phase,
        finalize_status,
    ) = _read_todo_metadata(project_path, todo_dir)
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
            prepare_phase=prepare_phase,
            integration_phase=integration_phase,
            finalize_status=finalize_status,
        )
    )


def _infer_input_description(todo_dir: Path) -> str | None:
    input_path = todo_dir / "input.md"
    if not input_path.exists():
        return None
    try:
        for line in input_path.read_text().splitlines():
            cleaned = line.strip()
            if not cleaned:
                continue
            return cleaned.lstrip("#").strip() if cleaned.startswith("#") else cleaned
    except OSError:
        return None
    return None


def _load_active_roadmap_items(
    todos: list[TodoInfo],
    seen_slugs: set[str],
    *,
    project_path: str,
    todos_root: Path,
    icebox_root: Path,
    icebox_slugs: set[str],
) -> None:
    for entry in load_roadmap(project_path):
        if entry.slug in seen_slugs:
            logger.warning("Duplicate todo slug '%s' in roadmap.yaml, ignoring duplicate", entry.slug)
            continue
        if entry.slug in icebox_slugs:
            logger.info("Skipping todo '%s' because it is in icebox", entry.slug)
            continue
        seen_slugs.add(entry.slug)
        _append_todo(
            todos,
            project_path=project_path,
            todos_root=todos_root,
            icebox_root=icebox_root,
            slug=entry.slug,
            description=entry.description,
            after=entry.after,
            group=entry.group,
        )


def _load_icebox_items(
    todos: list[TodoInfo],
    seen_slugs: set[str],
    *,
    project_path: str,
    todos_root: Path,
    icebox_root: Path,
    include_icebox: bool,
    icebox_entries: list[RoadmapEntry],
) -> None:
    if not include_icebox:
        return
    for entry in icebox_entries:
        if entry.slug in seen_slugs:
            continue
        seen_slugs.add(entry.slug)
        _append_todo(
            todos,
            project_path=project_path,
            todos_root=todos_root,
            icebox_root=icebox_root,
            slug=entry.slug,
            description=entry.description,
            after=entry.after,
            group=entry.group,
            is_icebox_item=True,
        )


def _load_delivered_items(
    todos: list[TodoInfo],
    seen_slugs: set[str],
    *,
    project_path: str,
    todos_root: Path,
    icebox_root: Path,
    include_delivered: bool,
) -> None:
    if not include_delivered:
        return
    for entry in load_delivered(project_path):
        if entry.slug in seen_slugs:
            continue
        seen_slugs.add(entry.slug)
        _append_todo(
            todos,
            project_path=project_path,
            todos_root=todos_root,
            icebox_root=icebox_root,
            slug=entry.slug,
            group="Delivered",
        )
        todos[-1].status = "delivered"
        todos[-1].delivered_at = entry.date


def _append_orphan_todos(
    todos: list[TodoInfo],
    seen_slugs: set[str],
    *,
    project_path: str,
    todos_root: Path,
    icebox_root: Path,
    icebox_slugs: set[str],
    icebox_groups: set[str],
    include_icebox: bool,
    icebox_only: bool,
    delivered_only: bool,
) -> None:
    for todo_dir in sorted(todos_root.iterdir(), key=lambda p: p.name):
        if (
            not todo_dir.is_dir()
            or todo_dir.name.startswith(".")
            or todo_dir.name == "_icebox"
            or todo_dir.name in seen_slugs
        ):
            continue
        is_icebox = todo_dir.name in icebox_slugs or todo_dir.name in icebox_groups
        if (is_icebox and not include_icebox) or (icebox_only and not is_icebox) or delivered_only:
            continue
        seen_slugs.add(todo_dir.name)
        orphan_group = (
            todo_dir.name if todo_dir.name in icebox_groups else ("Icebox" if todo_dir.name in icebox_slugs else None)
        )
        _append_todo(
            todos,
            project_path=project_path,
            todos_root=todos_root,
            icebox_root=icebox_root,
            slug=todo_dir.name,
            description=_infer_input_description(todo_dir),
            group=orphan_group,
        )


def _inject_breakdown_relationships(todos: list[TodoInfo], todos_root: Path) -> None:
    slug_to_idx = {todo.slug: idx for idx, todo in enumerate(todos)}
    for todo in list(todos):
        state_path = todos_root / todo.slug / "state.yaml"
        if not state_path.exists():
            legacy_path = todos_root / todo.slug / "state.json"
            if legacy_path.exists():
                state_path = legacy_path
        if not state_path.exists():
            continue
        try:
            state = yaml.safe_load(state_path.read_text())
            child_slugs = state.get("breakdown", {}).get("todos", [])
            children_in_list = [child_slug for child_slug in child_slugs if child_slug in slug_to_idx]
            if not children_in_list:
                continue
            for child_slug in children_in_list:
                child = todos[slug_to_idx[child_slug]]
                if todo.slug not in child.after:
                    child.after.append(todo.slug)
            if not todo.group:
                first_child = todos[slug_to_idx[children_in_list[0]]]
                if first_child.group:
                    todo.group = first_child.group
            container_idx = slug_to_idx[todo.slug]
            first_child_idx = min(slug_to_idx[child_slug] for child_slug in children_in_list)
            if container_idx > first_child_idx:
                todos.pop(container_idx)
                todos.insert(first_child_idx, todo)
                slug_to_idx = {item.slug: idx for idx, item in enumerate(todos)}
        except (yaml.YAMLError, OSError):
            continue


def assemble_roadmap(
    project_path: str,
    include_icebox: bool = False,
    icebox_only: bool = False,
    include_delivered: bool = False,
    delivered_only: bool = False,
) -> list[TodoInfo]:
    """Assemble a rich list of todos from roadmap, icebox, delivered, and filesystem.

    Args:
        project_path: Absolute path to project directory
        include_icebox: If True, include items from icebox.yaml
        icebox_only: If True, include ONLY items from icebox.yaml (implies include_icebox=True)
        include_delivered: If True, include items from delivered.yaml
        delivered_only: If True, include ONLY items from delivered.yaml (implies include_delivered=True)

    Returns:
        List of TodoInfo objects with full metadata (DOR, build status, etc.)
    """
    if icebox_only:
        include_icebox = True
    if delivered_only:
        include_delivered = True

    todos_root = Path(project_path) / "todos"
    icebox_root = todos_root / "_icebox"
    icebox_path = todos_root / "icebox.md"  # Legacy fallback

    todos: list[TodoInfo] = []
    seen_slugs: set[str] = set()

    if not todos_root.exists():
        return []

    icebox_entries, icebox_slugs, icebox_groups = _load_icebox_data(todos_root, icebox_root, icebox_path)

    # 1. Load active roadmap items
    if not icebox_only and not delivered_only:
        _load_active_roadmap_items(
            todos,
            seen_slugs,
            project_path=project_path,
            todos_root=todos_root,
            icebox_root=icebox_root,
            icebox_slugs=icebox_slugs,
        )

    # 2. Load icebox entries with their real metadata (group, after, description)
    _load_icebox_items(
        todos,
        seen_slugs,
        project_path=project_path,
        todos_root=todos_root,
        icebox_root=icebox_root,
        include_icebox=include_icebox,
        icebox_entries=icebox_entries,
    )

    # 2b. Load delivered entries
    _load_delivered_items(
        todos,
        seen_slugs,
        project_path=project_path,
        todos_root=todos_root,
        icebox_root=icebox_root,
        include_delivered=include_delivered,
    )

    # 3. Scan for remaining directories (orphans or untracked icebox containers)
    _append_orphan_todos(
        todos,
        seen_slugs,
        project_path=project_path,
        todos_root=todos_root,
        icebox_root=icebox_root,
        icebox_slugs=icebox_slugs,
        icebox_groups=icebox_groups,
        include_icebox=include_icebox,
        icebox_only=icebox_only,
        delivered_only=delivered_only,
    )
    _inject_breakdown_relationships(todos, todos_root)

    return todos
