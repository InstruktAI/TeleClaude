"""Scaffold todo folders with canonical TeleClaude artifacts."""

from __future__ import annotations

import shutil
from datetime import UTC
from pathlib import Path

import yaml

from teleclaude.constants import WORKTREE_DIR
from teleclaude.slug import ensure_unique_slug, validate_slug
from teleclaude.types.todos import BreakdownState, DorState, TodoState

_DEFAULT_STATE = TodoState(
    build="pending",
    review="pending",
    deferrals_processed=False,
    breakdown=BreakdownState(assessed=False, todos=[]),
    dor=DorState(status="needs_work", score=0),
    review_round=0,
    max_review_rounds=3,
    review_baseline_commit="",
    unresolved_findings=[],
    resolved_findings=[],
).model_dump()


_BUG_STATE = TodoState(
    build="pending",
    review="pending",
    deferrals_processed=False,
    breakdown=BreakdownState(assessed=False, todos=[]),
    dor=None,
    review_round=0,
    max_review_rounds=3,
    review_baseline_commit="",
    unresolved_findings=[],
    resolved_findings=[],
).model_dump()


def _templates_root() -> Path:
    return Path(__file__).resolve().parent.parent / "templates" / "todos"


def _read_template(name: str) -> str:
    template_path = _templates_root() / name
    return template_path.read_text(encoding="utf-8")


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def create_todo_skeleton(
    project_root: Path,
    slug: str,
    *,
    after: list[str] | None = None,
) -> Path:
    """Create or refresh a todo skeleton folder.

    Creates:
    - todos/{slug}/requirements.md
    - todos/{slug}/implementation-plan.md
    - todos/{slug}/quality-checklist.md
    - todos/{slug}/demo.md
    - todos/{slug}/state.yaml

    Optionally registers the slug in todos/roadmap.yaml when ``after`` is provided.
    """
    validate_slug(slug)
    slug = slug.strip()

    todos_root = project_root / "todos"
    slug = ensure_unique_slug(todos_root, slug)
    todo_dir = todos_root / slug

    req = _read_template("requirements.md").format(slug=slug)
    plan = _read_template("implementation-plan.md").format(slug=slug)
    checklist = _read_template("quality-checklist.md").format(slug=slug)
    input_md = _read_template("input.md").format(slug=slug)
    demo_md = _read_template("demo.md").format(slug=slug)
    state_content = yaml.dump(_DEFAULT_STATE, default_flow_style=False, sort_keys=False)

    _write_file(todo_dir / "requirements.md", req)
    _write_file(todo_dir / "implementation-plan.md", plan)
    _write_file(todo_dir / "quality-checklist.md", checklist)
    _write_file(todo_dir / "input.md", input_md)
    _write_file(todo_dir / "demo.md", demo_md)
    _write_file(todo_dir / "state.yaml", state_content)

    if after is not None:
        from teleclaude.core.next_machine.core import add_to_roadmap

        # Deduplicate and clean deps
        deduped: list[str] = []
        for item in after:
            cleaned = item.strip()
            if cleaned and cleaned not in deduped:
                deduped.append(cleaned)

        add_to_roadmap(str(project_root), slug, after=deduped)

    return todo_dir


def create_bug_skeleton(
    project_root: Path,
    slug: str,
    description: str,
    *,
    reporter: str = "manual",
    session_id: str = "none",
) -> Path:
    """Create a bug todo skeleton folder.

    Creates:
    - todos/{slug}/bug.md
    - todos/{slug}/state.yaml

    Bug todos skip the prepare phase and start as pending build work.
    """
    from datetime import datetime

    validate_slug(slug)
    slug = slug.strip()

    todos_root = project_root / "todos"
    slug = ensure_unique_slug(todos_root, slug)
    todo_dir = todos_root / slug

    date = datetime.now(UTC).strftime("%Y-%m-%d")

    bug_md = _read_template("bug.md").format(
        description=description,
        reporter=reporter,
        session_id=session_id,
        date=date,
    )
    state_content = yaml.dump(_BUG_STATE, default_flow_style=False, sort_keys=False)

    _write_file(todo_dir / "bug.md", bug_md)
    _write_file(todo_dir / "state.yaml", state_content)

    return todo_dir


