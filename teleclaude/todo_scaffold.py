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


def _load_dependencies(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("todos/dependencies.json must be a JSON object")
    result: dict[str, list[str]] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValueError("todos/dependencies.json must map string slugs to string arrays")
        result[key] = value
    return result


def _normalize_dep_list(items: list[str]) -> list[str]:
    deduped: list[str] = []
    for item in items:
        cleaned = item.strip()
        if not cleaned:
            continue
        if cleaned not in deduped:
            deduped.append(cleaned)
    return deduped


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

    Optionally updates todos/dependencies.json when ``after`` is provided.
    Does not modify todos/roadmap.md.
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
    state_content = json.dumps(_DEFAULT_STATE, indent=2) + "\n"

    _write_file(todo_dir / "requirements.md", req)
    _write_file(todo_dir / "implementation-plan.md", plan)
    _write_file(todo_dir / "quality-checklist.md", checklist)
    _write_file(todo_dir / "state.json", state_content)

    if after is not None:
        deps_path = todos_root / "dependencies.json"
        deps = _load_dependencies(deps_path)
        deps[slug] = _normalize_dep_list(after)
        deps = {k: v for k, v in deps.items() if v}

        if deps:
            deps_path.parent.mkdir(parents=True, exist_ok=True)
            deps_path.write_text(json.dumps(deps, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        elif deps_path.exists():
            deps_path.unlink()

    return todo_dir
