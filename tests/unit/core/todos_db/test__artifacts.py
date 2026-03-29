"""RED tests for TodosDbArtifactsMixin — artifact persistence and versioning."""

from __future__ import annotations

import pytest

from teleclaude.core.todos_db import TodosDb

pytestmark = pytest.mark.asyncio


async def test_read_artifact_returns_empty_for_unknown(todos_db: TodosDb) -> None:
    result = await todos_db.read_artifact("slug", "requirements")
    assert result == ""


async def test_write_then_read_artifact_round_trips(todos_db: TodosDb) -> None:
    await todos_db.write_artifact("my-slug", "requirements", "# Requirements\n\nContent here.")
    result = await todos_db.read_artifact("my-slug", "requirements")
    assert result == "# Requirements\n\nContent here."


async def test_write_artifact_updates_existing(todos_db: TodosDb) -> None:
    await todos_db.write_artifact("my-slug", "requirements", "v1")
    await todos_db.write_artifact("my-slug", "requirements", "v2")
    result = await todos_db.read_artifact("my-slug", "requirements")
    assert result == "v2"


async def test_write_artifact_stores_digest(todos_db: TodosDb) -> None:
    await todos_db.write_artifact("my-slug", "input", "some content")
    digest = await todos_db.artifact_digest("my-slug", "input")
    assert isinstance(digest, str)
    assert len(digest) == 64  # SHA-256 hex


async def test_artifact_exists_returns_false_for_unknown(todos_db: TodosDb) -> None:
    assert await todos_db.artifact_exists("slug", "missing") is False


async def test_artifact_exists_returns_true_after_write(todos_db: TodosDb) -> None:
    await todos_db.write_artifact("my-slug", "input", "content")
    assert await todos_db.artifact_exists("my-slug", "input") is True


async def test_list_artifacts_returns_names(todos_db: TodosDb) -> None:
    await todos_db.write_artifact("my-slug", "input", "a")
    await todos_db.write_artifact("my-slug", "requirements", "b")
    names = await todos_db.list_artifacts("my-slug")
    assert set(names) == {"input", "requirements"}


async def test_list_artifacts_empty_for_unknown_slug(todos_db: TodosDb) -> None:
    names = await todos_db.list_artifacts("nonexistent")
    assert names == []


async def test_write_artifact_creates_version_history(todos_db: TodosDb) -> None:
    await todos_db.write_artifact("my-slug", "requirements", "v1")
    await todos_db.write_artifact("my-slug", "requirements", "v2")
    versions = await todos_db.artifact_versions("my-slug", "requirements")
    assert len(versions) == 2
    assert versions[0]["content"] == "v2"  # newest first
    assert versions[1]["content"] == "v1"


async def test_delete_artifacts_removes_all_for_slug(todos_db: TodosDb) -> None:
    await todos_db.write_artifact("my-slug", "input", "a")
    await todos_db.write_artifact("my-slug", "requirements", "b")
    await todos_db.delete_artifacts("my-slug")
    assert await todos_db.list_artifacts("my-slug") == []


async def test_delete_artifacts_removes_version_history(todos_db: TodosDb) -> None:
    await todos_db.write_artifact("my-slug", "requirements", "v1")
    await todos_db.write_artifact("my-slug", "requirements", "v2")
    await todos_db.delete_artifacts("my-slug")
    versions = await todos_db.artifact_versions("my-slug", "requirements")
    assert versions == []