def split_todo(project_root: Path, parent_slug: str, child_slugs: list[str]) -> list[Path]:
    """Split a todo into child items (container transition).

    Scaffolds children, cleans parent builder artifacts, and sets container state.
    Returns list of created child directories.

    Raises:
        FileNotFoundError: If parent todo directory does not exist
        ValueError: If parent is already a container or child slug is invalid
        FileExistsError: If any child directory already exists
    """
    from teleclaude.core.next_machine.core import read_phase_state, write_phase_state

    validate_slug(parent_slug)
    parent_slug = parent_slug.strip()

    todos_root = project_root / "todos"
    parent_dir = todos_root / parent_slug

    if not parent_dir.exists():
        raise FileNotFoundError(f"Todo '{parent_slug}' not found at {parent_dir}")

    # Check parent is not already a container
    state = read_phase_state(str(project_root), parent_slug)
    breakdown = state.get("breakdown", {})
    if isinstance(breakdown, dict) and breakdown.get("todos"):
        raise ValueError(
            f"Todo '{parent_slug}' is already a container with children: {breakdown['todos']}"
        )

    # Validate all child slugs and check they don't exist
    for child in child_slugs:
        validate_slug(child)
        child_dir = todos_root / child
        if child_dir.exists():
            raise FileExistsError(f"Child todo '{child}' already exists at {child_dir}")

    # Scaffold children
    created: list[Path] = []
    for child in child_slugs:
        child_dir = create_todo_skeleton(project_root, child, after=[parent_slug])
        created.append(child_dir)

    # Clean parent builder artifacts — keep only input.md and state.yaml
    keep = {"input.md", "state.yaml"}
    for f in parent_dir.iterdir():
        if f.is_file() and f.name not in keep:
            f.unlink()

    # Reset parent state.yaml to container state
    state["breakdown"] = {"assessed": True, "todos": child_slugs}
    state["dor"] = {
        "score": 0,
        "status": "needs_work",
        "schema_version": 1,
        "blockers": [],
        "actions_taken": [],
    }
    state["requirements_review"] = {
        "verdict": "",
        "reviewed_at": "",
        "findings_count": 0,
        "rounds": 0,
    }
    state["plan_review"] = {
        "verdict": "",
        "reviewed_at": "",
        "findings_count": 0,
        "rounds": 0,
    }
    state["grounding"] = {
        "valid": False,
        "base_sha": "",
        "input_digest": "",
        "referenced_paths": [],
        "last_grounded_at": "",
        "invalidated_at": "",
        "invalidation_reason": "",
    }
    state["prepare_phase"] = ""
    write_phase_state(str(project_root), parent_slug, state)

    return created


def remove_todo(project_root: Path, slug: str) -> None:
    """Remove a todo and all its references.

    Removes:
    - todos/{slug}/ directory
    - Entry from todos/roadmap.yaml
    - Entry from todos/icebox.yaml (if present)
    - All `after` dependency references to this slug in roadmap and icebox

    Args:
        project_root: Project root directory
        slug: Todo slug to remove

    Raises:
        ValueError: If slug format is invalid
        RuntimeError: If worktree trees/{slug}/ exists
        FileNotFoundError: If slug has no directory and no roadmap/icebox entry
    """
    from teleclaude.core.next_machine.core import (
        clean_dependency_references,
        remove_from_icebox,
        remove_from_roadmap,
    )

    validate_slug(slug)
    slug = slug.strip()

    # Guard: check if worktree exists
    worktree_path = project_root / WORKTREE_DIR / slug
    if worktree_path.exists():
        raise RuntimeError(
            f"Cannot remove {slug}: worktree exists at {worktree_path}. "
            "Remove the worktree first with 'git worktree remove'."
        )

    todos_root = project_root / "todos"
    todo_dir = todos_root / slug
    icebox_dir = todos_root / "_icebox" / slug

    # Check both active and icebox locations
    found_in_active = todo_dir.exists()
    found_in_icebox_dir = icebox_dir.exists()
    found_directory = found_in_active or found_in_icebox_dir
    target_dir = todo_dir if found_in_active else icebox_dir

    found_in_roadmap = remove_from_roadmap(str(project_root), slug)
    found_in_icebox = remove_from_icebox(str(project_root), slug)

    # Clean up dependency references
    clean_dependency_references(str(project_root), slug)

    # Delete directory if it exists (from either location)
    if found_directory:
        shutil.rmtree(target_dir)

    # Error if nothing was found
    if not (found_directory or found_in_roadmap or found_in_icebox):
        raise FileNotFoundError(f"Todo '{slug}' not found in directory, roadmap, or icebox")
