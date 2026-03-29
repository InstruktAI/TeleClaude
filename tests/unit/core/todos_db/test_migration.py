"""RED tests for one-time migration from filesystem todos/ to todos.db."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from teleclaude.core.next_machine._types import StateValue
from teleclaude.core.todos_db import TodosDb

pytestmark = pytest.mark.asyncio


def _scaffold_todo(project: Path, slug: str, *, state: dict[str, StateValue] | None = None) -> None:
    """Create a minimal todo directory with state.yaml and artifacts."""
    todo_dir = project / "todos" / slug
    todo_dir.mkdir(parents=True, exist_ok=True)
    (todo_dir / "input.md").write_text(f"# Input for {slug}", encoding="utf-8")
    (todo_dir / "requirements.md").write_text(f"# Requirements for {slug}", encoding="utf-8")
    state_data = state or {"schema_version": 2, "current": "input_assessment", "phase": "pending"}
    (todo_dir / "state.yaml").write_text(yaml.dump(state_data), encoding="utf-8")


def _scaffold_roadmap(project: Path, slugs: list[str]) -> None:
    """Create a minimal roadmap.yaml."""
    entries = [{"slug": s} for s in slugs]
    (project / "todos" / "roadmap.yaml").write_text(yaml.dump(entries), encoding="utf-8")


async def test_migrate_imports_state_for_each_slug(todos_db: TodosDb, tmp_path: Path) -> None:
    from teleclaude.core.todos_db.migration import migrate_todos_to_db

    _scaffold_todo(tmp_path, "alpha")
    _scaffold_todo(tmp_path, "beta", state={"schema_version": 2, "current": "prepared", "phase": "pending"})
    _scaffold_roadmap(tmp_path, ["alpha", "beta"])

    await migrate_todos_to_db(str(tmp_path), todos_db)

    alpha_state = await todos_db.read_state("alpha")
    assert alpha_state is not None
    assert alpha_state["current"] == "input_assessment"

    beta_state = await todos_db.read_state("beta")
    assert beta_state is not None
    assert beta_state["current"] == "prepared"


async def test_migrate_imports_artifacts(todos_db: TodosDb, tmp_path: Path) -> None:
    from teleclaude.core.todos_db.migration import migrate_todos_to_db

    _scaffold_todo(tmp_path, "alpha")
    _scaffold_roadmap(tmp_path, ["alpha"])

    await migrate_todos_to_db(str(tmp_path), todos_db)

    content = await todos_db.read_artifact("alpha", "input")
    assert content == "# Input for alpha"
    content = await todos_db.read_artifact("alpha", "requirements")
    assert content == "# Requirements for alpha"


async def test_migrate_imports_roadmap_entries(todos_db: TodosDb, tmp_path: Path) -> None:
    from teleclaude.core.todos_db.migration import migrate_todos_to_db

    _scaffold_todo(tmp_path, "first")
    _scaffold_todo(tmp_path, "second")
    _scaffold_roadmap(tmp_path, ["first", "second"])

    await migrate_todos_to_db(str(tmp_path), todos_db)

    items = await todos_db.list_roadmap()
    assert [i["slug"] for i in items] == ["first", "second"]


async def test_migrate_is_idempotent(todos_db: TodosDb, tmp_path: Path) -> None:
    from teleclaude.core.todos_db.migration import migrate_todos_to_db

    _scaffold_todo(tmp_path, "alpha")
    _scaffold_roadmap(tmp_path, ["alpha"])

    await migrate_todos_to_db(str(tmp_path), todos_db)
    await migrate_todos_to_db(str(tmp_path), todos_db)

    slugs = await todos_db.list_slugs()
    assert slugs == ["alpha"]
