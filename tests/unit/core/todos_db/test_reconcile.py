"""Tests for filesystem → DB reconciliation."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
import yaml

from teleclaude.core.todos_db import TodosDb
from teleclaude.core.todos_db.reconcile import reconcile_filesystem_to_db


def _write_state(todo_dir: Path, state: dict[str, str]) -> None:
    todo_dir.mkdir(parents=True, exist_ok=True)
    (todo_dir / "state.yaml").write_text(yaml.safe_dump(state), encoding="utf-8")


def _write_artifact(todo_dir: Path, name: str, content: str) -> None:
    todo_dir.mkdir(parents=True, exist_ok=True)
    (todo_dir / f"{name}.md").write_text(content, encoding="utf-8")


@pytest.mark.unit
async def test_inserts_new_slug_from_filesystem(todos_db: TodosDb, tmp_path: Path) -> None:
    """Filesystem slug with no DB entry is inserted with correct state and artifacts."""
    todo_dir = tmp_path / "todos" / "new-slug"
    _write_state(todo_dir, {"current": "build_started", "phase": "in_progress"})
    _write_artifact(todo_dir, "requirements", "Real requirements content")

    counts = await reconcile_filesystem_to_db(str(tmp_path), todos_db)

    assert counts["state_inserted"] == 1
    assert counts["artifacts_inserted"] == 1
    state = await todos_db.read_state("new-slug")
    assert state is not None
    assert state["current"] == "build_started"
    content = await todos_db.read_artifact("new-slug", "requirements")
    assert content == "Real requirements content"


@pytest.mark.unit
async def test_updates_state_when_filesystem_is_newer(todos_db: TodosDb, tmp_path: Path) -> None:
    """Filesystem state.yaml with newer mtime overwrites the DB entry."""
    # Write old state to DB (roadmap entry required by write_state contract)
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"current": "input_assessment"})

    # Write newer state to filesystem (touch with future mtime)
    todo_dir = tmp_path / "todos" / "my-slug"
    _write_state(todo_dir, {"current": "finalize_ready", "phase": "in_progress"})
    state_path = todo_dir / "state.yaml"
    future_mtime = time.time() + 3600
    os.utime(state_path, (future_mtime, future_mtime))

    counts = await reconcile_filesystem_to_db(str(tmp_path), todos_db)

    assert counts["state_updated"] == 1
    state = await todos_db.read_state("my-slug")
    assert state is not None
    assert state["current"] == "finalize_ready"


@pytest.mark.unit
async def test_skips_state_when_db_is_newer(todos_db: TodosDb, tmp_path: Path) -> None:
    """DB entry with newer timestamp is kept when filesystem state is older."""
    # Write state to DB (roadmap entry required by write_state contract)
    await todos_db.add_to_roadmap("my-slug")
    await todos_db.write_state("my-slug", {"current": "review_approved"})

    # Write old state to filesystem (set mtime to past)
    todo_dir = tmp_path / "todos" / "my-slug"
    _write_state(todo_dir, {"current": "input_assessment"})
    state_path = todo_dir / "state.yaml"
    past_mtime = 1000000000.0  # 2001
    os.utime(state_path, (past_mtime, past_mtime))

    counts = await reconcile_filesystem_to_db(str(tmp_path), todos_db)

    assert counts["state_updated"] == 0
    state = await todos_db.read_state("my-slug")
    assert state is not None
    assert state["current"] == "review_approved"


@pytest.mark.unit
async def test_updates_artifact_when_filesystem_is_newer(todos_db: TodosDb, tmp_path: Path) -> None:
    """Artifact with newer filesystem mtime overwrites the DB copy."""
    await todos_db.write_artifact("my-slug", "requirements", "old content")

    todo_dir = tmp_path / "todos" / "my-slug"
    _write_artifact(todo_dir, "requirements", "newer content from reviewer")
    artifact_path = todo_dir / "requirements.md"
    future_mtime = time.time() + 3600
    os.utime(artifact_path, (future_mtime, future_mtime))

    counts = await reconcile_filesystem_to_db(str(tmp_path), todos_db)

    assert counts["artifacts_updated"] == 1
    content = await todos_db.read_artifact("my-slug", "requirements")
    assert content == "newer content from reviewer"


@pytest.mark.unit
async def test_skips_artifact_when_content_identical(todos_db: TodosDb, tmp_path: Path) -> None:
    """Artifact with identical digest is skipped even when filesystem mtime is newer."""
    content = "same content"
    await todos_db.write_artifact("my-slug", "requirements", content)

    todo_dir = tmp_path / "todos" / "my-slug"
    _write_artifact(todo_dir, "requirements", content)
    # Even with future mtime, identical digest means skip
    artifact_path = todo_dir / "requirements.md"
    future_mtime = time.time() + 3600
    os.utime(artifact_path, (future_mtime, future_mtime))

    counts = await reconcile_filesystem_to_db(str(tmp_path), todos_db)

    assert counts["artifacts_updated"] == 0


@pytest.mark.unit
async def test_prefers_worktree_state_when_newer(todos_db: TodosDb, tmp_path: Path) -> None:
    """Worktree state.yaml wins over main todos/ state when it has a newer mtime."""
    # Main has old state
    main_dir = tmp_path / "todos" / "my-slug"
    _write_state(main_dir, {"current": "build_started"})
    past_mtime = 1000000000.0
    os.utime(main_dir / "state.yaml", (past_mtime, past_mtime))

    # Worktree has newer state
    wt_dir = tmp_path / "trees" / "my-slug" / "todos" / "my-slug"
    _write_state(wt_dir, {"current": "finalize_handed_off"})
    future_mtime = time.time() + 3600
    os.utime(wt_dir / "state.yaml", (future_mtime, future_mtime))

    counts = await reconcile_filesystem_to_db(str(tmp_path), todos_db)

    assert counts["state_inserted"] == 1
    state = await todos_db.read_state("my-slug")
    assert state is not None
    assert state["current"] == "finalize_handed_off"


@pytest.mark.unit
async def test_idempotent_second_run_changes_nothing(todos_db: TodosDb, tmp_path: Path) -> None:
    """Second reconcile run produces zero changes when sources are already in sync."""
    todo_dir = tmp_path / "todos" / "my-slug"
    _write_state(todo_dir, {"current": "prepared"})
    _write_artifact(todo_dir, "input", "brain dump")

    first = await reconcile_filesystem_to_db(str(tmp_path), todos_db)
    assert first["state_inserted"] == 1

    second = await reconcile_filesystem_to_db(str(tmp_path), todos_db)
    assert second["state_updated"] == 0
    assert second["state_inserted"] == 0
    assert second["artifacts_updated"] == 0
    assert second["artifacts_inserted"] == 0
