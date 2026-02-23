"""Scaffold todo folders with canonical TeleClaude artifacts."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import yaml

from teleclaude.types.todos import BreakdownState, DorState, TodoState

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


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
    build="started",
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
    slug = slug.strip()
    if not slug:
        raise ValueError("Slug is required")
    if not SLUG_PATTERN.match(slug):
        raise ValueError("Invalid slug. Use lowercase letters, numbers, and hyphens only")

    todos_root = project_root / "todos"
    todo_dir = todos_root / slug

    if todo_dir.exists():
        raise FileExistsError(f"Todo already exists: {todo_dir}")

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

    Bug todos skip the prepare phase and start at in_progress/build phase.
    """
    from datetime import datetime, timezone

    slug = slug.strip()
    if not slug:
        raise ValueError("Slug is required")
    if not SLUG_PATTERN.match(slug):
        raise ValueError("Invalid slug. Use lowercase letters, numbers, and hyphens only")

    todos_root = project_root / "todos"
    todo_dir = todos_root / slug

    if todo_dir.exists():
        raise FileExistsError(f"Todo already exists: {todo_dir}")

    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

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

    slug = slug.strip()
    if not slug:
        raise ValueError("Slug is required")
    if not SLUG_PATTERN.match(slug):
        raise ValueError("Invalid slug. Use lowercase letters, numbers, and hyphens only")

    # Guard: check if worktree exists
    worktree_path = project_root / "trees" / slug
    if worktree_path.exists():
        raise RuntimeError(
            f"Cannot remove {slug}: worktree exists at {worktree_path}. "
            "Remove the worktree first with 'git worktree remove'."
        )

    todos_root = project_root / "todos"
    todo_dir = todos_root / slug

    # Track if we found anything to remove
    found_directory = todo_dir.exists()
    found_in_roadmap = remove_from_roadmap(str(project_root), slug)
    found_in_icebox = remove_from_icebox(str(project_root), slug)

    # Clean up dependency references
    clean_dependency_references(str(project_root), slug)

    # Delete directory if it exists
    if found_directory:
        shutil.rmtree(todo_dir)

    # Error if nothing was found
    if not (found_directory or found_in_roadmap or found_in_icebox):
        raise FileNotFoundError(f"Todo '{slug}' not found in directory, roadmap, or icebox")
