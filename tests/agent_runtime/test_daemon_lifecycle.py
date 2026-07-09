"""Functional regression test for the projects-with-todos listing.

The projects-with-todos listing returns every existing trusted directory. A
trusted directory that is not a TeleClaude project checkout carries an empty
todo list, and no todo store is opened or created for it.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from teleclaude.config import TrustedDir, config
from teleclaude.core.command_handlers import list_projects_with_todos
from teleclaude.core.todos_db import close_todos_db_instances, get_todos_db
from teleclaude.git import Repo
from teleclaude.types.lifecycle import LifecyclePhase

pytestmark = pytest.mark.functional

_SPEC = "docs/project/spec/feature/agent_runtime/daemon-lifecycle.md"
_SEEDED_SLUG = "seeded-checkout-todo"


@pytest.fixture(autouse=True)
async def _close_todos_db_after_test() -> AsyncGenerator[None]:
    yield
    await close_todos_db_instances()


def _init_checkout(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    Repo.init(root)
    (root / "teleclaude.yml").write_text("business:\n  domains:\n    software-development: docs\n", encoding="utf-8")
    return root


def _init_non_checkout(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    Repo.init(root)
    return root


@pytest.mark.spec(_SPEC, "UC-DL1")
@pytest.mark.asyncio
async def test_projects_listing_tolerates_a_non_checkout_trusted_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-checkout trusted dir lists with no todos; a checkout keeps its todos."""
    checkout_dir = _init_checkout(tmp_path / "checkout")
    non_checkout_dir = _init_non_checkout(tmp_path / "non-checkout")

    todos_db = await get_todos_db(checkout_dir)
    await todos_db.add_to_todo(_SEEDED_SLUG, lineage="human:test@example.com")
    await todos_db.write_state(
        _SEEDED_SLUG,
        {
            "schema_version": 4,
            "kind": "task",
            "phase": "pending",
            "lifecycle_phase": LifecyclePhase.PREPARED.value,
        },
    )

    monkeypatch.setattr(
        config.computer,
        "trusted_dirs",
        [
            TrustedDir(name="checkout", desc="", path=str(checkout_dir)),
            TrustedDir(name="non-checkout", desc="", path=str(non_checkout_dir)),
        ],
    )

    projects = await list_projects_with_todos()

    by_path = {project.path: project for project in projects}
    assert set(by_path) == {str(checkout_dir), str(non_checkout_dir)}

    checkout_project = by_path[str(checkout_dir)]
    assert {todo.slug for todo in checkout_project.todos} == {_SEEDED_SLUG}

    non_checkout_project = by_path[str(non_checkout_dir)]
    assert non_checkout_project.todos == []
    assert not (non_checkout_dir / ".teleclaude" / "todos.db").exists()
