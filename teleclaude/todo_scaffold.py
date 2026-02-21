"""Scaffold todo folders with canonical TeleClaude artifacts."""

from __future__ import annotations

import json
import re
from pathlib import Path

from teleclaude.types.todos import BreakdownState, DorState, TodoState

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


_DEFAULT_STATE = TodoState(
    phase="pending",
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
    - todos/{slug}/state.json

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
    state_content = json.dumps(_DEFAULT_STATE, indent=2) + "\n"

    _write_file(todo_dir / "requirements.md", req)
    _write_file(todo_dir / "implementation-plan.md", plan)
    _write_file(todo_dir / "quality-checklist.md", checklist)
    _write_file(todo_dir / "input.md", input_md)
    _write_file(todo_dir / "state.json", state_content)

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
